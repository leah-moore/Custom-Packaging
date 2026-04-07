# apps/grid_slats.py
#
# Python port of MATLAB "Vase Cross Sections → Half-Grid (XY + XZ), world-consistent & equal boards"
#
# GOAL FIX: ignore the *inside* of the object (inner wall) completely.
# We therefore compute an OUTER-ENVELOPE silhouette per slice, instead of using filled polygons
# (which preserve inner-wall/topology and can create double outlines on shelled meshes).

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
# ================== MATPLOTLIB BACKEND ==================
# Choose based on your OS:
#   "TkAgg"    = Raspberry Pi with display (or any Linux)
#   "MacOSX"   = macOS
#   "Agg"      = Headless (no display, saves to file)
# =========================================================
matplotlib.use("TkAgg")   # ← Change this for your OS

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
INPUT_STL = Path("data/stl/input/Asymmetrical/mouse.stl")  # change if needed

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

DEFAULT_N_XY = 4
DEFAULT_N_XZ = 4

margin      = 5.0      # board margin (mm)
clearance   = 0.0      # expand/shrink silhouette cutout (mm)
previewT    = 8.0      # visual thickness for 3D preview (mm)
fixGapMin   = 2        # bridge band width to FORCE open pocket to left edge (mm)
slotSafety  = max(kerfFit, 0.6)
showPlanes  = False

SHOW_ASSEMBLY_VIZ = False

bottomExtra = margin
sidePadX    = margin

MIN_SLAT_OVERHANG = 5.0  # mm — minimum material past silhouette

MIN_CARDBOARD_WIDTH = 1.0  # mm; raise if spikes remain, lower if you lose detail

# silhouette robustness
SNAP        = 1e-4     # snap rounding (finer rounding for smoother curves)
DUST_AREA   = 5.0      # drop tiny fragments

# NOTE: FORCE_SOLID/RM_HOLES are kept for compatibility with your toggles,
# but envelope silhouettes do not require them and they are not used.
FORCE_SOLID = False
RM_HOLES    = False

# envelope silhouette sampling density (higher = smoother, slower)
ENVELOPE_SAMPLES = 1200

# plotting
MESH_ALPHA  = 0.18
PLANE_ALPHA = 0.06
PLANE_RES   = 18
CONTOUR_EPS = 0.05

CUT_BOTH_SIDES = True   # or False

# ================================================
# SMOOTHING & FEATURE SIZE CONTROLS
# ================================================
# Blade detail tolerance: removes micro-features smaller than this
MIN_FEATURE_SIZE = 1.5         # mm — collapse blade steps/notches smaller than this
#                                # Increase to remove tiny details (1.5-3.0 mm typical)
#                                # Decrease to keep fine geometry (0.5-1.0 mm)

# Simplify contour curves: removes vertices that don't deviate much from a line
SIMPLIFY_TOLERANCE = 0.5       # Douglas-Peucker tolerance (mm)
#                                # 0.1-0.3 = smooth curves, keeps detail
#                                # 0.5-0.75 = aggressive smoothing, removes micro-zigzags
#                                # 1.0+ = very simplified, blocky look

