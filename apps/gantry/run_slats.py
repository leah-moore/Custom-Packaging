import sys
from pathlib import Path

# Add project root (Custom-Packaging/) to Python path
ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "apps"))

from shapely.affinity import rotate, translate

from Filler.grid_slats import compute_worldgrid_from_stl
from gantry.slat_layout_rollfeed import pack_slats_roll_feed, normalize_to_machine_center

from slat_toolpaths import (
    geometry_to_knife_segments,
    chain_segments,
)

from gantry.roll_feed_cam import RollFeedGantry

from gcode.emit_gcode import emit_gcode, get_angle, angle_diff_deg
from gcode.machine_ops_types import RapidMove, ToolDown, ToolUp, CutPath, PivotAction


# -------------------------------------------------
# USER INPUTS
# -------------------------------------------------

STL_PATH = Path("data/stl/input/Axisymmetrical/vase.stl")

# Number of generated slats in each family
# If omitted in compute_worldgrid_from_stl(...), the upstream defaults are used.
# Here we set them explicitly so you can control them from this script.
N_XY_SLATS = 3
N_XZ_SLATS = 4

OUTPUT_DIR = Path("data/stl/prepared/slats")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GANTRY = RollFeedGantry(
    feed_window_y=180.0,   # used here as single machine-window height
    gantry_width_x=280.0,  # machine width
    feed_clearance_y=20.0, # unused in single-window mode
)

# -------------------------------------------------
# MODE
# -------------------------------------------------
# True  -> manually place chosen slats by ID
# False -> auto-pack selected slats
USE_MANUAL_LAYOUT = True

# -------------------------------------------------
# MANUAL LAYOUT
# -------------------------------------------------
# Format:
#   (slat_id, x_mm, y_mm, rotation_deg)
#
# Parts are first placed in sheet/layout space, then the whole layout
# is centered so the final layout bounding-box center becomes (0, 0).
MANUAL_LAYOUT = [
    ("XY_left_01", -95.0,  30.0, 90.0),
    #("XY_left_01",  -5.0,  30.0, 90.0),
    #("XY_left_02", -95.0, -30.0, 90.0),
    #("XY_left_03",  -5.0, -30.0, 90.0),
]

# -------------------------------------------------
# AUTO SELECTION (used only when USE_MANUAL_LAYOUT = False)
# -------------------------------------------------
# Set to None to cut everything.
SELECTED_SLAT_IDS = None
SELECT_FAMILIES = None   # e.g. {"XY"} or {"XZ"}
SELECT_SIDES = {"left"}      # e.g. {"left"} or {"right"}

# -------------------------------------------------
# PIVOT THRESHOLD
# -------------------------------------------------
# Only pivot blade in air (after ToolUp) if the turn exceeds this angle.
# Set to 0.0 to always pivot after lifting, or higher to skip small adjustments.
PIVOT_ANGLE_THRESHOLD = 10.0  # degrees


# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def record_geom(rec):
    if isinstance(rec, dict):
        return rec["geom"]
    return rec.geom


def record_id(rec):
    if isinstance(rec, dict):
        return rec["slat_id"]
    return rec.slat_id


def record_family(rec):
    if isinstance(rec, dict):
        return rec.get("family")
    return getattr(rec, "family", None)


def record_side(rec):
    if isinstance(rec, dict):
        return rec.get("side")
    return getattr(rec, "side", None)


def slat_is_selected(rec):
    sid = record_id(rec)
    fam = record_family(rec)
    side = record_side(rec)

    if SELECTED_SLAT_IDS is not None and sid not in SELECTED_SLAT_IDS:
        return False

    if SELECT_FAMILIES is not None and fam not in SELECT_FAMILIES:
        return False

    if SELECT_SIDES is not None and side not in SELECT_SIDES:
        return False

    return True


def build_slat_lookup(all_slat_records):
    lookup = {}
    for rec in all_slat_records:
        geom = record_geom(rec)
        if geom is None or geom.is_empty:
            continue
        lookup[record_id(rec)] = rec
    return lookup


def place_geom(geom, x, y, rot_deg):
    """
    Rotate geometry in 2D sheet space, then place it.

    - normalize part to its own lower-left
    - rotate around (0, 0)
    - normalize rotated bounds to lower-left
    - translate to requested (x, y)
    """
    bx0, by0, bx1, by1 = geom.bounds
    g = translate(geom, xoff=-bx0, yoff=-by0)

    if abs(rot_deg) > 1e-9:
        g = rotate(g, rot_deg, origin=(0, 0), use_radians=False)
        rb0, rb1, rb2, rb3 = g.bounds
        g = translate(g, xoff=-rb0, yoff=-rb1)

    g = translate(g, xoff=x, yoff=y)
    return g


