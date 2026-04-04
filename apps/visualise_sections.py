# apps/cradle_worldgrid.py
#
# Python port of your MATLAB "Vase Cross Sections → Half-Grid (XY + XZ), world-consistent & equal boards"
#
# FIX for the “middle two still show inner+outer outlines”:
# - In Python/Trimesh sections, the inner wall can come back as a SEPARATE closed loop (a separate Polygon),
#   not as a HOLE. rmholes only removes holes; it does NOT delete a separate inner polygon.
# - So we explicitly DROP “contained” polygons and keep ONLY the outer shells (region-aware),
#   then (optionally) remove holes.
#
# Result:
# - Each slice becomes a “solid object silhouette” (outermost boundary only)
# - Pocket is OPEN to the LEFT via a bridge band before subtracting
# - Slots: XY uses Y-levels (cut from RIGHT inward), XZ uses Z-levels (cut from LEFT inward)
#
# Run:
#   conda activate custom-packaging
#   python apps/cradle_worldgrid.py

from __future__ import annotations

from pathlib import Path
import warnings
import numpy as np
import trimesh

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box, LineString
from shapely.ops import unary_union
from shapely.errors import TopologicalError

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------- USER SETTINGS ----------------
INPUT_STL = Path("data/stl/prepared/vase_capped.stl")  # change to your sealed STL if desired

materialT   = 3.0      # sheet thickness (mm)
kerfFit     = 0.15     # extra width to fit (kerf + wiggle) (mm)

nXY         = 6        # number of horizontal XY slats (red)
nXZ         = 6        # number of vertical  XZ slats (blue)

margin      = 10.0     # board margin (mm)
clearance   = 0.0      # expand/shrink silhouette cutout (mm)
previewT    = 8.0      # visual thickness for 3D preview (mm)
fixGapMin   = 0.8      # bridge band width to FORCE open pocket to left edge (mm)
slotSafety  = max(kerfFit, 0.6)
showPlanes  = False

extraLayers = 1
bottomExtra = margin
sidePadX    = margin

USE_HALF_X  = True
X_MIN       = 0.0

# silhouette robustness
SNAP        = 1e-3     # snap rounding
DUST_AREA   = 5.0      # drop tiny fragments
FORCE_SOLID = True     # IMPORTANT: drop contained polygons (inner wall loops)
RM_HOLES    = True     # remove holes after solidify (manufacturing realism)

# plotting
MESH_ALPHA  = 0.18
PLANE_ALPHA = 0.06
PLANE_RES   = 18
CONTOUR_EPS = 0.05
# ------------------------------------------------


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


def snap_and_clean_ring(Q: np.ndarray, snap: float) -> np.ndarray | None:
    Q = np.asarray(Q, dtype=float)
    if Q.shape[0] < 3:
        return None

    Q = np.round(Q / snap) * snap

    # remove consecutive duplicates / tiny edges
    if Q.shape[0] > 1:
        d = np.linalg.norm(np.diff(Q, axis=0), axis=1)
        keep = np.ones(Q.shape[0], dtype=bool)
        keep[1:] = d > snap
        Q = Q[keep]
    if Q.shape[0] < 3:
        return None

    # close ring
    if np.linalg.norm(Q[0] - Q[-1]) > snap:
        Q = np.vstack([Q, Q[0]])

    # remove tiny edges again
    if Q.shape[0] > 4:
        d = np.linalg.norm(np.diff(Q, axis=0), axis=1)
        keep = np.ones(Q.shape[0], dtype=bool)
        keep[1:] = d > snap
        Q = Q[keep]
        if np.linalg.norm(Q[0] - Q[-1]) > snap:
            Q = np.vstack([Q, Q[0]])

    return Q if Q.shape[0] >= 4 else None


