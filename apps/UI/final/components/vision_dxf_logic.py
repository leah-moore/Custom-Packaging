#!/usr/bin/env python3
"""
Vision → DXF Integration Pipeline with Roll Feed Control
Captures multiple images from webcam, advances roll between captures,
stitches them together, detects contours, and exports to DXF.
"""

import cv2
import numpy as np
import argparse
import time
import os
import threading
from pathlib import Path
from datetime import datetime

from apps.Vision.cnc_capture import capture_image
from apps.Vision.cpd_isp.raw_image import ImagePair, RawImage
from apps.Vision.cpd_isp.stitcher import ImageStitcher
from apps.Vision.cpd_isp.dxf_generator import DxfGenerator

try:
    from apps.gantry.pi_teensy_coordination.roller_controller import RollerController
    HAS_ROLLER_CTRL = True
except ImportError:
    HAS_ROLLER_CTRL = False
    RollerController = None


DEFAULTS = {
    "device": 0,
    "num_captures": 3,
    "capture_frames": 30,
    "width": 1280,
    "height": 720,
    "exposure": -6,
    "calibration": None,

    "stitch_margin": 150.0,
    "blend_width": 10,

    "dxf_scale": 1.0,
    "dxf_min_area": 5000,
    "x_margin": 10,
    "y_margin": 10,

    # base directory for all runs
    "output_dir": "data/vision",
    "save_intermediates": True,

    "enable_roller": False,
    "overlap_estimate": 20.0,
    "roller_speed_mm_s": 100.0,
    "pre_feed_mm": 0.0,
    "post_feed_mm": 0.0,
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def ensure_output_dir(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def make_run_dirs(base_output_dir: str | Path) -> dict:
    """
    Create a unique run folder with subfolders for raw/corrected/stitching/dxf.
    """
    base_output_dir = Path(base_output_dir)
    run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = base_output_dir / run_id

    dirs = {
        "base": run_dir,
        "vision_images": run_dir / "vision_images",
        "corrected": run_dir / "vision_images" / "corrected",
        "result_stitching": run_dir / "result_stitching",
        "result_dxf": run_dir / "result_dxf",
    }

    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    return dirs


def run_vision_dxf_pipeline(cfg: dict, roller_controller=None) -> dict:
    """
    Full pipeline: pre-feed → capture → correct → feed → stitch → DXF.
    """

    run_dirs = make_run_dirs(cfg["output_dir"])

    results = {
        "run_dir": str(run_dirs["base"]),
        "vision_images_dir": str(run_dirs["vision_images"]),
        "corrected_dir": str(run_dirs["corrected"]),
        "stitching_dir": str(run_dirs["result_stitching"]),
        "dxf_dir": str(run_dirs["result_dxf"]),
        "captured_images": [],
        "corrected_images": [],
        "canvas_path": None,
        "dxf_path": None,
        "status": "running",
        "feed_log": [],
    }

    try:
        if cfg["enable_roller"] and roller_controller and cfg["pre_feed_mm"] > 0:
            log(f"Pre-feeding roller {cfg['pre_feed_mm']:.2f} mm...")
            try:
                roller_controller.feed_distance(
                    cfg["pre_feed_mm"],
                    speed_mm_s=cfg["roller_speed_mm_s"],
                    forward=True
                )
                results["feed_log"].append({
                    "step": "pre_feed",
                    "distance_mm": cfg["pre_feed_mm"],
                    "speed_mm_s": cfg["roller_speed_mm_s"],
                })
                log("  ✓ Pre-feed complete")
            except Exception as e:
                log(f"  ✗ Pre-feed failed: {e}")

        log(f"Capturing {cfg['num_captures']} images with roll advance...")
        image_pairs = []

        for i in range(cfg["num_captures"]):
            log(f"\n  Capture {i+1}/{cfg['num_captures']}...")

            img_path = capture_image(
                device=cfg["device"],
                frames=cfg["capture_frames"],
                width=cfg["width"],
                height=cfg["height"],
                exposure=cfg["exposure"],
                output_dir=str(run_dirs["vision_images"]),
                calibration=cfg["calibration"],
                post_sharpen=True,
            )

            results["captured_images"].append(str(img_path))
            log(f"    ✓ {Path(img_path).name}")

            log("    Perspective-correcting...")
            raw_img = cv2.imread(img_path)
            if raw_img is None:
                log(f"    ✗ Failed to load {img_path}")
                continue

            try:
                raw_image_obj = RawImage(raw_img)
                log(f"    ✓ Corrected to {raw_image_obj.width}×{raw_image_obj.height}")
                image_pairs.append(raw_image_obj)

                if cfg["save_intermediates"]:
                    corrected_path = run_dirs["corrected"] / f"corrected_{i:02d}.png"
                    cv2.imwrite(str(corrected_path), raw_image_obj.corrected_image)
                    results["corrected_images"].append(str(corrected_path))
                    log(f"    → saved {corrected_path.name}")

            except Exception as e:
                log(f"    ✗ Error correcting: {e}")
                continue

            if cfg["enable_roller"] and roller_controller and i < cfg["num_captures"] - 1:
                img_width_mm = raw_image_obj.width * cfg["dxf_scale"]
                overlap_mm = img_width_mm * (cfg["overlap_estimate"] / 100.0)
                feed_distance_mm = img_width_mm - overlap_mm

                log(
                    f"    Feeding roll {feed_distance_mm:.2f} mm "
                    f"(width={img_width_mm:.1f}mm, overlap={cfg['overlap_estimate']:.0f}%)..."
                )
                try:
                    roller_controller.feed_distance(
                        feed_distance_mm,
                        speed_mm_s=cfg["roller_speed_mm_s"],
                        forward=True
                    )
                    results["feed_log"].append({
                        "step": f"after_capture_{i+1}",
                        "distance_mm": feed_distance_mm,
                        "speed_mm_s": cfg["roller_speed_mm_s"],
                        "img_width_mm": img_width_mm,
                        "overlap_percent": cfg["overlap_estimate"],
                    })
                    log(f"    ✓ Fed {feed_distance_mm:.2f} mm")
                except Exception as e:
                    log(f"    ✗ Feed failed: {e}")
                    log("       (continuing without roll feed)")

            time.sleep(0.5)

        if len(image_pairs) < 2:
            raise ValueError(f"Need at least 2 corrected images; got {len(image_pairs)}")

        log(f"\n✓ Captured and corrected {len(image_pairs)} images")

        log(f"\nStitching {len(image_pairs)} images...")

        img_pair_initial = ImagePair(
            image_pairs[0].corrected_image,
            image_pairs[1].corrected_image
        )

        stitcher = ImageStitcher(
            img_pair_initial,
            margin=cfg["stitch_margin"],
            blend_width=cfg["blend_width"]
        )
        log(f"  Initial canvas: {stitcher.canvas.shape}")

        for i in range(2, len(image_pairs)):
            log(f"  Adding image {i+1}/{len(image_pairs)}...")
            img_pair = ImagePair(
                image_pairs[i-1].corrected_image,
                image_pairs[i].corrected_image
            )
            dx, dy = stitcher.add_image(img_pair)
            log(f"    Shift: dx={dx:.1f}, dy={dy:.1f} (pixels)")

            shift_mm = dx * cfg["dxf_scale"]
            results["feed_log"].append({
                "step": f"stitch_after_image_{i}",
                "measured_dx_pixels": dx,
                "measured_dx_mm": shift_mm,
            })

        stitched = stitcher.canvas
        log(f"  Final canvas: {stitched.shape}")

        canvas_path = run_dirs["result_stitching"] / "stitched_canvas.png"
        cv2.imwrite(str(canvas_path), stitched)
        results["canvas_path"] = str(canvas_path)
        log(f"  ✓ Saved canvas: {canvas_path}")

        log("\nGenerating DXF from stitched image...")

        dxf_gen = DxfGenerator(
            stitched,
            x_margin=cfg["x_margin"],
            y_margin=cfg["y_margin"]
        )
        log(f"  ROI size: {dxf_gen.width}×{dxf_gen.height}")

        dxf_gen.get_contours(min_area=cfg["dxf_min_area"])
        log(f"  Found {len(dxf_gen.big_contours)} contours (area > {cfg['dxf_min_area']})")

        if cfg["save_intermediates"]:
            dxf_gen.plot_contours()
            contours_preview = run_dirs["result_stitching"] / "contours_preview.png"
            cv2.imwrite(str(contours_preview), dxf_gen.img_contours)
            log(f"  → saved contours preview: {contours_preview}")

        dxf_path = run_dirs["result_dxf"] / "output.dxf"
        dxf_gen.contours_to_merged_dxf(
            str(dxf_path),
            scale=cfg["dxf_scale"]
        )
        results["dxf_path"] = str(dxf_path)
        log(f"  ✓ Saved DXF: {dxf_path}")

        if cfg["enable_roller"] and roller_controller and cfg["post_feed_mm"] > 0:
            log(f"\nPost-feeding roller {cfg['post_feed_mm']:.2f} mm...")
            try:
                roller_controller.feed_distance(
                    cfg["post_feed_mm"],
                    speed_mm_s=cfg["roller_speed_mm_s"],
                    forward=True
                )
                results["feed_log"].append({
                    "step": "post_feed",
                    "distance_mm": cfg["post_feed_mm"],
                    "speed_mm_s": cfg["roller_speed_mm_s"],
                })
                log("  ✓ Post-feed complete")
            except Exception as e:
                log(f"  ✗ Post-feed failed: {e}")

        results["status"] = "success"

    except Exception as e:
        log(f"\n✗ Pipeline failed: {e}")
        results["status"] = f"error: {e}"
        import traceback
        traceback.print_exc()

    return results


class VisionRunner:
    def __init__(self):
        self.camera = None
        self.camera_running = False
        self.latest_frame = None

        self.scan_running = False
        self.latest_stitched = None
        self.latest_dxf_path = None
        self.latest_run_dir = None
        self.status = "idle"

    def start_camera(self):
        if self.camera_running:
            return

        self.camera = cv2.VideoCapture(0)
        self.camera_running = True

        def loop():
            while self.camera_running:
                ret, frame = self.camera.read()
                if ret:
                    self.latest_frame = frame

        threading.Thread(target=loop, daemon=True).start()

    def stop_camera(self):
        self.camera_running = False
        if self.camera:
            self.camera.release()
            self.camera = None

    def get_latest_camera_frame(self):
        return self.latest_frame

    def start_scan(self, dxf_path=None):
        if self.scan_running:
            return

        self.scan_running = True
        self.status = "processing"

        def run():
            try:
                cfg = DEFAULTS.copy()
                results = run_vision_dxf_pipeline(cfg)

                self.latest_stitched = None
                if results.get("canvas_path"):
                    self.latest_stitched = cv2.imread(results["canvas_path"])

                self.latest_dxf_path = results.get("dxf_path")
                self.latest_run_dir = results.get("run_dir")
                self.status = "done"

            except Exception as e:
                self.status = f"error: {e}"

            self.scan_running = False

        threading.Thread(target=run, daemon=True).start()

    def stop_scan(self):
        self.scan_running = False
        self.status = "stopped"

    def get_status(self):
        return {
            "phase": self.status,
            "detail": self.status,
            "scan_running": self.scan_running,
            "camera_running": self.camera_running,
            "generated_dxf_path": self.latest_dxf_path,
            "run_dir": self.latest_run_dir,
        }

    def get_latest_stitched_image(self):
        return self.latest_stitched


def main():
    parser = argparse.ArgumentParser(
        description="Vision → DXF Pipeline: capture with roll feed, stitch, generate CNC toolpath"
    )

    parser.add_argument("--device", type=int, default=DEFAULTS["device"])
    parser.add_argument("--num-captures", type=int, default=DEFAULTS["num_captures"])
    parser.add_argument("--capture-frames", type=int, default=DEFAULTS["capture_frames"])
    parser.add_argument("--width", type=int, default=DEFAULTS["width"])
    parser.add_argument("--height", type=int, default=DEFAULTS["height"])
    parser.add_argument("--exposure", type=float, default=DEFAULTS["exposure"])
    parser.add_argument("--calibration", type=str, default=DEFAULTS["calibration"])

    parser.add_argument("--stitch-margin", type=float, default=DEFAULTS["stitch_margin"])
    parser.add_argument("--blend-width", type=int, default=DEFAULTS["blend_width"])

    parser.add_argument("--dxf-scale", type=float, default=DEFAULTS["dxf_scale"])
    parser.add_argument("--dxf-min-area", type=int, default=DEFAULTS["dxf_min_area"])
    parser.add_argument("--x-margin", type=int, default=DEFAULTS["x_margin"])
    parser.add_argument("--y-margin", type=int, default=DEFAULTS["y_margin"])

    parser.add_argument("--output-dir", type=str, default=DEFAULTS["output_dir"])
    parser.add_argument("--no-intermediates", action="store_true")

    parser.add_argument("--enable-roller", action="store_true")
    parser.add_argument("--overlap-estimate", type=float, default=DEFAULTS["overlap_estimate"])
    parser.add_argument("--roller-speed", type=float, default=DEFAULTS["roller_speed_mm_s"])
    parser.add_argument("--pre-feed", type=float, default=DEFAULTS["pre_feed_mm"])
    parser.add_argument("--post-feed", type=float, default=DEFAULTS["post_feed_mm"])

    args = parser.parse_args()

    cfg = {
        "device": args.device,
        "num_captures": args.num_captures,
        "capture_frames": args.capture_frames,
        "width": args.width,
        "height": args.height,
        "exposure": args.exposure,
        "calibration": args.calibration,
        "stitch_margin": args.stitch_margin,
        "blend_width": args.blend_width,
        "dxf_scale": args.dxf_scale,
        "dxf_min_area": args.dxf_min_area,
        "x_margin": args.x_margin,
        "y_margin": args.y_margin,
        "output_dir": args.output_dir,
        "save_intermediates": not args.no_intermediates,
        "enable_roller": args.enable_roller,
        "overlap_estimate": args.overlap_estimate,
        "roller_speed_mm_s": args.roller_speed,
        "pre_feed_mm": args.pre_feed,
        "post_feed_mm": args.post_feed,
    }

    log("=" * 70)
    log("Vision → DXF Pipeline with Roll Feed Control")
    log("=" * 70)
    log("Configuration:")
    for key, val in cfg.items():
        log(f"  {key:<25}: {val}")
    log("=" * 70)
    log("")

    roller_ctrl = None
    if cfg["enable_roller"]:
        if HAS_ROLLER_CTRL and RollerController:
            try:
                log("Initializing roll feed controller...")
                roller_ctrl = RollerController()
                log("  ✓ Roll feed controller ready")
            except Exception as e:
                log(f"  ✗ Failed to init roller: {e}")
                log("     Continuing without roll feed")
        else:
            log("  ✗ RollerController module not available")
            log("     Continuing without roll feed")

    log("")
    results = run_vision_dxf_pipeline(cfg, roller_ctrl)

    if roller_ctrl:
        try:
            roller_ctrl.cleanup()
        except Exception as e:
            log(f"Warning: roller cleanup failed: {e}")

    log("")
    log("=" * 70)
    log(f"Pipeline Status: {results['status'].upper()}")
    log("=" * 70)
    if results["run_dir"]:
        log(f"✓ Run directory: {results['run_dir']}")
    if results["dxf_path"]:
        log(f"✓ DXF output: {results['dxf_path']}")
    if results["canvas_path"]:
        log(f"✓ Canvas: {results['canvas_path']}")
    if results["corrected_images"]:
        log(f"✓ Corrected images: {len(results['corrected_images'])} saved")
    if results["feed_log"]:
        log(f"\nRoll Feed Operations ({len(results['feed_log'])} total):")
        for i, feed_op in enumerate(results["feed_log"], 1):
            step = feed_op.get("step", "unknown")
            if "distance_mm" in feed_op:
                log(f"  {i}. {step}: {feed_op['distance_mm']:.2f} mm @ {feed_op['speed_mm_s']:.1f} mm/s")
            else:
                log(f"  {i}. {step}")


if __name__ == "__main__":
    main()