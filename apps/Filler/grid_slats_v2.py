# apps/grid_slats.py
#
# Python port of MATLAB "Vase Cross Sections → Half-Grid (XY + XZ), world-consistent & equal boards"
#
# GOAL FIX: ignore the *inside* of the object (inner wall) completely.
# We therefore compute an OUTER-ENVELOPE silhouette per slice, instead of using filled polygons
# (which preserve inner-wall/topology and can create double outlines on shelled meshes).
#
# ADDITIONAL FIX:
# photogrammetry meshes may contain missing regions / holes that create ugly,
# physically meaningless slat artifacts (skinny spikes, shelves, bites, scraps).
# We therefore apply a minimum-feature cleanup to each slat AFTER open-pocket
# construction and BEFORE slot cutting.
#
# ENVELOPE SMOOTHING:
# primary smoothing happens on the 1D scanline envelope before polygon creation.
# This version uses:
#   1) median filter
#   2) gaussian filter
#   3) curvature relaxation
# instead of a slope clamp, to avoid creating long artificial ramps.

from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import dataclass

# Add the "apps" folder to Python path
APPS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APPS_DIR))

import warnings
import numpy as np
import trimesh

import matplotlib
matplotlib.use("MacOSX")   # better than TkAgg on Mac

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box, LineString
from shapely.ops import unary_union
from shapely.errors import TopologicalError
import shapely.affinity

from Cardboard.corrugated import plot_corrugated_board

# ---------------- USER SETTINGS ----------------
USE_BLADE_SEGMENTS = False
BLADE_TOL = 1

# conditional import
if USE_BLADE_SEGMENTS:
    from Filler.blade_segments import segmentize_list
else:
    def segmentize_list(x, tol):
        return x

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------- USER SETTINGS ----------------
INPUT_STL = Path("data/stl/input/Axisymmetrical/vase.stl")  # change if needed

# ---------------- SYMMETRY MODE ----------------
# Options:
#   "axis"   -> rotational symmetry around Z (vases, bowls)
#   "plane"  -> mirror symmetry about X=0
#   "none"   -> fully asymmetrical object

SYMMETRY = "none"
# ----------------------------------------------

# ---------------- VISUALISATION ----------------
# Options:
#   "all"    -> show everything (default)
#   "right"  -> show only +X side
#   "left"   -> show only mirrored -X side
SHOW_SLATS = "all"
# -----------------------------------------------

materialT   = 3.0      # sheet thickness (mm)
kerfFit     = 0.15     # extra width to fit (kerf + wiggle) (mm)

DEFAULT_N_XY = 5
DEFAULT_N_XZ = 5

margin      = 5.0      # board margin (mm)
clearance   = 0.0      # expand/shrink silhouette cutout (mm)
previewT    = 8.0      # visual thickness for 3D preview (mm)
fixGapMin   = 2        # bridge band width to FORCE open pocket to left edge (mm)
slotSafety  = max(kerfFit, 0.6)
showPlanes  = False

SHOW_ASSEMBLY_VIZ = False

bottomExtra = margin
sidePadX    = margin

MIN_SLAT_OVERHANG = 2.0   # mm — minimum material past silhouette
MIN_CARDBOARD_WIDTH = 1.0 # mm; raise if spikes remain, lower if you lose detail

# silhouette robustness
SNAP        = 1e-3
DUST_AREA   = 5.0

# NOTE: FORCE_SOLID/RM_HOLES are kept for compatibility with your toggles,
# but envelope silhouettes do not require them and they are not used.
FORCE_SOLID = False
RM_HOLES    = False

# plotting
MESH_ALPHA  = 0.18
PLANE_ALPHA = 0.06
PLANE_RES   = 18
CONTOUR_EPS = 0.05

CUT_BOTH_SIDES = True

# ================================================
# ENVELOPE SMOOTHING CONTROLS
# ================================================
USE_ENVELOPE_SMOOTHING = True

# odd numbers work best
ENVELOPE_MEDIAN_WINDOW   = 9
ENVELOPE_GAUSSIAN_WINDOW = 9

# curvature-based smoothing
ENVELOPE_CURVATURE_STRENGTH = 0.30
ENVELOPE_CURVATURE_PASSES   = 3

# envelope silhouette sampling density (higher = smoother, slower)
ENVELOPE_SAMPLES = 700
# ================================================

# ================================================
# POLYGON-LEVEL SMOOTHING CONTROLS
# ================================================
# Keep these mild now that envelope smoothing is primary.
SIMPLIFY_TOLERANCE = 0.4
USE_MORPH_SMOOTH = False
MORPH_EXPAND = 0.3
MORPH_SHRINK = 0.3
# ================================================

# ================================================
# PHOTOGRAMMETRY ARTIFACT CLEANUP
# ================================================
MIN_FEATURE_SIZE = 2.5   # mm
CLEAN_MIN_AREA   = 20.0  # mm^2
POST_SLOT_CLEANUP = False
# ================================================


@dataclass
class SlatRecord:
    slat_id: str
    family: str          # "XY" or "XZ"
    index: int
    geom: object
    plane_value: float   # Z for XY slats, Y for XZ slats
    plane_axis: str      # "Z" or "Y"
    side: str            # "right" or "left"


def build_slat_records(geoms, family, side, plane_axis, plane_values):
    records = []
    for i, (geom, plane_value) in enumerate(zip(geoms, plane_values)):
        records.append(
            SlatRecord(
                slat_id=f"{family}_{side}_{i:02d}",
                family=family,
                index=i,
                geom=geom,
                plane_value=float(plane_value),
                plane_axis=plane_axis,
                side=side,
            )
        )
    return records


def symmetry_config():
    if SYMMETRY in ("axis", "plane"):
        xMin = 0.0
        half = "right"
    elif SYMMETRY == "none":
        xMin = 0.0
        half = "both"
    else:
        raise ValueError(f"Unknown SYMMETRY: {SYMMETRY}")


# =========================
# Shapely + mesh utilities
# =========================

