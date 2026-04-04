import sys
import math
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "apps"))

import ezdxf
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform

from slat_toolpaths import geometry_to_knife_segments, chain_segments
from gantry.roll_feed_cam import RollFeedGantry, build_roll_feed_ops
from gcode.emit_gcode import emit_gcode
from gcode.machine_ops_types import CutPath


# ------------------------------------------------------------------
# IMPORTANT: keep these aligned with filler_integration_dxf.py
# ------------------------------------------------------------------
LAYOUT_DXF_PATH = ROOT / "data" / "output" / "preview_cardboard_layout.dxf"
OUTPUT_DIR = ROOT / "data" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# From filler_integration_dxf.py conventions:
#   view_x = cardboard length
#   view_y = cardboard width
#
# Machine truth:
#   machine_x = cardboard width
#   machine_y = cardboard length / feed direction
#
# Window 0 is centered at origin in the VIEW layout.
FEED_WINDOW_LENGTH_MM = 200.0
GANTRY_WIDTH_MM = 300.0
FEED_CLEARANCE_Y_MM = 20.0

COMBINED_GCODE_OUT = OUTPUT_DIR / "filler_integration_roll_feed.nc"
WINDOW_SUMMARY_OUT = OUTPUT_DIR / "filler_integration_roll_feed_windows.txt"

GANTRY = RollFeedGantry(
    feed_window_y=FEED_WINDOW_LENGTH_MM,
    gantry_width_x=GANTRY_WIDTH_MM,
    feed_clearance_y=FEED_CLEARANCE_Y_MM,
)


def safe_geom(g):
    if g is None:
        return None
    try:
        if g.is_empty:
            return None
        fixed = g.buffer(0)
        if fixed.is_empty:
            return None
        return fixed
    except Exception:
        return None


