import sys
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "apps"))

import ezdxf
import matplotlib.pyplot as plt
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union

from Filler.grid_slats import compute_worldgrid_from_stl


# =========================================================
# INPUTS
# =========================================================

STL_PATH = Path("data/stl/input/Asymmetrical/mouse.stl")
DXF_PATH = Path("data/dxf/output.dxf")

OUT_DIR = Path("data/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LAYOUT_DXF_OUT = OUT_DIR / "filler_integration_layout.dxf"


@dataclass
class LayoutConfig:
    edge_margin: float = 5.0
    cut_clearance: float = 1.0
    part_gap: float = 2.0

    step_x: float = 8.0
    step_y: float = 8.0
    allowed_rotations: tuple[float, ...] = (0.0, 90.0)

    min_sheet_area: float = 50000.0
    sheet_index: int = 0

    feed_window_y: float = 200.0


CFG = LayoutConfig()


# =========================================================
# GEOMETRY HELPERS
# =========================================================

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


# =========================================================
# DXF LOADING
# =========================================================

def lwpolyline_to_polygon(entity):
    pts = [(p[0], p[1]) for p in entity.get_points()]
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return safe_geom(Polygon(pts))


def load_closed_polygons_from_dxf(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"DXF not found: {path}")

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    polys = []
    for e in msp.query("LWPOLYLINE"):
        pg = lwpolyline_to_polygon(e)
        if pg is not None:
            polys.extend(explode_polygons(pg))

    if not polys:
        raise RuntimeError("No closed LWPOLYLINE polygons found in DXF.")

    return polys


def classify_sheet_candidates(polys, min_sheet_area):
    polys = [p for p in polys if p.area > 1.0]
    polys.sort(key=lambda p: p.area, reverse=True)

    sheets = []
    for p in polys:
        if p.area < min_sheet_area:
            continue

        holes = []
        for q in polys:
            if q is p:
                continue
            if q.area >= p.area:
                continue
            if q.within(p):
                holes.append(q)

        sheets.append((p, holes))

    if not sheets:
        raise RuntimeError("No sheet-sized polygons found. Try lowering min_sheet_area.")

    return sheets


def build_usable_region(sheet, holes, edge_margin, cut_clearance):
    inner = safe_geom(sheet.buffer(-edge_margin))
    if inner is None:
        raise RuntimeError("Edge margin removed the whole sheet.")

    keepout = None
    if holes:
        keepout = safe_geom(unary_union(holes).buffer(cut_clearance))

    usable = inner if keepout is None else safe_geom(inner.difference(keepout))
    if usable is None:
        raise RuntimeError("No usable material remains after hole keepouts.")

    return usable


# =========================================================
# SLAT RECORD HELPERS
# =========================================================

def record_geom(rec):
    if isinstance(rec, dict):
        for key in ("geom", "polygon", "poly", "shape"):
            if key in rec and rec[key] is not None:
                return rec[key]
        raise KeyError(f"Could not find geometry in record keys: {list(rec.keys())}")
    return rec.geom


def record_id(rec):
    if isinstance(rec, dict):
        for key in ("slat_id", "id", "name", "label"):
            if key in rec and rec[key]:
                return str(rec[key])
        raise KeyError(f"Could not find ID in record keys: {list(rec.keys())}")
    return rec.slat_id


def load_all_slat_records(stl_path: Path):
    if not stl_path.exists():
        raise FileNotFoundError(f"STL not found: {stl_path}")

    data = compute_worldgrid_from_stl(stl_path)

    all_slat_records = (
        data["xy_left_records"]
        + data["xy_right_records"]
        + data["xz_left_records"]
        + data["xz_right_records"]
    )

    cleaned = []
    for rec in all_slat_records:
        g = safe_geom(record_geom(rec))
        if g is not None and not g.is_empty:
            cleaned.append(rec)

    if not cleaned:
        raise RuntimeError("No usable slat records were loaded from STL.")

    return cleaned


# =========================================================
# PLACEMENT
# =========================================================

def normalize_part_to_origin(geom):
    bx0, by0, _, _ = geom.bounds
    return translate(geom, xoff=-bx0, yoff=-by0)


def place_geom(geom, x, y, rot_deg):
    bx0, by0, _, _ = geom.bounds
    g = translate(geom, xoff=-bx0, yoff=-by0)

    if abs(rot_deg) > 1e-9:
        g = rotate(g, rot_deg, origin=(0, 0), use_radians=False)
        rb0, rb1, _, _ = g.bounds
        g = translate(g, xoff=-rb0, yoff=-rb1)

    return translate(g, xoff=x, yoff=y)


def grid_points(bounds, step_x, step_y):
    minx, miny, maxx, maxy = bounds
    x = minx
    while x <= maxx:
        y = miny
        while y <= maxy:
            yield (x, y)
            y += step_y
        x += step_x


def fits_in_region(candidate, usable_region, placed_geoms, gap):
    if not candidate.buffer(1e-6).within(usable_region):
        return False

    for g in placed_geoms:
        if candidate.buffer(gap).intersects(g):
            return False

    return True


def place_slats_on_cardboard(records, usable_region, cfg):
    placed = []
    prepared = []

    for rec in records:
        geom = safe_geom(record_geom(rec))
        if geom is None or geom.is_empty:
            continue
        prepared.append((record_id(rec), normalize_part_to_origin(geom)))

    prepared.sort(key=lambda item: item[1].area, reverse=True)

    for slat_id, base_geom in prepared:
        placed_this = False

        for rot_deg in cfg.allowed_rotations:
            for x, y in grid_points(usable_region.bounds, cfg.step_x, cfg.step_y):
                candidate = place_geom(base_geom, x, y, rot_deg)

                if fits_in_region(candidate, usable_region, placed, cfg.part_gap):
                    placed.append(candidate)
                    placed_this = True
                    print(f"PLACED {slat_id} @ x={x:.1f}, y={y:.1f}, rot={rot_deg:.1f}")
                    break

            if placed_this:
                break

        if not placed_this:
            print(f"SKIPPED {slat_id}")

    return placed


# =========================================================
# FEED BAND VISUALIZATION
# =========================================================

def build_feed_bands(usable_region, feed_window_y):
    minx, miny, maxx, maxy = usable_region.bounds
    bands = []

    y = miny
    idx = 0
    while y < maxy:
        band_box = box(minx, y, maxx, y + feed_window_y)
        band_region = safe_geom(usable_region.intersection(band_box))
        if band_region is not None and not band_region.is_empty:
            bands.append((idx, y, y + feed_window_y, band_region))
        y += feed_window_y
        idx += 1

    return bands


# =========================================================
# PLOTTING
# =========================================================

def plot_polygon(ax, poly, **kwargs):
    if poly is None or poly.is_empty:
        return
    x, y = poly.exterior.xy
    ax.plot(x, y, **kwargs)
    for hole in poly.interiors:
        hx, hy = hole.xy
        ax.plot(hx, hy, **kwargs)


def plot_geom_fill(ax, geom, facecolor=None, edgecolor=None, alpha=0.25, linewidth=1.0):
    for poly in explode_polygons(geom):
        x, y = poly.exterior.xy
        ax.fill(x, y, facecolor=facecolor, edgecolor=edgecolor, alpha=alpha, linewidth=linewidth)


def preview_raw_dxf_contours(all_polys, title="Raw CV DXF contours"):
    fig, ax = plt.subplots(figsize=(10, 12))

    for poly in all_polys:
        if poly is None or poly.is_empty:
            continue
        x, y = poly.exterior.xy
        ax.plot(x, y, color="black", linewidth=1.0)

    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.grid(True)
    plt.show()


def preview_layout(sheet, holes, usable_region, bands, placed_slats):
    fig, ax = plt.subplots(figsize=(10, 12))

    plot_polygon(ax, sheet, color="black", linewidth=1.6)

    for h in holes:
        plot_polygon(ax, h, color="gray", linewidth=1.0)

    plot_geom_fill(
        ax,
        usable_region,
        facecolor="lightgreen",
        edgecolor="green",
        alpha=0.25,
        linewidth=1.0,
    )

    minx, _, maxx, _ = usable_region.bounds
    for idx, y0, y1, band_region in bands:
        ax.plot([minx, maxx], [y0, y0], linestyle="--", linewidth=1.0, color="blue")
        ax.plot([minx, maxx], [y1, y1], linestyle="--", linewidth=1.0, color="blue")

        bx0, by0, bx1, by1 = band_region.bounds
        ax.text(bx1 + 5, (y0 + y1) / 2.0, f"band {idx}", fontsize=8, va="center")

    for g in placed_slats:
        plot_polygon(ax, g, linewidth=1.4)

    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Cardboard layout preview")
    ax.grid(True)
    plt.show()


# =========================================================
# DXF EXPORT
# =========================================================

def add_polygon_to_msp(msp, poly: Polygon, layer: str):
    if poly is None or poly.is_empty:
        return

    msp.add_lwpolyline(
        list(poly.exterior.coords),
        dxfattribs={"layer": layer, "closed": True},
    )

    for hole in poly.interiors:
        msp.add_lwpolyline(
            list(hole.coords),
            dxfattribs={"layer": layer, "closed": True},
        )


def export_layout_dxf(out_path: Path, input_contours, sheet, holes, usable_region, bands, placed_slats):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    layer_names = (
        "INPUT_CONTOURS",
        "SHEET",
        "HOLES",
        "USABLE",
        "FEED_BANDS",
        "PLACED_CUTS",
    )
    for layer in layer_names:
        if layer not in doc.layers:
            doc.layers.add(name=layer)

    for poly in input_contours:
        add_polygon_to_msp(msp, poly, "INPUT_CONTOURS")

    add_polygon_to_msp(msp, sheet, "SHEET")

    for h in holes:
        add_polygon_to_msp(msp, h, "HOLES")

    for pg in explode_polygons(usable_region):
        add_polygon_to_msp(msp, pg, "USABLE")

    for _, _, _, band_region in bands:
        for pg in explode_polygons(band_region):
            add_polygon_to_msp(msp, pg, "FEED_BANDS")

    for g in placed_slats:
        add_polygon_to_msp(msp, g, "PLACED_CUTS")

    doc.saveas(out_path)


# =========================================================
# MAIN
# =========================================================

def main():
    print(f">>> Loading raw CV DXF: {DXF_PATH}")
    input_contours = load_closed_polygons_from_dxf(DXF_PATH)
    print(f">>> Raw contour count: {len(input_contours)}")

    preview_raw_dxf_contours(input_contours, title="Raw CV DXF contours")

    sheets = classify_sheet_candidates(input_contours, CFG.min_sheet_area)
    if CFG.sheet_index >= len(sheets):
        raise IndexError(
            f"sheet_index={CFG.sheet_index} but only {len(sheets)} sheet candidates found"
        )

    sheet, holes = sheets[CFG.sheet_index]

    print(">>> Selected sheet bounds:", sheet.bounds)
    print(">>> Selected hole count:", len(holes))

    usable_region = build_usable_region(
        sheet,
        holes,
        edge_margin=CFG.edge_margin,
        cut_clearance=CFG.cut_clearance,
    )

    bands = build_feed_bands(usable_region, CFG.feed_window_y)
    print(f">>> Feed bands: {len(bands)}")

    print(f">>> Loading slat records from STL: {STL_PATH}")
    all_slat_records = load_all_slat_records(STL_PATH)
    print(f">>> Slat record count: {len(all_slat_records)}")

    placed_slats = place_slats_on_cardboard(all_slat_records, usable_region, CFG)
    print(f">>> Placed slats: {len(placed_slats)}")

    preview_layout(sheet, holes, usable_region, bands, placed_slats)

    export_layout_dxf(
        LAYOUT_DXF_OUT,
        input_contours=input_contours,
        sheet=sheet,
        holes=holes,
        usable_region=usable_region,
        bands=bands,
        placed_slats=placed_slats,
    )
    print(f">>> Wrote layout DXF: {LAYOUT_DXF_OUT}")


if __name__ == "__main__":
    main()