def center_like_matlab(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    V = mesh.vertices.copy()
    V[:, 0] -= 0.5 * (V[:, 0].min() + V[:, 0].max())
    V[:, 1] -= V[:, 1].mean()
    m = mesh.copy()
    m.vertices = V
    return m


def section_polylines(mesh: trimesh.Trimesh, origin, normal):
    sec = mesh.section(plane_origin=np.asarray(origin), plane_normal=np.asarray(normal))
    return [] if sec is None or sec.discrete is None else sec.discrete


def rmholes_like(g):
    parts = explode_polys(g)
    if not parts:
        return None
    exteriors = [Polygon(p.exterior) for p in parts]
    return safe_geom(unary_union(exteriors))


def keep_only_outer_shells(g):
    """
    CRITICAL FIX: If inner wall comes as a SEPARATE polygon, rmholes won't remove it.
    This drops polygons that are fully contained inside another polygon.
    Keeps all *outermost* shells (disjoint outers) => “treat object as solid”.
    """
    parts = explode_polys(g)
    if len(parts) <= 1:
        return g

    # sort big -> small, so we can test containment against already-kept outers
    parts_sorted = sorted(parts, key=lambda p: p.area, reverse=True)
    outers = []

    for p in parts_sorted:
        rp = p.representative_point()
        contained = False
        for o in outers:
            # if representative point lies inside an already-kept outer, this polygon is interior
            if o.contains(rp):
                contained = True
                break
        if not contained:
            outers.append(p)

    return safe_geom(unary_union(outers))


def outer_silhouette_2d_half(
    mesh: trimesh.Trimesh,
    origin, normal,
    proj_cols=(0, 1),
    x_min=-1e9, x_max=1e9,
    a2_min=-1e9, a2_max=1e9,
    half="right",
    snap=1e-3,
    dust_area=5.0,
    force_solid=True,
    rm_holes=True,
    clearance=0.0,
):
    polylines = section_polylines(mesh, origin, normal)
    if not polylines:
        return None

    polys = []
    for P in polylines:
        if P is None or len(P) < 3:
            continue
        Q = P[:, list(proj_cols)]
        Q = snap_and_clean_ring(Q, snap=snap)
        if Q is None:
            continue
        pg = safe_geom(Polygon(Q))
        if pg is None:
            continue
        polys.extend(explode_polys(pg))

    if not polys:
        return None

    U = safe_geom(unary_union(polys))
    if U is None:
        return None

    # drop dust fragments but keep all remaining
    parts = [p for p in explode_polys(U) if p.area > dust_area]
    if not parts:
        return None
    U = safe_geom(unary_union(parts))
    if U is None:
        return None

    # clip to half-space about X=0
    midX = 0.0
    if half.lower() == "left":
        mask = Polygon([(x_min, a2_min), (midX, a2_min), (midX, a2_max), (x_min, a2_max)])
    elif half.lower() == "right":
        mask = Polygon([(midX, a2_min), (x_max, a2_min), (x_max, a2_max), (midX, a2_max)])
    else:
        mask = Polygon([(x_min, a2_min), (x_max, a2_min), (x_max, a2_max), (x_min, a2_max)])

    I = safe_geom(U.intersection(mask))
    if I is None:
        return None

    # clearance
    if abs(clearance) > 1e-9:
        I = safe_geom(I.buffer(float(clearance)))
        I = safe_geom(I.buffer(0)) if I is not None else None
        if I is None:
            return None

    # IMPORTANT: treat solid by removing contained polygons (inner wall loops)
    if force_solid:
        I = keep_only_outer_shells(I)
        if I is None:
            return None

    # remove holes for manufacturing realism
    if rm_holes:
        I = rmholes_like(I)
        if I is None:
            return None

    return I


# =========================
# Board / slot operations
# =========================

def line_poly_intersect_x(poly, y_or_z, x_range):
    x0, x1 = x_range
    scan = LineString([(x0, y_or_z), (x1, y_or_z)])
    inter = poly.boundary.intersection(scan)
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

    # dedup
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

    # fallback: keep largest
    parts.sort(key=lambda pp: pp.area, reverse=True)
    return parts[0]


def make_open_pocket(board_rect, cutout, x_min, a2_min, a2_max, fix_gap_min):
    """
    Force the pocket OPEN to the left edge by bridging cutout to x_min *across full height*.
    This ensures the object space is open (no “closed donut pocket”).
    """
    if cutout is None or cutout.is_empty:
        return board_rect

    # full-height bridge band
    band = box(x_min, a2_min, x_min + fix_gap_min, a2_max)

    cut_open = safe_geom(cutout.union(band))
    if cut_open is None:
        return board_rect

    solid = safe_geom(board_rect.difference(cut_open))
    return solid


def cut_xy_slots(pg_xy, y_levels, rXmin, rXmax, rYmin, rYmax, slotH, edgeSafety, openEps):
    if pg_xy is None or pg_xy.is_empty:
        return pg_xy

    rects = []
    for yC0 in y_levels:
        yC = float(np.clip(yC0, rYmin + edgeSafety + 0.5 * slotH, rYmax - edgeSafety - 0.5 * slotH))
        y1, y2 = yC - 0.5 * slotH, yC + 0.5 * slotH

        xInts = line_poly_intersect_x(pg_xy, yC, (rXmin, rXmax))
        if len(xInts) < 2:
            continue

        for s in range(0, len(xInts) - 1, 2):
            xL, xR = xInts[s], xInts[s + 1]
            usable = max(0.0, (xR - edgeSafety) - (xL + edgeSafety))
            if usable <= 0:
                continue

            localW = xR - xL
            slotDepth = min(0.5 * localW, usable)

            # from RIGHT inward, overshoot right edge
            xSlotR = min(rXmax, xR) + openEps
            xSlotL = max(xL + edgeSafety, xSlotR - slotDepth)

            if xSlotL < xSlotR:
                rects.append(box(xSlotL, y1, xSlotR, y2))

    if not rects:
        return pg_xy

    S = safe_geom(unary_union(rects))
    if S is None:
        return pg_xy

    out = safe_geom(pg_xy.difference(S))
    return safe_geom(out.buffer(0)) if out is not None else None


def cut_xz_slots(pg_xz, z_levels, rXmin, rXmax, rZmin, rZmax, slotH, edgeSafety, openEps):
    if pg_xz is None or pg_xz.is_empty:
        return pg_xz

    rects = []
    for zz in z_levels:
        z1 = max(rZmin, float(zz) - 0.5 * slotH)
        z2 = min(rZmax, float(zz) + 0.5 * slotH)
        if z2 <= z1:
            continue

        zMid = 0.5 * (z1 + z2)

        xInts = line_poly_intersect_x(pg_xz, zMid, (rXmin, rXmax))
        if len(xInts) < 2:
            continue

        for s in range(0, len(xInts) - 1, 2):
            xL, xR = xInts[s], xInts[s + 1]
            usable = max(0.0, (xR - edgeSafety) - (xL + edgeSafety))
            if usable <= 0:
                continue

            localW = xR - xL
            slotDepth = min(0.5 * localW, usable)

            # from LEFT inward, overshoot left edge
            xSlotL = max(rXmin - openEps, xL - openEps)
            xSlotR = min(xR - edgeSafety, xSlotL + slotDepth)

            if xSlotR > xSlotL:
                rects.append(box(xSlotL, z1, xSlotR, z2))

    if not rects:
        return pg_xz

    S = safe_geom(unary_union(rects))
    if S is None:
        return pg_xz

    out = safe_geom(pg_xz.difference(S))
    return safe_geom(out.buffer(0)) if out is not None else None


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
    span = (maxs - mins).max() / 2
    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)