def safe_geom(g):
    if g is None or getattr(g, "is_empty", True):
        return None
    try:
        if hasattr(g, "is_valid") and (not g.is_valid):
            g = g.buffer(0)
        return None if g.is_empty else g
    except TopologicalError:
        return None


def bridge_short_dips(a2, x, min_depth_mm):
    """
    Remove shallow inward dents in the envelope.

    If a dip is shallower than min_depth_mm in X,
    clamp it back to the outer baseline.
    """
    if min_depth_mm <= 0 or len(x) < 5:
        return x

    x = np.asarray(x, float)

    left_max  = np.maximum.accumulate(x)
    right_max = np.maximum.accumulate(x[::-1])[::-1]
    baseline  = np.minimum(left_max, right_max)

    dent_depth = baseline - x

    x2 = x.copy()
    mask = dent_depth < min_depth_mm
    x2[mask] = baseline[mask]

    return x2


def explode_polys(g):
    if g is None or g.is_empty:
        return []
    t = g.geom_type
    if t == "Polygon":
        return [g]
    if t == "MultiPolygon":
        return list(g.geoms)
    if t == "GeometryCollection":
        out = []
        for gg in g.geoms:
            out.extend(explode_polys(gg))
        return out
    return []


def center_like_matlab(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    V = mesh.vertices.copy()
    center = 0.5 * (V.min(axis=0) + V.max(axis=0))
    V -= center
    m = mesh.copy()
    m.vertices = V
    return m


def section_polylines(mesh: trimesh.Trimesh, origin, normal):
    sec = mesh.section(plane_origin=np.asarray(origin), plane_normal=np.asarray(normal))
    return [] if sec is None or sec.discrete is None else sec.discrete


def halfspace_mask(x_min, x_max, a2_min, a2_max, half: str):
    midX = 0.0
    h = half.lower()
    if h == "left":
        return Polygon([(x_min, a2_min), (midX, a2_min), (midX, a2_max), (x_min, a2_max)])
    if h == "right":
        return Polygon([(midX, a2_min), (x_max, a2_min), (x_max, a2_max), (midX, a2_max)])
    return Polygon([(x_min, a2_min), (x_max, a2_min), (x_max, a2_max), (x_min, a2_max)])


def _collect_lines_from_section(polylines, proj_cols, snap=1e-3):
    """
    Project 3D section polylines into 2D LineStrings in a world-consistent axis frame
    (XY uses (X,Y), XZ uses (X,Z)).
    """
    lines = []
    for P in polylines:
        if P is None or len(P) < 2:
            continue
        Q = np.asarray(P[:, list(proj_cols)], dtype=float)
        Q = np.round(Q / snap) * snap
        if len(Q) < 2:
            continue
        ln = safe_geom(LineString(Q))
        if ln is not None and ln.length > snap:
            lines.append(ln)
    return lines


def draw_geom_with_vis(ax, geom, fixed_value, mode, color, lw_main=1.8, lw_mirror=1.2):
    if geom is None or geom.is_empty:
        return

    if SHOW_SLATS in ("all", "right"):
        plot_geom_outline_3d(
            ax,
            geom,
            fixed_value,
            mode=mode,
            color=color,
            lw=lw_main,
        )

    if SHOW_SLATS in ("all", "left") and SYMMETRY in ("axis", "plane"):
        plot_geom_outline_3d(
            ax,
            mirror_geom_x(geom),
            fixed_value,
            mode=mode,
            color=color,
            lw=lw_mirror,
        )


def _odd_window(window: int, n: int) -> int:
    w = int(max(1, window))
    if w % 2 == 0:
        w += 1
    if n <= 1:
        return 1
    if w > n:
        w = n if (n % 2 == 1) else (n - 1)
    return max(w, 1)


def _gaussian_kernel1d(window: int) -> np.ndarray:
    if window <= 1:
        return np.array([1.0], dtype=float)
    sigma = max(window / 3.0, 1e-6)
    r = window // 2
    x = np.arange(-r, r + 1, dtype=float)
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    k /= k.sum()
    return k


def _median_filter_1d(xs: np.ndarray, window: int) -> np.ndarray:
    n = len(xs)
    w = _odd_window(window, n)
    if w <= 1:
        return xs.copy()

    r = w // 2
    padded = np.pad(xs, (r, r), mode="edge")
    out = np.empty_like(xs)

    for i in range(n):
        out[i] = np.median(padded[i:i + w])

    return out


def _gaussian_filter_1d(xs: np.ndarray, window: int) -> np.ndarray:
    n = len(xs)
    w = _odd_window(window, n)
    if w <= 1:
        return xs.copy()

    r = w // 2
    padded = np.pad(xs, (r, r), mode="edge")
    kernel = _gaussian_kernel1d(w)
    out = np.empty_like(xs)

    for i in range(n):
        out[i] = np.sum(padded[i:i + w] * kernel)

    return out


def _curvature_relax_1d(xs: np.ndarray, strength: float = 0.35, passes: int = 3) -> np.ndarray:
    """
    Smooth by relaxing second differences (discrete curvature),
    not by clamping first differences (slope).

    This reduces wiggles while avoiding long artificial ramps.
    """
    xs = np.asarray(xs, dtype=float).copy()
    n = len(xs)
    if n < 5 or strength <= 0 or passes <= 0:
        return xs

    out = xs.copy()

    for _ in range(passes):
        prev = out.copy()
        out[1:-1] = prev[1:-1] + strength * (
            0.5 * (prev[:-2] + prev[2:]) - prev[1:-1]
        )
        out[0] = xs[0]
        out[-1] = xs[-1]

    return out


def smooth_envelope_points(
    xs,
    a2s,
    median_window=9,
    gaussian_window=9,
    curvature_strength=0.35,
    curvature_passes=3,
):
    """
    Smooth the envelope as a 1D signal x = f(a2).

    Passes:
      1) median   -> remove spikes / local scan glitches
      2) gaussian -> soften remaining roughness
      3) curvature relax -> smooth wiggles without forcing straight ramps
    """
    xs = np.asarray(xs, dtype=float)
    if len(xs) < 5:
        return xs

    sm = _median_filter_1d(xs, median_window)
    sm = _gaussian_filter_1d(sm, gaussian_window)
    sm = _curvature_relax_1d(
        sm,
        strength=curvature_strength,
        passes=curvature_passes,
    )

    sm[0] = xs[0]
    sm[-1] = xs[-1]
    return sm


def morph_smooth(poly, expand_mm=0.3, shrink_mm=0.3):
    """
    Dilate → erode to smooth without losing shape.
    """
    if poly is None or poly.is_empty:
        return poly

    expanded = safe_geom(poly.buffer(expand_mm))
    if expanded is None:
        return poly

    smoothed = safe_geom(expanded.buffer(-shrink_mm))
    return smoothed if smoothed is not None else poly


def cleanup_slat(pg, feature_size=2.5, min_area=20.0):
    """
    Remove scan-damage artifacts from a finished slat polygon.
    """
    if pg is None or pg.is_empty:
        return pg

    g = safe_geom(pg)
    if g is None:
        return pg

    r = 0.5 * float(feature_size)

    g = safe_geom(g.buffer(r).buffer(-r))
    if g is None or g.is_empty:
        return pg

    g2 = safe_geom(g.buffer(-r).buffer(r))
    if g2 is not None and not g2.is_empty:
        g = g2

    parts = [p for p in explode_polys(g) if p.area >= min_area]
    if not parts:
        return pg

    return safe_geom(unary_union(parts))


def finalize_slat(pg):
    if pg is None or pg.is_empty:
        return pg
    return cleanup_slat(
        pg,
        feature_size=MIN_FEATURE_SIZE,
        min_area=CLEAN_MIN_AREA,
    )

def envelope_silhouette_polygon_from_lines(
    lines,
    x_min, x_max,
    a2_min, a2_max,
    half="right",
    nsamples=250,   # 🔥 reduced from 700
    eps=1e-6,
    use_envelope_smoothing=True,
    median_window=9,
    gaussian_window=9,
    curvature_strength=0.35,
    curvature_passes=3,
):
    if not lines:
        return None

    L = safe_geom(unary_union(lines))
    if L is None:
        return None

    ys = np.linspace(a2_min, a2_max, nsamples)
    env = []

    def collect_xs(inter, xs):
        if inter.is_empty:
            return
        t = inter.geom_type
        if t == "Point":
            xs.append(inter.x)
        elif t in ("MultiPoint", "GeometryCollection"):
            for gg in inter.geoms:
                collect_xs(gg, xs)
        elif t in ("LineString", "LinearRing"):
            coords = list(inter.coords)
            xs.extend([coords[0][0], coords[-1][0]])
        elif t == "MultiLineString":
            for gg in inter.geoms:
                collect_xs(gg, xs)

    h = half.lower()

    for y in ys:
        scan = LineString([(x_min, y), (x_max, y)])
        inter = L.intersection(scan)

        xs = []
        collect_xs(inter, xs)

        # 🔥 KEY FIX: DON'T SKIP → insert NaN
        if not xs:
            env.append((np.nan, y))
            continue

        xs = np.asarray(xs, dtype=float)
        xs.sort()

        if h == "right":
            env.append((xs[-1], y))
        elif h == "left":
            env.append((xs[0], y))
        else:
            env.append((xs[0], xs[-1], y))

    # -------------------------
    # BUILD POLYGON (FIXED)
    # -------------------------

    if h == "right":
        xs = np.array([p[0] for p in env], dtype=float)
        a2s = np.array([p[1] for p in env], dtype=float)

        # 🔥 REMOVE NaNs → prevents fake bridges
        mask = np.isfinite(xs)
        xs = xs[mask]
        a2s = a2s[mask]

        if len(xs) < 3:
            return None

        if use_envelope_smoothing:
            xs = smooth_envelope_points(
                xs,
                a2s,
                median_window=median_window,
                gaussian_window=gaussian_window,
                curvature_strength=curvature_strength,
                curvature_passes=curvature_passes,
            )

        xs = bridge_short_dips(a2s, xs, MIN_CARDBOARD_WIDTH)

        ring = [(x_min, a2s[0])] + list(zip(xs, a2s)) + [(x_min, a2s[-1])]
        return safe_geom(Polygon(ring))

    if h == "left":
        xs = np.array([p[0] for p in env], dtype=float)
        a2s = np.array([p[1] for p in env], dtype=float)

        mask = np.isfinite(xs)
        xs = xs[mask]
        a2s = a2s[mask]

        if len(xs) < 3:
            return None

        if use_envelope_smoothing:
            xs_m = smooth_envelope_points(
                -xs,
                a2s,
                median_window=median_window,
                gaussian_window=gaussian_window,
                curvature_strength=curvature_strength,
                curvature_passes=curvature_passes,
            )
            xs = -xs_m

        xs = -bridge_short_dips(a2s, -xs, MIN_CARDBOARD_WIDTH)

        ring = [(x_max, a2s[0])] + list(zip(xs, a2s)) + [(x_max, a2s[-1])]
        return safe_geom(Polygon(ring))

    # (both case unchanged)
    if len(env) < 3:
        return None

    left = np.array([p[0] for p in env], dtype=float)
    right = np.array([p[1] for p in env], dtype=float)
    a2s = np.array([p[2] for p in env], dtype=float)

    mask = np.isfinite(left) & np.isfinite(right)
    left = left[mask]
    right = right[mask]
    a2s = a2s[mask]

    if len(a2s) < 3:
        return None

    if use_envelope_smoothing:
        left = smooth_envelope_points(left, a2s)
        right = smooth_envelope_points(right, a2s)

    ring = list(zip(right, a2s)) + list(zip(left[::-1], a2s[::-1]))
    return safe_geom(Polygon(ring))

def outer_silhouette_2d(
    mesh: trimesh.Trimesh,
    origin, normal,
    proj_cols=(0, 1),
    x_min=-1e9, x_max=1e9,
    a2_min=-1e9, a2_max=1e9,
    half="right",
    snap=1e-3,
    dust_area=5.0,
    force_solid=False,
    rm_holes=False,
    clearance=0.0,
    simplify_tolerance=0.5,
    use_morph_smooth=False,
    morph_expand=0.3,
    morph_shrink=0.3,
):
    """
    OUTER-ENVELOPE silhouette (ignores interior walls):
      section -> polylines -> 2D lines -> scanline envelope polygon -> clip -> clearance.
    """
    polylines = section_polylines(mesh, origin, normal)
    if not polylines:
        return None

    lines = _collect_lines_from_section(polylines, proj_cols=proj_cols, snap=snap)
    if not lines:
        return None

    U = envelope_silhouette_polygon_from_lines(
        lines,
        x_min=x_min, x_max=x_max,
        a2_min=a2_min, a2_max=a2_max,
        half=half,
        nsamples=ENVELOPE_SAMPLES,
        use_envelope_smoothing=USE_ENVELOPE_SMOOTHING,
        median_window=ENVELOPE_MEDIAN_WINDOW,
        gaussian_window=ENVELOPE_GAUSSIAN_WINDOW,
        curvature_strength=ENVELOPE_CURVATURE_STRENGTH,
        curvature_passes=ENVELOPE_CURVATURE_PASSES,
    )
    if U is None or U.is_empty or U.area < dust_area:
        return None

    U = safe_geom(U.simplify(tolerance=simplify_tolerance, preserve_topology=True))
    if U is None or U.is_empty:
        return None

    if use_morph_smooth:
        U = morph_smooth(U, expand_mm=morph_expand, shrink_mm=morph_shrink)
        if U is None or U.is_empty:
            return None

    mask = halfspace_mask(x_min, x_max, a2_min, a2_max, half)
    I = safe_geom(U.intersection(mask))
    if I is None or I.is_empty or I.area < dust_area:
        return None

    if abs(clearance) > 1e-9:
        I = safe_geom(I.buffer(float(clearance)))
        I = safe_geom(I.buffer(0)) if I is not None else None
        if I is None:
            return None

    return I


# =========================
# Board / slot operations
# =========================

def line_poly_intersect_x(poly, y_or_z, x_range):
    x0, x1 = x_range
    scan = LineString([(x0, y_or_z), (x1, y_or_z)])
    inter = poly.intersection(scan)
    xs = []

    def collect(g):
        if g.is_empty:
            return
        t = g.geom_type
        if t == "Point":
            xs.append(g.x)
        elif t in ("MultiPoint", "GeometryCollection"):
            for gg in g.geoms:
                collect(gg)
        elif t in ("LineString", "LinearRing"):
            coords = list(g.coords)
            xs.extend([coords[0][0], coords[-1][0]])
        elif t == "MultiLineString":
            for gg in g.geoms:
                collect(gg)

    collect(inter)
    xs = np.array(xs, dtype=float)
    if xs.size == 0:
        return []
    xs.sort()

    out = [xs[0]]
    for v in xs[1:]:
        if abs(v - out[-1]) > 1e-6:
            out.append(v)
    return out


def keep_only_touching_frame(pg, frame_bounds, eps=1e-3):
    if pg is None or pg.is_empty:
        return pg
    parts = explode_polys(pg)
    if len(parts) <= 1:
        return pg

    xmin, ymin, xmax, ymax = frame_bounds
    touching = []
    for p in parts:
        V = np.asarray(p.exterior.coords)
        touch = np.any(
            (np.abs(V[:, 0] - xmin) < eps) |
            (np.abs(V[:, 0] - xmax) < eps) |
            (np.abs(V[:, 1] - ymin) < eps) |
            (np.abs(V[:, 1] - ymax) < eps)
        )
        if touch:
            touching.append(p)

    if touching:
        return safe_geom(unary_union(touching))

    parts.sort(key=lambda pp: pp.area, reverse=True)
    return parts[0]


def remove_small_parts(pg, min_area=10.0):
    if pg is None or pg.is_empty:
        return pg

    parts = [p for p in explode_polys(pg) if p.area >= min_area]
    if not parts:
        return None

    return safe_geom(unary_union(parts))


def make_open_pocket(board_rect, cutout, x_min, a2_min, a2_max, fix_gap_min):
    if cutout is None or cutout.is_empty:
        return board_rect

    band = box(x_min, a2_min, x_min + fix_gap_min, a2_max)
    cut_open = safe_geom(cutout.union(band))
    if cut_open is None:
        return board_rect

    return safe_geom(board_rect.difference(cut_open))


def make_open_pocket_right(board_rect, cutout, x_min, a2_min, a2_max, fix_gap_min):
    if cutout is None or cutout.is_empty:
        return board_rect

    band = box(x_min, a2_min, x_min + fix_gap_min, a2_max)
    cut_open = safe_geom(cutout.union(band))
    if cut_open is None:
        return board_rect

    return safe_geom(board_rect.difference(cut_open))


def make_open_pocket_left(board_rect, cutout, x_max, a2_min, a2_max, fix_gap_min):
    if cutout is None or cutout.is_empty:
        return board_rect

    band = box(x_max - fix_gap_min, a2_min, x_max, a2_max)
    cut_open = safe_geom(cutout.union(band))
    if cut_open is None:
        return board_rect

    return safe_geom(board_rect.difference(cut_open))


def enforce_min_overhang_against_board(cutout, board_rect, min_overhang):
    """
    Ensure the cutout does NOT approach the FAR board edge
    closer than min_overhang.
    """
    if cutout is None or cutout.is_empty:
        return cutout

    bx0, by0, bx1, by1 = board_rect.bounds
    cx0, cy0, cx1, cy1 = cutout.bounds

    if bx0 == 0.0:
        far_edge = bx1
        if cx1 > far_edge - min_overhang:
            dx = (far_edge - min_overhang) - cx1
            cutout = shapely.affinity.translate(cutout, xoff=dx)
    else:
        far_edge = bx0
        if cx0 < far_edge + min_overhang:
            dx = (far_edge + min_overhang) - cx0
            cutout = shapely.affinity.translate(cutout, xoff=dx)

    return safe_geom(cutout)


def cut_xy_slots(pg_xy, y_levels, x_open, x_stop,
                 rYmin, rYmax, slotH, edgeSafety, openEps):
    if pg_xy is None or pg_xy.is_empty:
        return pg_xy

    rects = []
    for yC0 in y_levels:
        yC = float(np.clip(
            yC0,
            rYmin + edgeSafety + 0.5 * slotH,
            rYmax - edgeSafety - 0.5 * slotH
        ))
        y1, y2 = yC - 0.5 * slotH, yC + 0.5 * slotH

        xInts = line_poly_intersect_x(pg_xy, yC, (min(x_open, x_stop), max(x_open, x_stop)))
        if len(xInts) < 2:
            continue

        for s in range(0, len(xInts) - 1, 2):
            xL, xR = xInts[s], xInts[s + 1]

            x_overlap_L = xL + edgeSafety
            x_overlap_R = xR - edgeSafety
            overlapW = x_overlap_R - x_overlap_L

            x_mid = 0.5 * (x_overlap_L + x_overlap_R)

            if overlapW <= 0:
                continue

            if x_open < x_stop:
                xs0 = x_open - openEps
                xs1 = x_mid
            else:
                xs1 = x_open + openEps
                xs0 = x_mid

            if xs1 > xs0:
                rects.append(box(xs0, y1, xs1, y2))

    if not rects:
        return pg_xy

    return safe_geom(pg_xy.difference(unary_union(rects)))


def cut_xz_slots(pg_xz, z_levels, x_open, x_stop,
                 rZmin, rZmax, slotH, edgeSafety, openEps):
    if pg_xz is None or pg_xz.is_empty:
        return pg_xz

    rects = []
    for zC0 in z_levels:
        zC = float(np.clip(
            zC0,
            rZmin + edgeSafety + 0.5 * slotH,
            rZmax - edgeSafety - 0.5 * slotH
        ))
        z1, z2 = zC - 0.5 * slotH, zC + 0.5 * slotH

        xInts = line_poly_intersect_x(
            pg_xz, zC,
            (min(x_open, x_stop), max(x_open, x_stop))
        )
        if len(xInts) < 2:
            continue

        for s in range(0, len(xInts) - 1, 2):
            xL, xR = xInts[s], xInts[s + 1]
            x_overlap_L = xL + edgeSafety
            x_overlap_R = xR - edgeSafety
            x_mid = 0.5 * (x_overlap_L + x_overlap_R)
            overlapW = x_overlap_R - x_overlap_L

            if overlapW <= 0:
                continue

            if x_open < x_stop:
                xs0 = x_open - openEps
                xs1 = x_mid
            else:
                xs1 = x_open + openEps
                xs0 = x_mid

            if xs1 > xs0:
                rects.append(box(xs0, z1, xs1, z2))

    if not rects:
        return pg_xz

    return safe_geom(pg_xz.difference(unary_union(rects)))


def mirror_geom_x(g):
    if g is None or g.is_empty:
        return g

    def mirror_poly(p: Polygon):
        ext = np.asarray(p.exterior.coords)
        ext[:, 0] *= -1.0
        holes = []
        for ring in p.interiors:
            rr = np.asarray(ring.coords)
            rr[:, 0] *= -1.0
            holes.append(rr)
        return Polygon(ext, holes)

    if g.geom_type == "Polygon":
        return mirror_poly(g)
    if g.geom_type == "MultiPolygon":
        return MultiPolygon([mirror_poly(p) for p in g.geoms])
    if g.geom_type == "GeometryCollection":
        polys = [mirror_poly(p) for p in explode_polys(g)]
        return safe_geom(unary_union(polys))
    return g


# =========================
# Plotting helpers
# =========================

def set_axes_equal(ax, verts):
    mins, maxs = verts.min(0), verts.max(0)
    center = (mins + maxs) / 2

    padding = 1.3
    span = (maxs - mins).max() / 2 * padding

    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)


