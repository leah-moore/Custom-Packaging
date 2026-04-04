from __future__ import annotations

import math
from typing import List, Tuple
from pathlib import Path

import ezdxf
from svgpathtools import svg2paths


# -------------------------------------------------
# FILE CONFIG
# -------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "input" / "pliers.svg"
OUTPUT_FILE = BASE_DIR / "output" / "pliers.nc"


# -------------------------------------------------
# SIZE / SCALE CONFIG
# -------------------------------------------------

SCALE_MODE = "height"   # "none", "width", "height", "fit", "direct"

TARGET_WIDTH = 30.0
TARGET_HEIGHT = 30.0
DIRECT_SCALE = 1.0


# -------------------------------------------------
# MACHINE CONFIG
# -------------------------------------------------

SAFE_Z = 10.0
CUT_Z = 0.0

FEED_Z = 1000
FEED_XY = 2000
FEED_B = 1000

OSC_SPEED = 2000

SEGMENT_LENGTH = 1.0
LIFT_TURN_THRESHOLD = 30.0


# -------------------------------------------------
# SWIVEL AXIS CALIBRATION
# -------------------------------------------------

KNIFE_ANGLE_OFFSET = 0.0
KNIFE_SIGN = -1.0

# Distance in mm from the knife swivel center to the actual cutting tip.
KNIFE_TIP_OFFSET_MM = 0.0


def knife_angle_to_axis(angle_deg: float) -> float:
    return (angle_deg + KNIFE_ANGLE_OFFSET) * KNIFE_SIGN


def offset_tip_to_pivot(x_tip: float, y_tip: float, angle_deg: float, offset_mm: float) -> Tuple[float, float]:
    """
    Convert desired knife-tip XY to swivel-center XY.

    Args:
        x_tip, y_tip: Desired cutting tip position
        angle_deg: Knife heading in degrees
        offset_mm: Distance from swivel axis to knife tip (negative = behind)

    Returns:
        (x_pivot, y_pivot): Commanded machine position
    """
    a = math.radians(angle_deg)
    x_pivot = x_tip - offset_mm * math.cos(a)
    y_pivot = y_tip - offset_mm * math.sin(a)
    return x_pivot, y_pivot


# -------------------------------------------------
# TYPES
# -------------------------------------------------

Point = Tuple[float, float]


# -------------------------------------------------
# GEOMETRY HELPERS
# -------------------------------------------------

def compute_scale_and_bounds(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> Tuple[float, float, float, float, float, float]:
    width = max_x - min_x
    height = max_y - min_y

    if width <= 0 or height <= 0:
        raise RuntimeError("Input drawing has invalid bounds.")

    print("\n--- Original Dimensions ---")
    print(f"Min X : {min_x:.3f}")
    print(f"Max X : {max_x:.3f}")
    print(f"Min Y : {min_y:.3f}")
    print(f"Max Y : {max_y:.3f}")
    print(f"Width : {width:.3f}")
    print(f"Height: {height:.3f}")

    if SCALE_MODE == "none":
        scale_x = 1.0
        scale_y = 1.0
        print("\n--- Scale Mode ---")
        print("No scaling")

    elif SCALE_MODE == "width":
        scale_x = TARGET_WIDTH / width
        scale_y = scale_x
        print("\n--- Scale Mode ---")
        print("Scale to exact width")
        print(f"Target Width : {TARGET_WIDTH:.3f}")

    elif SCALE_MODE == "height":
        scale_y = TARGET_HEIGHT / height
        scale_x = scale_y
        print("\n--- Scale Mode ---")
        print("Scale to exact height")
        print(f"Target Height: {TARGET_HEIGHT:.3f}")

    elif SCALE_MODE == "fit":
        scale_x = TARGET_WIDTH / width
        scale_y = TARGET_HEIGHT / height
        uniform_scale = min(scale_x, scale_y)
        scale_x = uniform_scale
        scale_y = uniform_scale
        print("\n--- Scale Mode ---")
        print("Fit inside target box")
        print(f"Target Width : {TARGET_WIDTH:.3f}")
        print(f"Target Height: {TARGET_HEIGHT:.3f}")

    elif SCALE_MODE == "direct":
        scale_x = DIRECT_SCALE
        scale_y = DIRECT_SCALE
        print("\n--- Scale Mode ---")
        print("Direct scale")
        print(f"Direct Scale : {DIRECT_SCALE:.6f}")

    else:
        raise RuntimeError(f"Unsupported SCALE_MODE: {SCALE_MODE}")

    final_width = width * scale_x
    final_height = height * scale_y

    print("\n--- Applied Scale ---")
    print(f"Scale X      : {scale_x:.6f}")
    print(f"Scale Y      : {scale_y:.6f}")
    print(f"Final Width  : {final_width:.3f}")
    print(f"Final Height : {final_height:.3f}\n")

    return min_x, min_y, width, height, scale_x, scale_y


def heading_deg(p1: Point, p2: Point) -> float:
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))