def explode_polygons(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return [p for p in g.geoms if not p.is_empty]
    return []


def lwpolyline_to_polygon(entity):
    pts = [(p[0], p[1]) for p in entity.get_points()]
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return safe_geom(Polygon(pts))


def print_layout_layers(path: Path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    layer_names = sorted({e.dxf.layer for e in msp})
    print(">>> Layers in layout DXF:")
    for name in layer_names:
        print("   ", name)


def load_polygons_from_layer(path: Path, layer_name: str):
    path = path.resolve()
    print(f">>> Looking for layout DXF at: {path}")

    if not path.exists():
        raise FileNotFoundError(f"Layout DXF not found: {path}")

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    polys = []
    query = f'LWPOLYLINE[layer=="{layer_name}"]'
    for e in msp.query(query):
        pg = lwpolyline_to_polygon(e)
        if pg is not None:
            polys.extend(explode_polygons(pg))

    return polys


def load_cut_polygons(path: Path):
    """
    Prefer the layer name used by the current preview exporter.
    Fall back to older naming if needed.
    """
    for layer_name in ("PLACED", "PLACED_CUTS"):
        polys = load_polygons_from_layer(path, layer_name)
        print(f">>> {layer_name} polygons: {len(polys)}")
        if polys:
            print(f">>> Using layer: {layer_name}")
            return polys, layer_name

    return [], None


def print_geom_bounds(label, geoms):
    if not geoms:
        print(f"{label} BOUNDS: <empty>")
        return

    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)

    print(f"{label} BOUNDS: ({minx:.3f}, {miny:.3f}) -> ({maxx:.3f}, {maxy:.3f})")


def print_toolpath_bounds(toolpaths):
    knife_paths = toolpaths.get("knife", [])
    if not knife_paths:
        print("TOOLPATH BOUNDS: <no knife paths>")
        return

    minx = min(x for path in knife_paths for x, y in path)
    maxx = max(x for path in knife_paths for x, y in path)
    miny = min(y for path in knife_paths for x, y in path)
    maxy = max(y for path in knife_paths for x, y in path)

    print("TOOLPATH BOUNDS:", (minx, miny), "->", (maxx, maxy))


# ------------------------------------------------------------------
# VIEW -> MACHINE MAPPING
# Based directly on filler_integration_dxf.py conventions
# ------------------------------------------------------------------
def view_geom_to_machine_geom(geom):
    """
    View frame:
      x = cardboard length
      y = cardboard width

    Machine frame:
      X = cardboard width
      Y = cardboard length / feed direction
    """
    def mapper(x, y, z=None):
        return (y, x)

    return safe_geom(transform(mapper, geom))


def view_polys_to_machine_polys(polys):
    out = []
    for poly in polys:
        mg = view_geom_to_machine_geom(poly)
        if mg is not None and not mg.is_empty:
            out.extend(explode_polygons(mg))
    return out


# ------------------------------------------------------------------
# TOOLPATH BUILD
# ------------------------------------------------------------------
def build_machine_toolpaths_from_polys(cut_polys_machine):
    knife_segments = []
    for poly in cut_polys_machine:
        knife_segments.extend(geometry_to_knife_segments(poly))

    print("knife_segments:", len(knife_segments))

    knife_paths = chain_segments(knife_segments)
    toolpaths = {"knife": knife_paths, "crease": []}

    print("MACHINE knife paths:", len(toolpaths["knife"]))
    print("MACHINE knife points:", sum(len(p) for p in toolpaths["knife"]))
    print_toolpath_bounds(toolpaths)

    return toolpaths


# ------------------------------------------------------------------
# FEED WINDOW SUMMARY
# ------------------------------------------------------------------
def path_bounds(path):
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    return min(xs), min(ys), max(xs), max(ys)


def window_index_for_machine_y(y, feed_window_y):
    half = 0.5 * feed_window_y
    return math.floor((y + half) / feed_window_y)


def window_y_bounds(index, feed_window_y):
    half = 0.5 * feed_window_y
    y0 = index * feed_window_y - half
    y1 = y0 + feed_window_y
    return y0, y1


def touched_windows_for_path(path, feed_window_y):
    _, miny, _, maxy = path_bounds(path)
    start_idx = window_index_for_machine_y(miny, feed_window_y)
    end_idx = window_index_for_machine_y(maxy, feed_window_y)
    return list(range(start_idx, end_idx + 1))


def summarize_toolpaths_by_window(toolpaths, feed_window_y):
    knife_paths = toolpaths.get("knife", [])

    per_window = defaultdict(list)
    spanning = []

    for i, path in enumerate(knife_paths):
        windows = touched_windows_for_path(path, feed_window_y)
        rec = {
            "path_index": i,
            "path": path,
            "windows": windows,
            "bounds": path_bounds(path),
        }

        if len(windows) == 1:
            per_window[windows[0]].append(rec)
        else:
            spanning.append(rec)

    return dict(per_window), spanning


def write_window_summary(path: Path, per_window, spanning, feed_window_y):
    lines = []
    lines.append("Feed window summary")
    lines.append(f"feed_window_y = {feed_window_y}")
    lines.append("")

    for w in sorted(per_window.keys()):
        y0, y1 = window_y_bounds(w, feed_window_y)
        items = per_window[w]
        point_count = sum(len(rec["path"]) for rec in items)
        lines.append(
            f"window {w}: y=[{y0:.1f}, {y1:.1f}] "
            f"paths={len(items)} points={point_count}"
        )
        for rec in items:
            minx, miny, maxx, maxy = rec["bounds"]
            lines.append(
                f"  path {rec['path_index']}: "
                f"bounds=({minx:.1f}, {miny:.1f}) -> ({maxx:.1f}, {maxy:.1f})"
            )

    lines.append("")
    lines.append("Paths spanning multiple windows")
    if spanning:
        for rec in spanning:
            minx, miny, maxx, maxy = rec["bounds"]
            lines.append(
                f"  path {rec['path_index']}: windows={rec['windows']} "
                f"bounds=({minx:.1f}, {miny:.1f}) -> ({maxx:.1f}, {maxy:.1f})"
            )
    else:
        lines.append("  <none>")

    path.write_text("\n".join(lines))
    print("wrote:", path)


def main():
    print(f">>> ROOT: {ROOT}")
    print(f">>> Loading layout DXF: {LAYOUT_DXF_PATH.resolve()}")

    if not LAYOUT_DXF_PATH.exists():
        raise FileNotFoundError(f"Layout DXF not found: {LAYOUT_DXF_PATH.resolve()}")

    print_layout_layers(LAYOUT_DXF_PATH)

    cut_polys_view, used_layer = load_cut_polygons(LAYOUT_DXF_PATH)

    if not cut_polys_view:
        raise RuntimeError("No polygons found on PLACED or PLACED_CUTS layer.")

    print_geom_bounds(f"VIEW cut polys [{used_layer}]", cut_polys_view)

    cut_polys_machine = view_polys_to_machine_polys(cut_polys_view)
    print_geom_bounds("MACHINE cut polys", cut_polys_machine)

    if not cut_polys_machine:
        raise RuntimeError(f"No machine-frame polygons produced from layer {used_layer}.")

    toolpaths = build_machine_toolpaths_from_polys(cut_polys_machine)

    if not toolpaths["knife"]:
        raise RuntimeError("No knife toolpaths generated from machine-frame polygons.")

    per_window, spanning = summarize_toolpaths_by_window(
        toolpaths,
        FEED_WINDOW_LENGTH_MM,
    )

    print("\n>>> Feed window summary")
    for w in sorted(per_window.keys()):
        y0, y1 = window_y_bounds(w, FEED_WINDOW_LENGTH_MM)
        items = per_window[w]
        point_count = sum(len(rec["path"]) for rec in items)
        print(
            f"  window {w}: y=[{y0:.1f}, {y1:.1f}] "
            f"paths={len(items)} points={point_count}"
        )

    if spanning:
        print("\n>>> Paths spanning multiple windows")
        for rec in spanning:
            print(f"  path {rec['path_index']}: windows={rec['windows']}")
    else:
        print("\n>>> No paths span multiple windows")

    write_window_summary(
        WINDOW_SUMMARY_OUT,
        per_window,
        spanning,
        FEED_WINDOW_LENGTH_MM,
    )

    ops, feed_positions = build_roll_feed_ops(toolpaths, GANTRY)

    print("\n>>> Roll-feed op summary")
    print("ops:", len(ops))
    print("cutpaths:", sum(1 for o in ops if isinstance(o, CutPath)))
    print("feed_positions:", feed_positions)

    gcode = emit_gcode(ops, feed_window_y=GANTRY.feed_window_y)
    COMBINED_GCODE_OUT.write_text(gcode)

    print("wrote:", COMBINED_GCODE_OUT)
    print(">>> DONE")


if __name__ == "__main__":
    main()