def plot_geom_outline_3d(ax, geom, fixed_value, mode: str, color: str, lw=1.8):
    if geom is None or geom.is_empty:
        return
    for p in explode_polys(geom):
        x, y = p.exterior.xy
        x = np.asarray(x)
        y = np.asarray(y)
        if mode == "xy":
            ax.plot(x, y, np.full_like(x, fixed_value + CONTOUR_EPS), color, lw=lw)
        elif mode == "xz":
            ax.plot(x, np.full_like(x, fixed_value + CONTOUR_EPS), y, color, lw=lw)


def plot_2d_layout(title, geoms, labels, axis_name2="Y"):
    LABEL_PAD = 12.0
    label_y = max(g.bounds[3] for g in geoms if g and not g.is_empty) + LABEL_PAD

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("X")
    ax.set_ylabel(axis_name2)

    offset = 5.0
    gap = 10.0

    for g, lab in zip(geoms, labels):
        if g is None or g.is_empty:
            continue

        bx0, by0, bx1, by1 = g.bounds
        w = bx1 - bx0

        for p in explode_polys(g):
            x, y = p.exterior.xy
            ax.plot(np.asarray(x) + (offset - bx0), y, lw=1.2)

        x_center = offset + w / 2

        ax.text(
            x_center,
            1.02,
            lab,
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontweight="bold",
            fontsize=8,
        )

        offset += w + gap

    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    return fig, ax


