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
from gantry.roll_feed_cam import (
    RollFeedGantry,
    build_roll_feed_ops,
    plot_roll_feed_execution,
    _clip_polyline_to_y_window,
)
from gantry.roll_feed_animation import animate_roll_feed_execution

from gcode.emit_gcode import emit_gcode
from gcode.machine_ops_types import CutPath


# -------------------------------------------------
# USER INPUTS
# -------------------------------------------------

STL_PATH = Path("data/stl/input/Asymmetrical/mouse.stl")

OUTPUT_DIR = Path("data/stl/prepared/slats")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GANTRY = RollFeedGantry(
    feed_window_y=200.0,   # material advances in Y
    gantry_width_x=300.0,  # machine is limited in X
    feed_clearance_y=20.0,
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
# Coordinates are interpreted in sheet/layout space first.
# After all parts are placed, the whole layout is shifted so
# the layout bounding-box center becomes (0, 0).
#
# This only places the parts on the sheet.
# Knife B-angle still comes from emit_gcode().
MANUAL_LAYOUT = [
    ("XY_right_03", 10.0, 0.0, 0.0),
    ("XY_right_01", 120.0, 20.0, 90.0),
]

# -------------------------------------------------
# AUTO SELECTION (used only when USE_MANUAL_LAYOUT = False)
# -------------------------------------------------
# Set to None to cut everything.
SELECTED_SLAT_IDS = None
SELECT_FAMILIES = None   # e.g. {"XY"} or {"XZ"}
SELECT_SIDES = None      # e.g. {"left"} or {"right"}


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

    This keeps each part's local placement logic the same:
    - normalize part to its own lower-left
    - rotate around (0, 0)
    - normalize rotated bounds to lower-left
    - translate to requested (x, y)

    After all parts are placed, the ENTIRE layout will be shifted so that
    the layout bounding-box center becomes (0, 0).
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

    centered = [translate(g, xoff=-cx, yoff=-cy) for g in geoms]
    return centered


def validate_layout_against_gantry(laid_out_slats, gantry):
    """
    Validate layout in a center-origin coordinate system.

    With centered coordinates:
      X should typically lie within [-gantry_width_x/2, +gantry_width_x/2]
      Y is reported symmetrically around 0 for layout/debug visibility

    Note:
    This validation does NOT change machine/export coordinates.
    If your G-code emitter or machine controller requires all-positive
    coordinates, apply a final translation before emit_gcode().
    """
    if not laid_out_slats:
        raise RuntimeError("No laid out slats.")

    minx = min(g.bounds[0] for g in laid_out_slats)
    miny = min(g.bounds[1] for g in laid_out_slats)
    maxx = max(g.bounds[2] for g in laid_out_slats)
    maxy = max(g.bounds[3] for g in laid_out_slats)

    width = maxx - minx
    height = maxy - miny
    half_width_limit = gantry.gantry_width_x / 2.0

    print("CENTERED LAYOUT X RANGE:", minx, "→", maxx)
    print("CENTERED LAYOUT Y RANGE:", miny, "→", maxy)
    print("CENTERED LAYOUT SIZE:", width, "x", height)
    print("CENTER:", ((minx + maxx) / 2.0), ((miny + maxy) / 2.0))

    if minx < -half_width_limit or maxx > half_width_limit:
        print(
            f"WARNING: Layout exceeds centered gantry X limits "
            f"([{ -half_width_limit:.3f }, { half_width_limit:.3f }])"
        )


# -------------------------------------------------
# PIPELINE
# -------------------------------------------------

print(f">>> Loading STL: {STL_PATH}")

data = compute_worldgrid_from_stl(STL_PATH)

# Requires grid_slats.py to return these record lists
all_slat_records = (
    data["xy_left_records"]
    + data["xy_right_records"]
    + data["xz_left_records"]
    + data["xz_right_records"]
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

    # Keep existing packing normalization, then re-center the full layout.
    laid_out_slats = normalize_to_machine_center(laid_out_slats)

# Re-center the final layout so that (0, 0) is at the layout center.
laid_out_slats = center_layout(laid_out_slats)

validate_layout_against_gantry(laid_out_slats, GANTRY)


# -------------------------------------------------
# WORLD GEOMETRY → WORLD KNIFE PATHS
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
# ROLL-FEED EXECUTION → OPS
# -------------------------------------------------

ops, feed_positions = build_roll_feed_ops(toolpaths, GANTRY)

print("ops:", len(ops))
print("cutpaths:", sum(1 for o in ops if isinstance(o, CutPath)))


# -------------------------------------------------
# VISUALIZE ROLL-FEED EXECUTION (DEBUG)
# -------------------------------------------------

plot_roll_feed_execution(toolpaths, GANTRY, feed_positions, show_travel=True)

animate_roll_feed_execution(
    toolpaths,
    GANTRY,
    feed_positions,
    _clip_polyline_to_y_window,
)


# -------------------------------------------------
# EMIT G-CODE
# -------------------------------------------------
# Important:
# B-axis knife angle, C-axis crease angle, lift-turn behavior,
# and roller-feed A-axis logic come from emit_gcode().
#
# NOTE:
# This script now keeps geometry/toolpaths centered around (0, 0).
# If your controller or postprocessor requires all-positive machine
# coordinates, apply a final translation before emit_gcode().

gcode = emit_gcode(ops, feed_window_y=GANTRY.feed_window_y)

out = OUTPUT_DIR / "slats_roll_feed.nc"
out.write_text(gcode)

print("wrote:", out)
print(">>> DONE")