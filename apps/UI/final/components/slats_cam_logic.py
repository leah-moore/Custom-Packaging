# slats_cam_logic.py

from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box
from shapely.affinity import translate, rotate as shp_rotate
from shapely.ops import unary_union, transform as geom_transform

from apps.integration import filler_integration_dxf as fidxf


# =========================================================
# RECORD HELPERS
# =========================================================
def rec_get(rec, key, default=None):
    if isinstance(rec, dict):
        return rec.get(key, default)
    return getattr(rec, key, default)


def record_geom(rec):
    # Try the "final" geometry first
    g = rec_get(rec, "geom")
    if g is not None:
        return g

    # fallback to integration helper
    try:
        return fidxf.record_geom(rec)
    except Exception:
        return None


def record_id(rec):
    try:
        return fidxf.record_id(rec)
    except Exception:
        sid = rec_get(rec, "slat_id")
        if sid:
            return str(sid)
        fam = rec_get(rec, "family", "SLAT")
        side = rec_get(rec, "side", "na")
        idx = rec_get(rec, "index", 0)
        return f"{fam}_{side}_{idx:02d}"


def record_family(rec):
    fam = rec_get(rec, "family")
    if fam:
        return str(fam)
    sid = record_id(rec).upper()
    if sid.startswith("XY"):
        return "XY"
    if sid.startswith("XZ"):
        return "XZ"
    return "UNK"


def record_side(rec):
    side = rec_get(rec, "side")
    if side:
        return str(side)
    sid = record_id(rec).lower()
    if "_left_" in sid:
        return "left"
    if "_right_" in sid:
        return "right"
    return "na"


# =========================================================
# GEOMETRY HELPERS
# =========================================================
def iter_polys(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            yield from iter_polys(g)
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            yield from iter_polys(g)
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_polys(g)


def normalize_part(geom):
    try:
        return fidxf.normalize_part_to_origin(geom)
    except Exception:
        if geom is None or geom.is_empty:
            return None
        bx0, by0, _, _ = geom.bounds
        return translate(geom, xoff=-bx0, yoff=-by0)


def place_geom(geom, x, y, rot_deg):
    try:
        return fidxf.place_geom(geom, x, y, rot_deg)
    except Exception:
        g = normalize_part(geom)
        if g is None or g.is_empty:
            return None

        # rotate around normalized part origin so 0,0 stays as the placement anchor
        if rot_deg:
            g = shp_rotate(g, rot_deg, origin=(0, 0), use_radians=False)

            # after rotation, re-normalize to keep top-left / min corner anchored cleanly
            bx0, by0, _, _ = g.bounds
            g = translate(g, xoff=-bx0, yoff=-by0)

        return translate(g, xoff=x, yoff=y)


def geom_collides(test_geom, other_geoms, tol=1e-6):
    if test_geom is None or test_geom.is_empty:
        return True

    for other in other_geoms:
        if other is None or other.is_empty:
            continue
        try:
            if test_geom.intersects(other) and test_geom.intersection(other).area > tol:
                return True
        except Exception:
            if test_geom.intersects(other):
                return True
    return False


def geom_inside_region(test_geom, region):
    if test_geom is None or test_geom.is_empty:
        return False
    if region is None or region.is_empty:
        return False
    try:
        return region.buffer(1e-6).contains(test_geom) or region.buffer(1e-6).covers(test_geom)
    except Exception:
        return region.contains(test_geom) or region.covers(test_geom)


# =========================================================
# SLAT GENERATION
# =========================================================
def generate_slats(stl_path, xy_count, xz_count):
    raw = fidxf.load_all_slat_records(
        stl_path,
        n_xy=xy_count,
        n_xz=xz_count,
    )
    return filter_records_by_requested_counts(raw, xy_count, xz_count)


def filter_records_by_requested_counts(records, xy_count, xz_count):
    buckets = {
        ("XY", "left"): [],
        ("XY", "right"): [],
        ("XZ", "left"): [],
        ("XZ", "right"): [],
    }

    for rec in records:
        fam = record_family(rec).upper()
        side = record_side(rec).lower()
        key = (fam, side)
        if key in buckets:
            buckets[key].append(rec)

    for key in buckets:
        buckets[key] = sorted(buckets[key], key=lambda r: record_id(r))

    out = []
    out.extend(buckets[("XY", "left")][:xy_count])
    out.extend(buckets[("XY", "right")][:xy_count])
    out.extend(buckets[("XZ", "left")][:xz_count])
    out.extend(buckets[("XZ", "right")][:xz_count])
    return out


# =========================================================
# PREVIEW DRAW
# =========================================================
def draw_library_preview(canvas, rec):
    canvas.delete("all")

    geom = normalize_part(record_geom(rec))
    if geom is None or geom.is_empty:
        return

    cw = max(int(canvas.winfo_reqwidth()), 150)
    ch = max(int(canvas.winfo_reqheight()), 95)
    pad = 10

    bx0, by0, bx1, by1 = geom.bounds
    gw = max(bx1 - bx0, 1e-9)
    gh = max(by1 - by0, 1e-9)

    s = min((cw - 2 * pad) / gw, (ch - 2 * pad) / gh) * 0.9
    ox = (cw - gw * s) / 2
    oy = (ch - gh * s) / 2

    fam = record_family(rec).upper()
    outline = "#FFAA33" if fam.startswith("XZ") else "#66CCFF"

    for poly in iter_polys(geom):
        pts = []
        for x0, y0 in poly.exterior.coords:
            cx = ox + (x0 - bx0) * s
            cy = ch - (oy + (y0 - by0) * s)
            pts.extend([cx, cy])

        canvas.create_polygon(pts, outline=outline, fill="", width=1)


# =========================================================
# WINDOW / MACHINE GEOMETRY
# =========================================================
def clip_geom_to_window(geom, window, sheet_bounds):
    if geom is None or geom.is_empty or window is None:
        return None

    _, x0, x1 = window
    miny, maxy = sheet_bounds

    rect = box(x0, miny, x1, maxy)
    clipped = geom.intersection(rect)

    if clipped is None or clipped.is_empty:
        return None
    return clipped


def material_to_machine_geom(geom, window):
    if geom is None or geom.is_empty or window is None:
        return None

    _, x0, x1 = window
    cx = 0.5 * (x0 + x1)

    def mapper(x, y, z=None):
        mx = y
        my = x - cx
        if z is None:
            return (mx, my)
        return (mx, my, z)

    return geom_transform(mapper, geom)