# Morphological smoothing: dilate→erode to round sharp corners
USE_MORPH_SMOOTH = True        # if True, apply dilate→erode smoothing
MORPH_EXPAND = 0.5             # expand amount (mm) — increase for rounder curves
MORPH_SHRINK = 0.5             # shrink amount (mm) — keep equal to MORPH_EXPAND
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
        # KEEP the same board opening edge as before
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

    This enforces minimum cardboard thickness
    between board edge and contour.
    """
    if min_depth_mm <= 0 or len(x) < 5:
        return x

    x = np.asarray(x, float)

    # outer envelope baseline (largest possible outer wall)
    left_max  = np.maximum.accumulate(x)
    right_max = np.maximum.accumulate(x[::-1])[::-1]
    baseline  = np.minimum(left_max, right_max)

    dent_depth = baseline - x

    # if dent is shallow → remove it
    x2 = x.copy()
    mask = dent_depth < min_depth_mm
    x2[mask] = baseline[mask]

    return x2


def filter_micro_features(geom, min_feature_mm):
    """
    Remove small notches and indentations from a geometry.
    
    For each vertex, if the inward dent depth is smaller than min_feature_mm,
    snap it back to the outer envelope.
    
    Args:
        geom: Shapely Polygon or MultiPolygon
        min_feature_mm: minimum inward feature depth (mm) to preserve
    
    Returns:
        Simplified geometry with micro-features removed
    """
    if geom is None or geom.is_empty or min_feature_mm <= 0:
        return geom
    
    if not hasattr(geom, 'exterior'):
        # MultiPolygon or other; process recursively
        if hasattr(geom, 'geoms'):
            polys = [filter_micro_features(g, min_feature_mm) for g in geom.geoms]
            polys = [p for p in polys if p is not None and not p.is_empty]
            if not polys:
                return None
            if len(polys) == 1:
                return polys[0]
            return MultiPolygon(polys)
        return geom
    
    try:
        # Buffer slightly inward then outward to collapse small notches
        # This is more robust than manual coordinate filtering
        buffer_amt = min_feature_mm / 1000.0
        buffered = geom.buffer(-buffer_amt, resolution=4)
        buffered = buffered.buffer(buffer_amt, resolution=4)
        
        result = safe_geom(buffered)
        return result if result is not None else geom
    except Exception:
        return geom


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

    # 🔑 ONLY mirror when the object is declared symmetric
    if SHOW_SLATS in ("all", "left") and SYMMETRY in ("axis", "plane"):
        plot_geom_outline_3d(
            ax,
            mirror_geom_x(geom),
            fixed_value,
            mode=mode,
            color=color,
            lw=lw_mirror,
        )


def smooth_envelope_points(xs, a2s, method="median", window=5):
    """
    Smooth envelope X values while preserving endpoints.
    
    xs: array of X coordinates along the envelope
    a2s: corresponding Y (or Z) coordinates
    method: 'median' or 'gaussian'
    window: kernel size (odd number)
    """
    if len(xs) < window:
        return xs
    
    xs = np.asarray(xs, dtype=float)
    
    if method == "median":
        from scipy.ndimage import median_filter
        smoothed = median_filter(xs, size=window, mode='nearest')
    elif method == "gaussian":
        from scipy.ndimage import gaussian_filter1d
        sigma = window / 3.0
        smoothed = gaussian_filter1d(xs, sigma=sigma, mode='nearest')
    else:
        return xs
    
    # Keep endpoints anchored
    smoothed[0] = xs[0]
    smoothed[-1] = xs[-1]
    
    return smoothed


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


def envelope_silhouette_polygon_from_lines(
    lines,
    x_min, x_max,
    a2_min, a2_max,
    half="right",
    nsamples=700,
    eps=1e-6,
    smooth_method=None,
    smooth_window=5
):
    """
    Build a SINGLE silhouette polygon that ignores all interior walls.

    Method: scanline extremum.
      - For each scanline at coordinate a2 (Y for XY slices, Z for XZ slices),
        intersect with section curves, get all X intersections.
      - Keep ONLY the outermost X (max for right-half, min for left-half).
      - Create a filled polygon between the board edge (x_min or x_max) and that envelope.

    This makes shelled meshes behave like solid blobs in silhouette space.
    
    smooth_method: None, 'median', or 'gaussian' - applies array-level smoothing to envelope
    smooth_window: kernel size for smoothing (odd numbers work best)
    """
    if not lines:
        return None

    L = safe_geom(unary_union(lines))
    if L is None:
        return None

    ys = np.linspace(a2_min, a2_max, nsamples)

    # store envelope points (x_outer, y)
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
        if not xs:
            continue
        xs = np.array(xs, dtype=float)
        xs.sort()

        if h == "right":
            env.append((xs[-1], y))
        elif h == "left":
            env.append((xs[0], y))
        else:  # both
            env.append((xs[0], xs[-1], y))

    if h == "right":
        if len(env) < 3:
            return None
        xs = np.array([p[0] for p in env])
        a2s = np.array([p[1] for p in env])

        # 🔑 OPTIONAL: smooth the envelope before bridge_short_dips
        if smooth_method is not None:
            xs = smooth_envelope_points(xs, a2s, method=smooth_method, window=smooth_window)

        xs = bridge_short_dips(a2s, xs, MIN_CARDBOARD_WIDTH)

        x_outer = list(zip(xs, a2s))
        y0 = x_outer[0][1]
        y1 = x_outer[-1][1]
        ring = [(x_min, y0)] + x_outer + [(x_min, y1)]
        pg = safe_geom(Polygon(ring))
        return pg

    if h == "left":
        if len(env) < 3:
            return None
        xs = np.array([p[0] for p in env])
        a2s = np.array([p[1] for p in env])

        # 🔑 OPTIONAL: smooth the envelope before bridge_short_dips
        if smooth_method is not None:
            xs = -smooth_envelope_points(-xs, a2s, method=smooth_method, window=smooth_window)

        xs = -bridge_short_dips(a2s, -xs, MIN_CARDBOARD_WIDTH)

        x_outer = list(zip(xs, a2s))
        y0 = x_outer[0][1]
        y1 = x_outer[-1][1]
        ring = [(x_max, y0)] + x_outer + [(x_max, y1)]
        pg = safe_geom(Polygon(ring))
        return pg

    if len(env) < 3:
        return None
    left = [(xmin, y) for (xmin, xmax, y) in env]
    right = [(xmax, y) for (xmin, xmax, y) in env]
    ring = right + left[::-1]
    pg = safe_geom(Polygon(ring))
    return pg


def outer_silhouette_2d(
    mesh: trimesh.Trimesh,
    origin, normal,
    proj_cols=(0, 1),
    x_min=-1e9, x_max=1e9,
    a2_min=-1e9, a2_max=1e9,
    half="right",
    snap=1e-3,
    dust_area=5.0,
    force_solid=False,  # kept for signature compatibility (unused)
    rm_holes=False,     # kept for signature compatibility (unused)
    clearance=0.0,
    simplify_tolerance=0.5,
    use_morph_smooth=False,
    morph_expand=0.3,
    morph_shrink=0.3,
    min_feature_size=0.0,
):
    """
    OUTER-ENVELOPE silhouette (ignores interior walls):
      section -> polylines -> 2D lines -> scanline envelope polygon -> clip -> clearance.
      
    Parameters:
      simplify_tolerance: Douglas-Peucker simplification tolerance (0.5–1.0 mm typical)
      use_morph_smooth: if True, apply dilate→erode smoothing
      morph_expand, morph_shrink: morphological smoothing amounts
      min_feature_size: collapse blade notches/steps smaller than this (mm)
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
        smooth_method=None,  # could be 'median' or 'gaussian' for scanline smoothing
        smooth_window=5,
    )
    if U is None or U.is_empty or U.area < dust_area:
        return None

    # 🔑 SMOOTH via simplify (Douglas-Peucker)
    U = safe_geom(U.simplify(tolerance=simplify_tolerance, preserve_topology=True))
    if U is None or U.is_empty:
        return None

    # 🔑 OPTIONAL: filter micro-features (collapse notches smaller than min_feature_size)
    if min_feature_size > 0:
        U = filter_micro_features(U, min_feature_size)
        if U is None or U.is_empty:
            return None

    # 🔑 OPTIONAL: morphological smoothing (dilate→erode)
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

    # Right board: [0, +boardW]
    if bx0 == 0.0:
        far_edge = bx1
        if cx1 > far_edge - min_overhang:
            dx = (far_edge - min_overhang) - cx1
            cutout = shapely.affinity.translate(cutout, xoff=dx)

    # Left board: [-boardW, 0]
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
                # right board: cut from X=0 → midpoint
                xs0 = x_open - openEps
                xs1 = x_mid
            else:
                # left board: cut from X=0 → midpoint
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
                # right board: cut from X=0 → midpoint
                xs0 = x_open - openEps
                xs1 = x_mid
            else:
                # left board: cut from X=0 → midpoint
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

    # -------------------------------------------------
    # 🔑 KEY FIX: separate scan space from board space
    # -------------------------------------------------

    boardXMin = 0.0

    scanXMin = float(xRange[0] - 2 * margin)
    scanXMax = float(xRange[1] + 2 * margin)

    clipYMin = float(yRange[0] - 2 * margin)
    clipYMax = float(yRange[1] + 2 * margin)
    clipZMin = float(zRange[0] - 2 * margin)
    clipZMax = float(zRange[1] + 2 * margin)

    # -------------------------------------------------
    # Silhouettes (FULL scan width, controlled half)
    # -------------------------------------------------

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
                min_feature_size=MIN_FEATURE_SIZE,
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
                min_feature_size=MIN_FEATURE_SIZE,
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
                min_feature_size=MIN_FEATURE_SIZE,
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
                min_feature_size=MIN_FEATURE_SIZE,
            )
        )

    # -------------------------------------------------
    # Board extents (RIGHT-HALF LOGIC PRESERVED)
    # -------------------------------------------------

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

    # Right side boards (X >= 0)
    rectXY_right = box(0.0, rYmin, boardW, rYmax)
    rectXZ_right = box(0.0, rZmin, boardW, rZmax)

    # Left side boards (X <= 0)
    rectXY_left  = box(-boardW, rYmin, 0.0, rYmax)
    rectXZ_left  = box(-boardW, rZmin, 0.0, rZmax)

    # -------------------------------------------------
    # Build world slats (OPEN POCKET AT X = 0, TRUE SANDWICH)
    # -------------------------------------------------

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
            cutXY = enforce_min_overhang_against_board(cutXY, rectXY_right, MIN_SLAT_OVERHANG)

        worldXY_right.append(
            make_open_pocket(rectXY_right, cutXY, 0.0, rYmin, rYmax, fixGapMin)
            if cutXY else rectXY_right
        )

    for cutXY in xy_left:
        if cutXY:
            cutXY = enforce_min_overhang_against_board(cutXY, rectXY_left, MIN_SLAT_OVERHANG)

        worldXY_left.append(
            make_open_pocket(rectXY_left, cutXY, -boardW, rYmin, rYmax, fixGapMin)
            if cutXY else rectXY_left
        )

    # -------------------------
    # Build world XZ slats
    # -------------------------

    worldXZ_right = []
    worldXZ_left  = []

    for cutXZ in xz_right:
        if cutXZ:
            cutXZ = enforce_min_overhang_against_board(cutXZ, rectXZ_right, MIN_SLAT_OVERHANG)

        worldXZ_right.append(
            make_open_pocket(rectXZ_right, cutXZ, 0.0, rZmin, rZmax, fixGapMin)
            if cutXZ else rectXZ_right
        )

    for cutXZ in xz_left:
        if cutXZ:
            cutXZ = enforce_min_overhang_against_board(cutXZ, rectXZ_left, MIN_SLAT_OVERHANG)

        worldXZ_left.append(
            make_open_pocket(rectXZ_left, cutXZ, -boardW, rZmin, rZmax, fixGapMin)
            if cutXZ else rectXZ_left
        )

    if is_symmetric and not CUT_BOTH_SIDES:
        worldXY_left = []
        worldXZ_left = []

    # -------------------------------------------------
    # Slots
    # -------------------------------------------------

    edgeSafety = max(slotSafety, 1.0)
    slotH = materialT + kerfFit
    openEps = 0.5

    worldXY_right = [
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
        )
        for pg in worldXY_right
    ]

    worldXY_left = [
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
        )
        for pg in worldXY_left
    ]

    worldXZ_right = [
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
        )
        for pg in worldXZ_right
    ]

    worldXZ_left = [
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
        )
        for pg in worldXZ_left
    ]

    print(
        "worldXY_right:", len(worldXY_right),
        "worldXY_left:",  len(worldXY_left),
        "worldXZ_right:", len(worldXZ_right),
        "worldXZ_left:",  len(worldXZ_left),
    )

    # -------------------------------------------------
    # Convert curves → straight blade segments
    # -------------------------------------------------

    if USE_BLADE_SEGMENTS:
        worldXY_right = segmentize_list(worldXY_right, BLADE_TOL)
        worldXY_left  = segmentize_list(worldXY_left,  BLADE_TOL)
        worldXZ_right = segmentize_list(worldXZ_right, BLADE_TOL)
        worldXZ_left  = segmentize_list(worldXZ_left,  BLADE_TOL)

    # -------------------------------------------------
    # Build ID-carrying slat records
    # -------------------------------------------------

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
    print(f"Bounds (mm): L={bounds['L']:.2f} W={bounds['W']:.2f} H={bounds['H']:.2f}")
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