#!/usr/bin/env python3
"""
CNC Bed Webcam Capture
Captures high-quality images from a cheap webcam using frame averaging
and optional lens distortion correction.
"""

import cv2
import numpy as np
import argparse
import time
import os
from pathlib import Path
import sys


# ─── Defaults ─────────────────────────────────────────────────────────────────

DEFAULTS = {
    "device":       0,      # Camera index
    "frames":       30,     # Frames to average (more = less noise, slower)
    "width":        1280,
    "height":       720,
    "exposure":     -6,     # Tune with cnc_probe.py — aim for brightness 100-200
    "output_dir":   ".",
    "calibration":  None,   # Path to calibration .npz for lens undistortion
    "post_sharpen": True,   # Unsharp mask after averaging
}


# ─── Capture ──────────────────────────────────────────────────────────────────

def capture_averaged(cap: cv2.VideoCapture, n_frames: int) -> np.ndarray:
    """Average n frames to cancel random sensor noise (SNR improves by √n)."""
    print(f"Capturing {n_frames} frames...", end=" ", flush=True)
    accumulator = None
    for i in range(n_frames):
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError(f"Frame grab failed at frame {i}")
        f32 = frame.astype(np.float32)
        accumulator = f32 if accumulator is None else accumulator + f32
    print("done.")
    return (accumulator / n_frames).astype(np.uint8)


# ─── Post-Processing ──────────────────────────────────────────────────────────

def unsharp_mask(img: np.ndarray,
                 radius: float = 1.5,
                 strength: float = 0.7) -> np.ndarray:
    """Enhance real edges without amplifying noise."""
    k = int(radius * 6) | 1
    blurred = cv2.GaussianBlur(img, (k, k), radius)
    return cv2.addWeighted(img, 1 + strength, blurred, -strength, 0)


def correct_distortion(img: np.ndarray, calib_file: str) -> np.ndarray:
    """Undistort using calibration matrix from --calibrate mode."""
    data = np.load(calib_file)
    mtx  = data["camera_matrix"]
    dist = data["dist_coeffs"]
    h, w = img.shape[:2]
    new_mtx, roi = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))
    undistorted  = cv2.undistort(img, mtx, dist, None, new_mtx)
    x, y, rw, rh = roi
    return undistorted[y:y+rh, x:x+rw] if all([rw, rh]) else undistorted


# ─── Lens Calibration ─────────────────────────────────────────────────────────