def plot_geom_outline_3d(ax, geom, fixed_value, mode: str, color: str, lw=1.8):
    if geom is None or geom.is_empty:
        return
    for p in explode_polys(geom):
        x, y = p.exterior.xy
        x = np.asarray(x); y = np.asarray(y)
        if mode == "xy":
            ax.plot(x, y, np.full_like(x, fixed_value + CONTOUR_EPS), color, lw=lw)
        elif mode == "xz":
            ax.plot(x, np.full_like(x, fixed_value + CONTOUR_EPS), y, color, lw=lw)


def plot_2d_layout(title, geoms, labels, axis_name2="Y"):
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

        ax.text(offset + w/2, by1 + 5, lab, ha="center", va="bottom", fontweight="bold")
        offset += w + gap

    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    return fig, ax


# =========================
# Main
# =========================

def main():
    mesh = trimesh.load(INPUT_STL, force="mesh")
    mesh = center_like_matlab(mesh)

    V = mesh.vertices
    xr, yr, zr = V[:, 0], V[:, 1], V[:, 2]
    xRange = (float(xr.min()), float(xr.max()))
    yRange = (float(yr.min()), float(yr.max()))
    zRange = (float(zr.min()), float(zr.max()))

    # slice levels (MATLAB-ish)
    marginMin = 5.0
    bottomExtraEff = max(margin, marginMin)

    zBase = max(zRange[0] + 0.5 * materialT, zRange[0] - 0.25 * margin)
    zLevels = np.linspace(zBase, zRange[1] + margin, nXY + 2 * extraLayers)

    baseY = yRange[0] - bottomExtraEff
    yTop = yRange[1] + margin
    yLevels = np.linspace(baseY, yTop, nXZ + 2 * extraLayers)

    xMin = float(X_MIN) if USE_HALF_X else float(xRange[0] - 2 * margin)
    half = "right" if USE_HALF_X else "both"

    # clip extents
    clipXMax = float(xRange[1] + 2 * margin)
    clipYMin = float(yRange[0] - 2 * margin)
    clipYMax = float(yRange[1] + 2 * margin)
    clipZMin = float(zRange[0] - 2 * margin)
    clipZMax = float(zRange[1] + 2 * margin)

    # silhouettes
    xy_slices = []
    for z in zLevels:
        pg = outer_silhouette_2d_half(
            mesh,
            origin=[0, 0, float(z)],
            normal=[0, 0, 1],
            proj_cols=(0, 1),
            x_min=xMin, x_max=clipXMax,
            a2_min=clipYMin, a2_max=clipYMax,
            half=half,
            snap=SNAP,
            dust_area=DUST_AREA,
            force_solid=FORCE_SOLID,
            rm_holes=RM_HOLES,
            clearance=clearance,
        )
        xy_slices.append(pg)

    xz_slices = []
    for y in yLevels:
        pg = outer_silhouette_2d_half(
            mesh,
            origin=[0, float(y), 0],
            normal=[0, 1, 0],
            proj_cols=(0, 2),
            x_min=xMin, x_max=clipXMax,
            a2_min=clipZMin, a2_max=clipZMax,
            half=half,
            snap=SNAP,
            dust_area=DUST_AREA,
            force_solid=FORCE_SOLID,
            rm_holes=RM_HOLES,
            clearance=clearance,
        )
        xz_slices.append(pg)

    print("Silhouette valid: XY =", sum(g is not None and not g.is_empty for g in xy_slices),
          "XZ =", sum(g is not None and not g.is_empty for g in xz_slices))

    # common board extents
    def max_x_of(geoms):
        xs = []
        for g in geoms:
            if g is None or g.is_empty:
                continue
            xs.append(g.bounds[2])
        return max(xs) if xs else 0.0

    xy_xmax = max_x_of(xy_slices)
    xz_xmax = max_x_of(xz_slices)

    boardW = max(xy_xmax, xz_xmax) - xMin + margin + sidePadX

    baseZ = zRange[0] - bottomExtraEff
    zTop = zRange[1] + margin

    rXmin = xMin
    rXmax = xMin + boardW + sidePadX

    rYmin = (baseY - margin)
    rYmax = (yTop + margin)

    rZmin = (baseZ - margin)
    rZmax = (zTop + margin)

    rectXY = box(rXmin, rYmin, rXmax, rYmax)
    rectXZ = box(rXmin, rZmin, rXmax, rZmax)

    # build world slats with OPEN pockets
    worldXY = []
    for cutXY in xy_slices:
        if cutXY is None or cutXY.is_empty:
            solidXY = rectXY
        else:
            solidXY = make_open_pocket(rectXY, cutXY, rXmin, rYmin, rYmax, fixGapMin)
            solidXY = safe_geom(solidXY.buffer(0)) if solidXY is not None else None
            if solidXY is not None:
                solidXY = keep_only_touching_frame(solidXY, (rXmin, rYmin, rXmax, rYmax))
        worldXY.append(solidXY)

    worldXZ = []
    for cutXZ in xz_slices:
        if cutXZ is None or cutXZ.is_empty:
            solidXZ = rectXZ
        else:
            solidXZ = make_open_pocket(rectXZ, cutXZ, rXmin, rZmin, rZmax, fixGapMin)
            solidXZ = safe_geom(solidXZ.buffer(0)) if solidXZ is not None else None
            if solidXZ is not None:
                solidXZ = keep_only_touching_frame(solidXZ, (rXmin, rZmin, rXmax, rZmax))
        worldXZ.append(solidXZ)

    # slots (cross-lap)
    edgeSafety = max(slotSafety, 1.0)
    slotH = materialT + kerfFit
    openEps = 5.0

    worldXY = [cut_xy_slots(pg, yLevels, rXmin, rXmax, rYmin, rYmax, slotH, edgeSafety, openEps) for pg in worldXY]
    worldXZ = [cut_xz_slots(pg, zLevels, rXmin, rXmax, rZmin, rZmax, slotH, edgeSafety, openEps) for pg in worldXZ]

    # 3D preview
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.set_title("WORLD-GRID — 3D Preview (mesh + slats outlines)")

    mesh_poly = Poly3DCollection(mesh.vertices[mesh.faces], alpha=MESH_ALPHA)
    mesh_poly.set_facecolor([0.3, 0.5, 1.0])
    ax.add_collection3d(mesh_poly)

    mins, maxs = mesh.vertices.min(0), mesh.vertices.max(0)
    xlim = (mins[0], maxs[0])
    ylim = (mins[1], maxs[1])
    zlim = (mins[2], maxs[2])

    if showPlanes:
        for z in zLevels:
            X, Y = np.meshgrid(np.linspace(*xlim, PLANE_RES), np.linspace(*ylim, PLANE_RES))
            ax.plot_surface(X, Y, np.full_like(X, z), alpha=PLANE_ALPHA)
        for y in yLevels:
            X, Z = np.meshgrid(np.linspace(*xlim, PLANE_RES), np.linspace(*zlim, PLANE_RES))
            ax.plot_surface(X, np.full_like(X, y), Z, alpha=PLANE_ALPHA)

    for z, geom in zip(zLevels, worldXY):
        plot_geom_outline_3d(ax, geom, float(z), mode="xy", color="r", lw=1.8)
        if USE_HALF_X and geom is not None and not geom.is_empty:
            plot_geom_outline_3d(ax, mirror_geom_x(geom), float(z), mode="xy", color="r", lw=1.2)

    for y, geom in zip(yLevels, worldXZ):
        plot_geom_outline_3d(ax, geom, float(y), mode="xz", color="b", lw=1.8)
        if USE_HALF_X and geom is not None and not geom.is_empty:
            plot_geom_outline_3d(ax, mirror_geom_x(geom), float(y), mode="xz", color="b", lw=1.2)

    ax.view_init(25, 35)
    set_axes_equal(ax, mesh.vertices)
    plt.tight_layout()

    # 2D layouts
    xy_labels = [f"Z={z:.1f}" for z in zLevels]
    xz_labels = [f"Y={y:.1f}" for y in yLevels]
    plot_2d_layout("WORLD-GRID — XY Slats (2D)", worldXY, xy_labels, axis_name2="Y")
    plot_2d_layout("WORLD-GRID — XZ Slats (2D)", worldXZ, xz_labels, axis_name2="Z")

    plt.show()


if __name__ == "__main__":
    main()