def manually_place_selected_slats(all_slat_records, manual_layout):
    lookup = build_slat_lookup(all_slat_records)
    placed = []

    for slat_id, x, y, rot_deg in manual_layout:
        if slat_id not in lookup:
            available = "\n".join(sorted(lookup.keys()))
            raise ValueError(
                f"Unknown slat_id: {slat_id}\n\nAvailable IDs:\n{available}"
            )

        rec = lookup[slat_id]
        geom = record_geom(rec)
        placed_geom = place_geom(geom, x, y, rot_deg)
        placed.append(placed_geom)

    return placed


def center_layout(geoms):
    """
    Shift all geometry so the overall layout bounding-box center lands at (0, 0).
    """
    if not geoms:
        return geoms

    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)

    cx = 0.5 * (minx + maxx)
    cy = 0.5 * (miny + maxy)

    return [translate(g, xoff=-cx, yoff=-cy) for g in geoms]


def validate_layout_against_gantry(laid_out_slats, gantry):
    """
    Validate layout in a center-origin coordinate system.

    Expected machine window:
      X in [-gantry_width_x/2, +gantry_width_x/2]
      Y in [-feed_window_y/2, +feed_window_y/2]
    """
    if not laid_out_slats:
        raise RuntimeError("No laid out slats.")

    minx = min(g.bounds[0] for g in laid_out_slats)
    miny = min(g.bounds[1] for g in laid_out_slats)
    maxx = max(g.bounds[2] for g in laid_out_slats)
    maxy = max(g.bounds[3] for g in laid_out_slats)

    width = maxx - minx
    height = maxy - miny

    half_width = gantry.gantry_width_x / 2.0
    half_height = gantry.feed_window_y / 2.0

    print("CENTERED LAYOUT X RANGE:", minx, "→", maxx)
    print("CENTERED LAYOUT Y RANGE:", miny, "→", maxy)
    print("CENTERED LAYOUT SIZE:", width, "x", height)
    print("CENTER:", ((minx + maxx) / 2.0), ((miny + maxy) / 2.0))

    if minx < -half_width or maxx > half_width:
        print(
            f"WARNING: Layout exceeds gantry X limits "
            f"([{ -half_width:.3f}, {half_width:.3f}])"
        )

    if miny < -half_height or maxy > half_height:
        print(
            f"WARNING: Layout exceeds gantry Y limits "
            f"([{ -half_height:.3f }, { half_height:.3f }])"
        )

def build_single_window_ops(toolpaths):
    """
    Convert already-centered toolpaths directly into machine ops for one
    fixed gantry window. No feed motion, no sectioning.

    For each new path:
      - compute its starting heading
      - if first path, pivot to heading
      - if heading change from previous path exceeds threshold, pivot in air
      - rapid to start
      - tool down
      - cut path
      - tool up
    """
    ops = []
    last_knife_angle = None
    last_crease_angle = None

    for path in toolpaths.get("knife", []):
        if not path or len(path) < 2:
            continue

        current_angle = get_angle(path[0], path[1])

        if last_knife_angle is None:
            ops.append(PivotAction(tool="knife", angle=current_angle))
        else:
            turn = abs(angle_diff_deg(current_angle, last_knife_angle))
            if turn > PIVOT_ANGLE_THRESHOLD:
                ops.append(PivotAction(tool="knife", angle=current_angle))

        ops.append(RapidMove(to=path[0]))
        ops.append(ToolDown(tool="knife"))
        ops.append(CutPath(path=path))
        ops.append(ToolUp())

        last_knife_angle = current_angle

    for path in toolpaths.get("crease", []):
        if not path or len(path) < 2:
            continue

        current_angle = get_angle(path[0], path[1])

        if last_crease_angle is None:
            ops.append(PivotAction(tool="crease", angle=current_angle))
        else:
            turn = abs(angle_diff_deg(current_angle, last_crease_angle))
            if turn > PIVOT_ANGLE_THRESHOLD:
                ops.append(PivotAction(tool="crease", angle=current_angle))

        ops.append(RapidMove(to=path[0]))
        ops.append(ToolDown(tool="crease"))
        ops.append(CutPath(path=path))
        ops.append(ToolUp())

        last_crease_angle = current_angle

    return ops