def run_calibration(device: int, width: int, height: int,
                    cols: int = 8, rows: int = 5,
                    n_samples: int = 15,
                    output: str = "calibration.npz"):
    """
    Interactive lens calibration using a printed checkerboard.
    Generate one at: https://calib.io/pages/camera-calibration-pattern-generator
    Hold it at different angles/distances. SPACE = capture, Q = finish.
    """
    cap = open_camera(device)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    obj_points, img_points = [], []

    print(f"Calibration mode — need {n_samples} samples. SPACE=capture  Q=done\n")

    while len(obj_points) < n_samples:
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, (cols, rows), None)
        display = frame.copy()
        if found:
            cv2.drawChessboardCorners(display, (cols, rows), corners, found)
            cv2.putText(display, "SPACE to capture", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        else:
            cv2.putText(display, "No board found", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.putText(display, f"Samples: {len(obj_points)}/{n_samples}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
        cv2.imshow("Calibration", display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(' ') and found:
            corners2 = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            obj_points.append(objp)
            img_points.append(corners2)
            print(f"  Sample {len(obj_points)}/{n_samples}")
        elif key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(obj_points) < 4:
        print("Not enough samples — aborted.")
        return

    print("Computing calibration...", end=" ")
    h, w = gray.shape
    _, mtx, dist, _, _ = cv2.calibrateCamera(obj_points, img_points, (w, h), None, None)
    np.savez(output, camera_matrix=mtx, dist_coeffs=dist)
    print(f"done. Saved to {output}")

def open_camera(device):
    if sys.platform.startswith("win"):
        return cv2.VideoCapture(device, cv2.CAP_DSHOW)
    else:
        return cv2.VideoCapture(device, cv2.CAP_V4L2)

# ─── Main ─────────────────────────────────────────────────────────────────────

def capture(cfg: dict) -> str:
    # Open fresh, set exposure only — don't touch other settings.
    # This camera ignores AUTO_EXPOSURE and has its own AE logic;
    # too many warmup frames lets it override our exposure setting.
    cap = open_camera(cfg["device"])
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera device {cfg['device']}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  cfg["width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg["height"])
    time.sleep(0.2)
    cap.set(cv2.CAP_PROP_EXPOSURE, cfg["exposure"])

    print("Settling...", end=" ", flush=True)
    for _ in range(10):
        cap.read()
    print("done.")

    image = capture_averaged(cap, cfg["frames"])
    cap.release()

    if cfg["calibration"] and os.path.exists(cfg["calibration"]):
        print("Undistorting...", end=" ", flush=True)
        image = correct_distortion(image, cfg["calibration"])
        print("done.")

    if cfg["post_sharpen"]:
        print("Sharpening...", end=" ", flush=True)
        image = unsharp_mask(image)
        print("done.")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(cfg["output_dir"]) / f"cnc_{ts}.png"
    cv2.imwrite(str(out_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    print(f"\n✓ Saved: {out_path}")
    return str(out_path)


def capture_image(
    device=None,
    frames=None,
    width=None,
    height=None,
    exposure=None,
    output_dir=None,
    calibration=None,
    post_sharpen=True,
):
    """
    Capture a high-quality image from the webcam.
    All parameters fall back to DEFAULTS if not provided.
    Returns the path to the saved image.
    """
    cfg = {
        "device":      device      if device      is not None else DEFAULTS["device"],
        "frames":      frames      if frames      is not None else DEFAULTS["frames"],
        "width":       width       if width       is not None else DEFAULTS["width"],
        "height":      height      if height      is not None else DEFAULTS["height"],
        "exposure":    exposure    if exposure    is not None else DEFAULTS["exposure"],
        "output_dir":  output_dir  if output_dir  is not None else DEFAULTS["output_dir"],
        "calibration": calibration if calibration is not None else DEFAULTS["calibration"],
        "post_sharpen": post_sharpen,
    }
    os.makedirs(cfg["output_dir"], exist_ok=True)
    return capture(cfg)  # make sure capture() returns the saved path


def main():
    p = argparse.ArgumentParser(description="CNC webcam high-quality capture")
    p.add_argument("--device",      type=int,   default=DEFAULTS["device"])
    p.add_argument("--frames",      type=int,   default=DEFAULTS["frames"],
                   help="Frames to average (default: 30)")
    p.add_argument("--width",       type=int,   default=DEFAULTS["width"])
    p.add_argument("--height",      type=int,   default=DEFAULTS["height"])
    p.add_argument("--exposure",    type=float, default=DEFAULTS["exposure"],
                   help="Exposure value from cnc_probe.py (e.g. -6)")
    p.add_argument("--output-dir",  type=str,   default=DEFAULTS["output_dir"])
    p.add_argument("--calibration", type=str,   default=DEFAULTS["calibration"],
                   help="Path to calibration .npz for lens undistortion")
    p.add_argument("--no-sharpen",  action="store_true",
                   help="Skip unsharp mask")
    p.add_argument("--calibrate",   action="store_true",
                   help="Run interactive lens calibration instead of capturing")
    args = p.parse_args()

    if args.calibrate:
        run_calibration(args.device, args.width, args.height)
        return

    cfg = {
        "device":       args.device,
        "frames":       args.frames,
        "width":        args.width,
        "height":       args.height,
        "exposure":     args.exposure,
        "output_dir":   args.output_dir,
        "calibration":  args.calibration,
        "post_sharpen": not args.no_sharpen,
    }

    os.makedirs(cfg["output_dir"], exist_ok=True)
    capture(cfg)


if __name__ == "__main__":
    main()