def compute_worldgrid_from_stl(stl_path, n_xy=None, n_xz=None):
    is_symmetric = SYMMETRY in ("axis", "plane")

    if n_xy is None:
        n_xy = DEFAULT_N_XY
    if n_xz is None:
        n_xz = DEFAULT_N_XZ

    mesh = trimesh.load_mesh(stl_path, process=False)
    mesh = center_like_matlab(mesh)

    V = mesh.vertices
    print("spans:", V.max(axis=0) - V.min(axis=0))

    bounds = {
        "L": float(V[:, 0].max() - V[:, 0].min()),
        "W": float(V[:, 1].max() - V[:, 1].min()),
        "H": float(V[:, 2].max() - V[:, 2].min()),
    }

    xRange = (float(V[:, 0].min()), float(V[:, 0].max()))
    yRange = (float(V[:, 1].min()), float(V[:, 1].max()))
    zRange = (float(V[:, 2].min()), float(V[:, 2].max()))

    marginMin = 5.0
    bottomExtraEff = max(margin, marginMin)

    zBase = max(zRange[0] + 0.5 * materialT, zRange[0] - 0.25 * margin)
    zLevels = np.linspace(zRange[0], zRange[1], n_xy)

    baseY = yRange[0] - bottomExtraEff
    yTop  = yRange[1] + margin
    yLevels = np.linspace(yRange[0], yRange[1], n_xz)

    boardXMin = 0.0

    scanXMin = float(xRange[0] - 2 * margin)
    scanXMax = float(xRange[1] + 2 * margin)

    clipYMin = float(yRange[0] - 2 * margin)
    clipYMax = float(yRange[1] + 2 * margin)
    clipZMin = float(zRange[0] - 2 * margin)
    clipZMax = float(zRange[1] + 2 * margin)

    xy_right = []
    xy_left  = []

    for z in zLevels:
        xy_right.append(
            outer_silhouette_2d(
                mesh,
                origin=[0, 0, float(z)],
                normal=[0, 0, 1],
                proj_cols=(0, 1),
                x_min=scanXMin,
                x_max=scanXMax,
                a2_min=clipYMin,
                a2_max=clipYMax,
                half="right",
                snap=SNAP,
                dust_area=DUST_AREA,
                clearance=clearance,
                simplify_tolerance=SIMPLIFY_TOLERANCE,
                use_morph_smooth=USE_MORPH_SMOOTH,
                morph_expand=MORPH_EXPAND,
                morph_shrink=MORPH_SHRINK,
            )
        )

        xy_left.append(
            outer_silhouette_2d(
                mesh,
                origin=[0, 0, float(z)],
                normal=[0, 0, 1],
                proj_cols=(0, 1),
                x_min=scanXMin,
                x_max=scanXMax,
                a2_min=clipYMin,
                a2_max=clipYMax,
                half="left",
                snap=SNAP,
                dust_area=DUST_AREA,
                clearance=clearance,
                simplify_tolerance=SIMPLIFY_TOLERANCE,
                use_morph_smooth=USE_MORPH_SMOOTH,
                morph_expand=MORPH_EXPAND,
                morph_shrink=MORPH_SHRINK,
            )
        )

    xz_right = []
    xz_left  = []

    for y in yLevels:
        xz_right.append(
            outer_silhouette_2d(
                mesh,
                origin=[0, float(y), 0],
                normal=[0, 1, 0],
                proj_cols=(0, 2),
                x_min=scanXMin,
                x_max=scanXMax,
                a2_min=clipZMin,
                a2_max=clipZMax,
                half="right",
                snap=SNAP,
                dust_area=DUST_AREA,
                clearance=clearance,
                simplify_tolerance=SIMPLIFY_TOLERANCE,
                use_morph_smooth=USE_MORPH_SMOOTH,
                morph_expand=MORPH_EXPAND,
                morph_shrink=MORPH_SHRINK,
            )
        )

        xz_left.append(
            outer_silhouette_2d(
                mesh,
                origin=[0, float(y), 0],
                normal=[0, 1, 0],
                proj_cols=(0, 2),
                x_min=scanXMin,
                x_max=scanXMax,
                a2_min=clipZMin,
                a2_max=clipZMax,
                half="left",
                snap=SNAP,
                dust_area=DUST_AREA,
                clearance=clearance,
                simplify_tolerance=SIMPLIFY_TOLERANCE,
                use_morph_smooth=USE_MORPH_SMOOTH,
                morph_expand=MORPH_EXPAND,
                morph_shrink=MORPH_SHRINK,
            )
        )

    def max_x_of(geoms):
        xs = []
        for g in geoms:
            if g and not g.is_empty:
                xs.append(g.bounds[2])
        return max(xs) if xs else 0.0

    xy_xmax = max(
        max_x_of(xy_right),
        max_x_of(xy_left),
    )

    xz_xmax = max(
        max_x_of(xz_right),
        max_x_of(xz_left),
    )

    boardW = max(
        xy_xmax + MIN_SLAT_OVERHANG,
        xz_xmax + MIN_SLAT_OVERHANG,
    ) + sidePadX

    baseZ = zRange[0] - bottomExtraEff
    zTop  = zRange[1] + margin

    rXmin = boardXMin
    rXmax = boardXMin + boardW

    rYmin = baseY - margin
    rYmax = yTop + margin

    rZmin = baseZ - margin
    rZmax = zTop + margin

    rectXY_right = box(0.0, rYmin, boardW, rYmax)
    rectXZ_right = box(0.0, rZmin, boardW, rZmax)

    rectXY_left  = box(-boardW, rYmin, 0.0, rYmax)
    rectXZ_left  = box(-boardW, rZmin, 0.0, rZmax)

    # -------------------------
    # Build world XY slats
    # -------------------------

    worldXY_right = []
    worldXY_left  = []

    for cutXY in xy_right:
        if cutXY:
            cutXY = enforce_min_overhang_against_board(
                cutXY, rectXY_right, MIN_SLAT_OVERHANG
            )
            # Smooth / clean ONLY the object contour, not the final slat
            cutXY = finalize_slat(cutXY)

        slat = (
            make_open_pocket(rectXY_right, cutXY, 0.0, rYmin, rYmax, fixGapMin)
            if cutXY else rectXY_right
        )
        slat = keep_only_touching_frame(slat, rectXY_right.bounds)
        slat = remove_small_parts(slat, min_area=CLEAN_MIN_AREA)

        worldXY_right.append(slat)

    for cutXY in xy_left:
        if cutXY:
            cutXY = enforce_min_overhang_against_board(
                cutXY, rectXY_left, MIN_SLAT_OVERHANG
            )
            # Smooth / clean ONLY the object contour, not the final slat
            cutXY = finalize_slat(cutXY)

        slat = (
            make_open_pocket(rectXY_left, cutXY, -boardW, rYmin, rYmax, fixGapMin)
            if cutXY else rectXY_left
        )
        slat = keep_only_touching_frame(slat, rectXY_left.bounds)
        slat = remove_small_parts(slat, min_area=CLEAN_MIN_AREA)

        worldXY_left.append(slat)

    # -------------------------
    # Build world XZ slats
    # -------------------------

    worldXZ_right = []
    worldXZ_left  = []

    for cutXZ in xz_right:
        if cutXZ:
            cutXZ = enforce_min_overhang_against_board(
                cutXZ, rectXZ_right, MIN_SLAT_OVERHANG
            )
            # Smooth / clean ONLY the object contour, not the final slat
            cutXZ = finalize_slat(cutXZ)

        slat = (
            make_open_pocket(rectXZ_right, cutXZ, 0.0, rZmin, rZmax, fixGapMin)
            if cutXZ else rectXZ_right
        )
        slat = keep_only_touching_frame(slat, rectXZ_right.bounds)
        slat = remove_small_parts(slat, min_area=CLEAN_MIN_AREA)

        worldXZ_right.append(slat)

    for cutXZ in xz_left:
        if cutXZ:
            cutXZ = enforce_min_overhang_against_board(
                cutXZ, rectXZ_left, MIN_SLAT_OVERHANG
            )
            # Smooth / clean ONLY the object contour, not the final slat
            cutXZ = finalize_slat(cutXZ)

        slat = (
            make_open_pocket(rectXZ_left, cutXZ, -boardW, rZmin, rZmax, fixGapMin)
            if cutXZ else rectXZ_left
        )
        slat = keep_only_touching_frame(slat, rectXZ_left.bounds)
        slat = remove_small_parts(slat, min_area=CLEAN_MIN_AREA)

        worldXZ_left.append(slat)
    # -------------------------------------------------
    # Slots
    # -------------------------------------------------

    edgeSafety = max(slotSafety, 1.0)
    slotH = materialT + kerfFit
    openEps = 0.5

    worldXY_right = [
        remove_small_parts(
            keep_only_touching_frame(
                cut_xy_slots(
                    pg,
                    yLevels,
                    x_open=0.0,
                    x_stop=rXmax,
                    rYmin=rYmin,
                    rYmax=rYmax,
                    slotH=slotH,
                    edgeSafety=edgeSafety,
                    openEps=openEps,
                ),
                rectXY_right.bounds,
            ),
            min_area=CLEAN_MIN_AREA,
        )
        for pg in worldXY_right
    ]

    worldXY_left = [
        remove_small_parts(
            keep_only_touching_frame(
                cut_xy_slots(
                    pg,
                    yLevels,
                    x_open=0.0,
                    x_stop=-boardW,
                    rYmin=rYmin,
                    rYmax=rYmax,
                    slotH=slotH,
                    edgeSafety=edgeSafety,
                    openEps=openEps,
                ),
                rectXY_left.bounds,
            ),
            min_area=CLEAN_MIN_AREA,
        )
        for pg in worldXY_left
    ]

    worldXZ_right = [
        remove_small_parts(
            keep_only_touching_frame(
                cut_xz_slots(
                    pg,
                    zLevels,
                    x_open=0.0,
                    x_stop=rXmax,
                    rZmin=rZmin,
                    rZmax=rZmax,
                    slotH=slotH,
                    edgeSafety=edgeSafety,
                    openEps=openEps,
                ),
                rectXZ_right.bounds,
            ),
            min_area=CLEAN_MIN_AREA,
        )
        for pg in worldXZ_right
    ]

    worldXZ_left = [
        remove_small_parts(
            keep_only_touching_frame(
                cut_xz_slots(
                    pg,
                    zLevels,
                    x_open=0.0,
                    x_stop=-boardW,
                    rZmin=rZmin,
                    rZmax=rZmax,
                    slotH=slotH,
                    edgeSafety=edgeSafety,
                    openEps=openEps,
                ),
                rectXZ_left.bounds,
            ),
            min_area=CLEAN_MIN_AREA,
        )
        for pg in worldXZ_left
    ]

    if POST_SLOT_CLEANUP:
        worldXY_right = [finalize_slat(pg) for pg in worldXY_right]
        worldXY_left  = [finalize_slat(pg) for pg in worldXY_left]
        worldXZ_right = [finalize_slat(pg) for pg in worldXZ_right]
        worldXZ_left  = [finalize_slat(pg) for pg in worldXZ_left]

    print(
        "worldXY_right:", len(worldXY_right),
        "worldXY_left:",  len(worldXY_left),
        "worldXZ_right:", len(worldXZ_right),
        "worldXZ_left:",  len(worldXZ_left),
    )

    if USE_BLADE_SEGMENTS:
        worldXY_right = segmentize_list(worldXY_right, BLADE_TOL)
        worldXY_left  = segmentize_list(worldXY_left,  BLADE_TOL)
        worldXZ_right = segmentize_list(worldXZ_right, BLADE_TOL)
        worldXZ_left  = segmentize_list(worldXZ_left,  BLADE_TOL)

    xy_right_records = build_slat_records(
        worldXY_right, family="XY", side="right", plane_axis="Z", plane_values=zLevels
    )
    xy_left_records = build_slat_records(
        worldXY_left, family="XY", side="left", plane_axis="Z", plane_values=zLevels
    )
    xz_right_records = build_slat_records(
        worldXZ_right, family="XZ", side="right", plane_axis="Y", plane_values=yLevels
    )
    xz_left_records = build_slat_records(
        worldXZ_left, family="XZ", side="left", plane_axis="Y", plane_values=yLevels
    )

    return {
        "mesh": mesh,
        "bounds": bounds,
        "zLevels": zLevels,
        "yLevels": yLevels,
        "worldXY_right": worldXY_right,
        "worldXY_left":  worldXY_left,
        "worldXZ_right": worldXZ_right,
        "worldXZ_left":  worldXZ_left,
        "xy_right_records": xy_right_records,
        "xy_left_records":  xy_left_records,
        "xz_right_records": xz_right_records,
        "xz_left_records":  xz_left_records,
    }


