import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "apps"))

from Box.boxes import (
    gen_RSC,
    rebuild_edges_and_reclassify,
    rotate_90_dieline,
    normalize_to_origin,
)
from extract_toolpaths import extract_toolpaths
from gcode.emit_gcode import emit_gcode
from gcode.machine_ops_types import RapidMove, ToolDown, ToolUp, CutPath

# -------------------------------------------------
# TRUE MACHINE CONVENTION
#   X = gantry width
#   Y = feed direction
# -------------------------------------------------
GANTRY_WIDTH_X = 300.0
FEED_START_CLEARANCE_Y = 40.0

# PREVIEW ONLY:
# how much stock length to draw in the world-view plot
PREVIEW_STOCK_Y_MIN = 0.0
PREVIEW_STOCK_Y_MAX = 600.0

dim = dict(L=40, W=80, H=120)

class Material:
    thickness = 2.8

class Tooling:
    EX = 0
    score_width = 1.2


# -------------------------------------------------
# GEOMETRY HELPERS
# -------------------------------------------------
def dieline_bounds(dl):
    pts = []
    for poly in dl.cuts:
        pts.extend(poly)
    for a, b in dl.creases:
        pts.append(a)
        pts.append(b)

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def center_dieline_in_workable_x(dl, workable_x):
    xmin, xmax, _, _ = dieline_bounds(dl)
    dieline_w = xmax - xmin
    offset = 0.5 * (workable_x - dieline_w) - xmin

    def shift(p):
        return (p[0] + offset, p[1])

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for (a, b) in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {
            k: [shift(p) for p in poly]
            for k, poly in dl.debug["panels"].items()
        }

    rebuild_edges_and_reclassify(dl)


def offset_dieline_in_y(dl, dy):
    def shift(p):
        return (p[0], p[1] + dy)

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for (a, b) in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {
            k: [shift(p) for p in poly]
            for k, poly in dl.debug["panels"].items()
        }

    rebuild_edges_and_reclassify(dl)


def assert_within_gantry_width(dl, gantry_width_x):
    xmin, xmax, ymin, ymax = dieline_bounds(dl)

    print(
        f"Bounds after alignment:"
        f" X=[{xmin:.3f}, {xmax:.3f}]"
        f" Y=[{ymin:.3f}, {ymax:.3f}]"
    )

    if xmin < -1e-6 or xmax > gantry_width_x + 1e-6:
        raise RuntimeError(
            f"Dieline exceeds gantry width in X. "
            f"Got X=[{xmin:.3f}, {xmax:.3f}] but machine allows [0, {gantry_width_x:.3f}]"
        )


# -------------------------------------------------
# OPS
# NO FEED-AXIS CLIPPING
# NO WINDOW SECTIONING
# -------------------------------------------------
def build_ops_crease_then_cut(toolpaths):
    ops = []

    # CREASE FIRST
    for (a, b) in toolpaths.get("crease", []):
        ops.append(RapidMove(to=a))
        ops.append(ToolDown(tool="crease"))
        ops.append(CutPath(path=[a, b]))
        ops.append(ToolUp())

    # CUT SECOND
    for path in toolpaths.get("knife", []):
        if len(path) < 2:
            continue
        ops.append(RapidMove(to=path[0]))
        ops.append(ToolDown(tool="knife"))
        ops.append(CutPath(path=path))
        ops.append(ToolUp())

    return ops


# -------------------------------------------------
# VISUALIZATION
# VIEW ONLY:
#   horizontal axis = real machine Y (length / feed progression)
#   vertical axis   = real machine X (gantry width)
# -------------------------------------------------
def plot_toolpaths_world_view(toolpaths, gantry_width_x, stock_y_min=0.0, stock_y_max=None):
    import matplotlib.pyplot as plt

    VIEW_MARGIN = 20.0

    all_pts = []
    for path in toolpaths.get("knife", []):
        all_pts.extend(path)
    for a, b in toolpaths.get("crease", []):
        all_pts.append(a)
        all_pts.append(b)

    if not all_pts:
        raise RuntimeError("No toolpaths to plot")

    part_ys = [p[1] for p in all_pts]
    part_y_min = min(part_ys)
    part_y_max = max(part_ys)

    if stock_y_max is None:
        stock_y_max = part_y_max + 100.0

    fig, ax = plt.subplots(figsize=(12, 8))

    # Stock / board extent
    xs_rect = [stock_y_min, stock_y_max, stock_y_max, stock_y_min, stock_y_min]
    ys_rect = [0, 0, gantry_width_x, gantry_width_x, 0]
    ax.fill(xs_rect, ys_rect, alpha=0.08)
    ax.plot(xs_rect, ys_rect, linewidth=1.2)

    # Optional reference lines at part extents
    ax.vlines(
        [part_y_min, part_y_max],
        ymin=0,
        ymax=gantry_width_x,
        linestyles=":",
        linewidth=1.0,
        alpha=0.5
    )

    # Creases
    for (a, b) in toolpaths.get("crease", []):
        x1, y1 = a
        x2, y2 = b
        ax.plot(
            [y1, y2],
            [x1, x2],
            linestyle="--",
            linewidth=1.5,
        )

    # Cuts
    for path in toolpaths.get("knife", []):
        xs = [p[1] for p in path]  # plot X = real Y
        ys = [p[0] for p in path]  # plot Y = real X
        ax.plot(xs, ys, linewidth=2)
        ax.scatter(xs[0], ys[0], s=25, marker="x")

    ax.set_xlim(stock_y_min - VIEW_MARGIN, stock_y_max + VIEW_MARGIN)
    ax.set_ylim(-VIEW_MARGIN, gantry_width_x + VIEW_MARGIN)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_title("Dieline / Toolpaths — World View")
    ax.set_xlabel("Length / feed progression (real Y)")
    ax.set_ylabel("Gantry width (real X)")
    plt.show()


# -------------------------------------------------
# PIPELINE
# -------------------------------------------------
dl = gen_RSC(dim, Material(), Tooling())

# Generator lays strip progression in X.
# Real machine feed is Y, so rotate once to align strip progression to Y.
dl = rotate_90_dieline(dl)
normalize_to_origin(dl)
rebuild_edges_and_reclassify(dl)

# Real machine width is X, so center inside workable X span.
center_dieline_in_workable_x(dl, GANTRY_WIDTH_X)

# Feed enters along Y, so add start clearance in Y.
offset_dieline_in_y(dl, FEED_START_CLEARANCE_Y)

rebuild_edges_and_reclassify(dl)
assert_within_gantry_width(dl, GANTRY_WIDTH_X)

# IMPORTANT: raw preview, no fake lead-ins/outs
toolpaths = extract_toolpaths(dl, add_knife_leads=False)

plot_toolpaths_world_view(
    toolpaths,
    GANTRY_WIDTH_X,
    stock_y_min=PREVIEW_STOCK_Y_MIN,
    stock_y_max=PREVIEW_STOCK_Y_MAX,
)

ops = build_ops_crease_then_cut(toolpaths)

gcode = emit_gcode(ops)

out = Path("rsc_test.nc")
out.write_text(gcode)

print("Wrote", out)