def angle_diff_deg(a: float, b: float) -> float:
    diff = a - b
    while diff > 180.0:
        diff -= 360.0
    while diff < -180.0:
        diff += 360.0
    return diff


def unwrap_angle_deg(angle: float, prev_unwrapped: float | None) -> float:
    if prev_unwrapped is None:
        return angle

    while angle - prev_unwrapped > 180.0:
        angle -= 360.0
    while angle - prev_unwrapped < -180.0:
        angle += 360.0

    return angle


def dedupe_consecutive_points(points: List[Point], eps: float = 1e-9) -> List[Point]:
    if not points:
        return points

    out = [points[0]]
    for p in points[1:]:
        if abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    return out


def center_normalize_and_scale_paths(
    paths: List[List[Point]],
    min_x: float,
    min_y: float,
    width: float,
    height: float,
    scale_x: float,
    scale_y: float,
) -> List[List[Point]]:
    """
    Normalize drawing to its own bounding box, apply selected scaling,
    then center on (0,0).
    """
    final_width = width * scale_x
    final_height = height * scale_y

    x_center_offset = final_width / 2.0
    y_center_offset = final_height / 2.0

    out: List[List[Point]] = []
    for path in paths:
        out.append([
            (
                ((x - min_x) * scale_x) - x_center_offset,
                ((y - min_y) * scale_y) - y_center_offset,
            )
            for x, y in path
        ])
    return out


# -------------------------------------------------
# GCODE EMISSION HELPERS
# -------------------------------------------------

def emit_safe_lift(g: List[str]) -> None:
    g.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")


def emit_rapid_xy(g: List[str], x: float, y: float) -> None:
    emit_safe_lift(g)
    g.append(f"G0 X{x:.3f} Y{y:.3f}")


def emit_pivot_b(g: List[str], angle_deg: float) -> None:
    b = knife_angle_to_axis(angle_deg)
    g.append(f"G1 B{b:.2f} F{FEED_B}")


def emit_plunge(g: List[str], osc_on: bool) -> bool:
    emit_safe_lift(g)
    if not osc_on:
        g.append(f"M3 S{OSC_SPEED} (Start Oscillation)")
        osc_on = True
    g.append(f"G1 Z{CUT_Z:.3f} F{FEED_Z}")
    return osc_on


def emit_toolpath(g: List[str], pts: List[Point], last_emitted_angle: float | None, osc_on: bool) -> Tuple[float | None, bool]:
    pts = dedupe_consecutive_points(pts)

    if len(pts) < 2:
        return last_emitted_angle, osc_on

    start = pts[0]
    first_angle_raw = heading_deg(pts[0], pts[1])
    first_angle = unwrap_angle_deg(first_angle_raw, last_emitted_angle)

    start_x, start_y = offset_tip_to_pivot(start[0], start[1], first_angle, KNIFE_TIP_OFFSET_MM)

    emit_safe_lift(g)
    g.append(f"G0 X{start_x:.3f} Y{start_y:.3f}")
    emit_pivot_b(g, first_angle)
    osc_on = emit_plunge(g, osc_on)

    last_segment_raw = None

    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]

        raw_angle = heading_deg(p1, p2)
        angle = unwrap_angle_deg(raw_angle, last_emitted_angle)
        b = knife_angle_to_axis(angle)

        if last_segment_raw is not None:
            turn = angle_diff_deg(raw_angle, last_segment_raw)
            if abs(turn) > LIFT_TURN_THRESHOLD:
                corner_x, corner_y = offset_tip_to_pivot(p1[0], p1[1], angle, KNIFE_TIP_OFFSET_MM)
                emit_safe_lift(g)
                emit_pivot_b(g, angle)
                g.append(f"G1 Z{CUT_Z:.3f} F{FEED_Z}")
                g.append(f"G0 X{corner_x:.3f} Y{corner_y:.3f}")
                g.append(f"G1 Z{CUT_Z:.3f} F{FEED_Z}")

        x_cmd, y_cmd = offset_tip_to_pivot(p2[0], p2[1], angle, KNIFE_TIP_OFFSET_MM)
        g.append(f"G1 X{x_cmd:.3f} Y{y_cmd:.3f} B{b:.2f} F{FEED_XY}")

        last_segment_raw = raw_angle
        last_emitted_angle = angle

    emit_safe_lift(g)
    return last_emitted_angle, osc_on