# =========================
# Main
# =========================

def main():
    data = compute_worldgrid_from_stl(INPUT_STL)

    mesh    = data["mesh"]
    bounds  = data["bounds"]
    zLevels = data["zLevels"]
    yLevels = data["yLevels"]
    worldXY_right = data["worldXY_right"]
    worldXY_left  = data["worldXY_left"]
    worldXZ_right = data["worldXZ_right"]
    worldXZ_left  = data["worldXZ_left"]

    print(f"STL: {INPUT_STL}")
    print("\n=== OBJECT DIMENSIONS (mm) ===")
    print(f"X (width)  : {bounds['L']:.2f}")
    print(f"Y (depth)  : {bounds['W']:.2f}")
    print(f"Z (height) : {bounds['H']:.2f}")
    print("================================\n")
    print(
        f"Slats: "
        f"XY_right={len(worldXY_right)}, "
        f"XY_left={len(worldXY_left)}, "
        f"XZ_right={len(worldXZ_right)}, "
        f"XZ_left={len(worldXZ_left)}"
    )

    # ---------------- 3D PREVIEW ----------------
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.set_title("WORLD-GRID — 3D Preview (mesh + slats outlines)")

    mesh_poly1 = Poly3DCollection(mesh.vertices[mesh.faces], alpha=MESH_ALPHA)
    mesh_poly1.set_facecolor([0.3, 0.5, 1.0])
    ax.add_collection3d(mesh_poly1)

    for z, geom in zip(zLevels, worldXY_right):
        plot_geom_outline_3d(ax, geom, z, "xy", "r")

    for z, geom in zip(zLevels, worldXY_left):
        plot_geom_outline_3d(ax, geom, z, "xy", "r")

    for y, geom in zip(yLevels, worldXZ_right):
        plot_geom_outline_3d(ax, geom, y, "xz", "b")

    for y, geom in zip(yLevels, worldXZ_left):
        plot_geom_outline_3d(ax, geom, y, "xz", "b")

    verts_accum = [mesh.vertices]

    for z, geom in zip(zLevels, worldXY_right + worldXY_left):
        if geom and not geom.is_empty:
            for p in explode_polys(geom):
                xy = np.asarray(p.exterior.coords)
                xyz = np.column_stack([
                    xy[:, 0],
                    xy[:, 1],
                    np.full(len(xy), z),
                ])
                verts_accum.append(xyz)

    for y, geom in zip(yLevels, worldXZ_right + worldXZ_left):
        if geom and not geom.is_empty:
            for p in explode_polys(geom):
                xz = np.asarray(p.exterior.coords)
                xyz = np.column_stack([
                    xz[:, 0],
                    np.full(len(xz), y),
                    xz[:, 1],
                ])
                verts_accum.append(xyz)

    all_verts = np.vstack(verts_accum)
    set_axes_equal(ax, all_verts)

    ax.view_init(25, 35)
    plt.tight_layout()

    # ---------------- ASSEMBLY VIEW ----------------
    if SHOW_ASSEMBLY_VIZ:
        figA = plt.figure(figsize=(12, 8))
        axA = figA.add_subplot(111, projection="3d")
        axA.set_title("ASSEMBLY — Object + One-Side Corrugated Slats")

        mesh_poly2 = Poly3DCollection(mesh.vertices[mesh.faces], alpha=0.25)
        mesh_poly2.set_facecolor([0.3, 0.5, 1.0])
        axA.add_collection3d(mesh_poly2)

        for z, geom in zip(zLevels, worldXY_right):
            if geom is not None and not geom.is_empty and geom.bounds[2] >= 0:
                plot_corrugated_board(
                    axA,
                    geom,
                    fixed_value=float(z),
                    mode="xy",
                    thickness=materialT,
                )

        for z, geom in zip(zLevels, worldXY_left):
            if geom is not None and not geom.is_empty and geom.bounds[2] >= 0:
                plot_corrugated_board(
                    axA,
                    geom,
                    fixed_value=float(z),
                    mode="xy",
                    thickness=materialT,
                )

        for y, geom in zip(yLevels, worldXZ_right):
            if geom is not None and not geom.is_empty and geom.bounds[2] >= 0:
                plot_corrugated_board(
                    axA,
                    geom,
                    fixed_value=float(y),
                    mode="xz",
                    thickness=materialT,
                )

        for y, geom in zip(yLevels, worldXZ_left):
            if geom is not None and not geom.is_empty and geom.bounds[2] >= 0:
                plot_corrugated_board(
                    axA,
                    geom,
                    fixed_value=float(y),
                    mode="xz",
                    thickness=materialT,
                )

        set_axes_equal(axA, mesh.vertices)
        axA.view_init(25, 35)
        plt.tight_layout()

    # ---------------- 2D LAYOUTS ----------------

    fig_xy_r, ax_xy_r = plot_2d_layout(
        "WORLD-GRID — XY Slats — Right",
        worldXY_right,
        [f"Z={z:.1f}" for z in zLevels],
        axis_name2="Y",
    )
    ax_xy_r.set_title("WORLD-GRID — XY Slats — Right", pad=28)

    fig_xy_l, ax_xy_l = plot_2d_layout(
        "WORLD-GRID — XY Slats — Left",
        worldXY_left,
        [f"Z={z:.1f}" for z in zLevels],
        axis_name2="Y",
    )
    ax_xy_l.set_title("WORLD-GRID — XY Slats — Left", pad=28)

    fig_xz_r, ax_xz_r = plot_2d_layout(
        "WORLD-GRID — XZ Slats — Right",
        worldXZ_right,
        [f"Y={y:.1f}" for y in yLevels],
        axis_name2="Z",
    )
    ax_xz_r.set_title("WORLD-GRID — XZ Slats — Right", pad=28)

    fig_xz_l, ax_xz_l = plot_2d_layout(
        "WORLD-GRID — XZ Slats — Left",
        worldXZ_left,
        [f"Y={y:.1f}" for y in yLevels],
        axis_name2="Z",
    )
    ax_xz_l.set_title("WORLD-GRID — XZ Slats — Left", pad=28)

    plt.show()


if __name__ == "__main__":
    main()