def plot_single_window(toolpaths, gantry, show_travel=False):
    import matplotlib.pyplot as plt

    xmin = -gantry.gantry_width_x / 2.0
    xmax =  gantry.gantry_width_x / 2.0
    ymin = -gantry.feed_window_y / 2.0
    ymax =  gantry.feed_window_y / 2.0
    margin = 10.0

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.axvspan(xmin, xmax, alpha=0.2, color="tan", zorder=0)
    ax.vlines([xmin, xmax], ymin=ymin, ymax=ymax, colors="blue", linewidth=2, zorder=1)
    ax.hlines([ymin, ymax], xmin=xmin, xmax=xmax, colors="blue", linewidth=2, zorder=1)

    last_end = None

    for path in toolpaths.get("knife", []):
        if len(path) < 2:
            continue

        xs = [p[0] for p in path]
        ys = [p[1] for p in path]
        ax.plot(xs, ys, linewidth=2, zorder=3)

        if show_travel and last_end is not None:
            ax.plot(
                [last_end[0], path[0][0]],
                [last_end[1], path[0][1]],
                linestyle="--",
                linewidth=1,
                zorder=2,
            )

        last_end = path[-1]

    for path in toolpaths.get("crease", []):
        if len(path) < 2:
            continue
        xs = [p[0] for p in path]
        ys = [p[1] for p in path]
        ax.plot(xs, ys, linestyle="--", linewidth=1.5, zorder=3)

    ax.set_xlim(xmin - margin, xmax + margin)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X (machine)")
    ax.set_ylabel("Y (machine)")
    ax.set_title("CNC VIEW — Single Gantry Window")
    ax.grid(True, alpha=0.3)
    plt.show()


# -------------------------------------------------
# PIPELINE
# -------------------------------------------------

print(f">>> Loading STL: {STL_PATH}")
print(f">>> Requested slat counts: XY={N_XY_SLATS}, XZ={N_XZ_SLATS}")

data = compute_worldgrid_from_stl(
    STL_PATH,
    n_xy=N_XY_SLATS,
    n_xz=N_XZ_SLATS,
)

xy_left_records = data["xy_left_records"]
xy_right_records = data["xy_right_records"]
xz_left_records = data["xz_left_records"]
xz_right_records = data["xz_right_records"]

print(f">>> Generated XY-left slats: {len(xy_left_records)}")
print(f">>> Generated XY-right slats: {len(xy_right_records)}")
print(f">>> Generated XZ-left slats: {len(xz_left_records)}")
print(f">>> Generated XZ-right slats: {len(xz_right_records)}")

all_slat_records = (
    xy_left_records
    + xy_right_records
    + xz_left_records
    + xz_right_records
)

all_slat_records = [
    r for r in all_slat_records
    if record_geom(r) is not None and not record_geom(r).is_empty
]

print(f">>> Total slat records: {len(all_slat_records)}")
print(">>> Available slat IDs:")
for r in all_slat_records:
    print("   ", record_id(r))


# -------------------------------------------------
# SELECT / PLACE
# -------------------------------------------------

if USE_MANUAL_LAYOUT:
    print(">>> Using MANUAL layout mode")
    print(f">>> Slats selected for cutting: {len(MANUAL_LAYOUT)}")
    for slat_id, x, y, rot in MANUAL_LAYOUT:
        print(f"    {slat_id} @ x={x:.1f}, y={y:.1f}, rot={rot:.1f}")

    laid_out_slats = manually_place_selected_slats(all_slat_records, MANUAL_LAYOUT)

else:
    print(">>> Using AUTO-PACK mode")

    selected_records = [r for r in all_slat_records if slat_is_selected(r)]

    if not selected_records:
        raise RuntimeError("No slats selected.")

    print(f">>> Selected slats: {len(selected_records)}")
    for r in selected_records:
        print("   ", record_id(r))

    raw_slats = [record_geom(r) for r in selected_records]

    laid_out_slats = pack_slats_roll_feed(
        raw_slats,
        gantry_width_x=GANTRY.gantry_width_x,
        feed_window_y=GANTRY.feed_window_y,
    )

    laid_out_slats = normalize_to_machine_center(laid_out_slats)

# Final center pass so manual and auto modes behave the same.
laid_out_slats = center_layout(laid_out_slats)

validate_layout_against_gantry(laid_out_slats, GANTRY)


# -------------------------------------------------
# WORLD GEOMETRY → KNIFE PATHS
# -------------------------------------------------

knife_segments = []
for geom in laid_out_slats:
    knife_segments.extend(geometry_to_knife_segments(geom))

knife_paths = chain_segments(knife_segments)

toolpaths = {
    "knife": knife_paths,
    "crease": [],
}

print("WORLD knife paths:", len(toolpaths["knife"]))
print("WORLD knife points:", sum(len(p) for p in toolpaths["knife"]))


# -------------------------------------------------
# SINGLE-WINDOW EXECUTION (NO FEED)
# -------------------------------------------------

ops = build_single_window_ops(toolpaths)

print("ops:", len(ops))
print("cutpaths:", sum(1 for o in ops if isinstance(o, CutPath)))


# -------------------------------------------------
# VISUALIZE
# -------------------------------------------------

plot_single_window(toolpaths, GANTRY, show_travel=True)


# -------------------------------------------------
# EMIT G-CODE
# -------------------------------------------------
# NOTE:
# This emits directly from centered machine-space paths.
# If your postprocessor/controller requires a different origin convention,
# shift coordinates before writing G-code.

gcode = emit_gcode(ops, feed_window_y=GANTRY.feed_window_y)

out = OUTPUT_DIR / "slats_single_window.nc"
out.write_text(gcode)

print("wrote:", out)
print(">>> DONE")