# -------------------------------------------------
# DXF HANDLING
# -------------------------------------------------

def handle_dxf(g: List[str], osc_on: bool) -> bool:
    doc = ezdxf.readfile(INPUT_FILE)
    msp = doc.modelspace()

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    all_paths: List[List[Point]] = []

    for e in msp:
        etype = e.dxftype()

        if etype == "LINE":
            s = e.dxf.start
            t = e.dxf.end
            pts = [(s.x, s.y), (t.x, t.y)]
            all_paths.append(pts)

            min_x = min(min_x, s.x, t.x)
            max_x = max(max_x, s.x, t.x)
            min_y = min(min_y, s.y, t.y)
            max_y = max(max_y, s.y, t.y)

    if not all_paths:
        raise RuntimeError("No supported DXF entities found.")

    min_x, min_y, width, height, scale_x, scale_y = compute_scale_and_bounds(min_x, min_y, max_x, max_y)
    normalized_paths = center_normalize_and_scale_paths(
        all_paths, min_x, min_y, width, height, scale_x, scale_y
    )

    last_emitted_angle = None
    for pts in normalized_paths:
        last_emitted_angle, osc_on = emit_toolpath(g, pts, last_emitted_angle, osc_on)

    return osc_on


# -------------------------------------------------
# SVG HANDLING
# -------------------------------------------------

def handle_svg(g: List[str], osc_on: bool) -> bool:
    paths, _ = svg2paths(INPUT_FILE)

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    all_paths: List[List[Point]] = []

    for path in paths:
        length = path.length()
        steps = max(int(length / SEGMENT_LENGTH), 1)

        pts_complex = [path.point(t) for t in [i / steps for i in range(steps + 1)]]
        pts = [(p.real, p.imag) for p in pts_complex]
        all_paths.append(pts)

        for x, y in pts:
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

    if not all_paths:
        raise RuntimeError("No SVG paths found.")

    min_x, min_y, width, height, scale_x, scale_y = compute_scale_and_bounds(min_x, min_y, max_x, max_y)
    normalized_paths = center_normalize_and_scale_paths(
        all_paths, min_x, min_y, width, height, scale_x, scale_y
    )

    last_emitted_angle = None
    for pts in normalized_paths:
        last_emitted_angle, osc_on = emit_toolpath(g, pts, last_emitted_angle, osc_on)

    return osc_on


# -------------------------------------------------
# MAIN
# -------------------------------------------------

def main() -> None:
    g: List[str] = []
    osc_on = False

    g.append("(DXF/SVG tangential knife output with optional scaling)")
    g.append("G21")
    g.append("G17")
    g.append("G90")
    emit_safe_lift(g)

    ext = INPUT_FILE.suffix.lower()

    if ext == ".dxf":
        osc_on = handle_dxf(g, osc_on)
    elif ext == ".svg":
        osc_on = handle_svg(g, osc_on)
    else:
        raise RuntimeError("Unsupported file type. Use .dxf or .svg")

    if osc_on:
        g.append("M5 (Stop Oscillation)")
    emit_safe_lift(g)
    g.append("G0 X0.000 Y0.000")
    g.append("M2")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(g))

    print(f"Generated {OUTPUT_FILE}")


if __name__ == "__main__":
    main()