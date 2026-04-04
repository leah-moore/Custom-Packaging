# apps/integration/filler_integration_dxf.py

import sys
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "apps"))

import ezdxf
import matplotlib.pyplot as plt
from shapely.affinity import rotate, translate, scale
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from Filler.grid_slats import compute_worldgrid_from_stl


DXF_PATH = Path("data/dxf/output.dxf")
STL_PATH = Path("data/stl/input/Asymmetrical/Rabbit.stl")

# View convention:
#   current view x-axis = cardboard length
#   current view y-axis = cardboard width
#
# Machine truth:
#   machine X = cardboard width
#   machine Y = cardboard length / feed direction

CARDBOARD_TARGET_WIDTH_MM = 300.0

# Offset relative to the center of window 0
CARDBOARD_OFFSET_X_MM = 0.0
CARDBOARD_OFFSET_Y_MM = 0.0

SHOW_FEED_WINDOWS = True
FEED_WINDOW_LENGTH_MM = 200.0

AUTO_PLACE_SELECTED = True

WORKLIST_SLAT_IDS = [
    "XY_left_00",
    "XY_left_01",
    "XY_left_02",
    "XY_left_03",
    "XY_right_00",
    "XY_right_01",
    "XY_right_02",
    "XY_right_03",
    "XZ_left_01",
    "XZ_left_02",
    "XZ_left_03",
    "XZ_right_01",
    "XZ_right_02",
    "XZ_right_03",
]

# Used only when AUTO_PLACE_SELECTED = False
MANUAL_LAYOUT = [
    ("XY_left_00", -80.0, -40.0, 0.0),
    ("XY_left_02", 10.0, -30.0, 0.0),
    ("XY_right_00", 80.0, -20.0, 0.0),
    ("XY_right_03", 140.0, -20.0, 0.0),
    ("XZ_left_01", -120.0, -40.0, 90.0),
    ("XZ_right_02", -40.0, -40.0, 90.0),
]


@dataclass
class DxfPreviewConfig:
    min_sheet_area: float = 50000.0
    sheet_index: int = 0
    edge_margin: float = 5.0
    cut_clearance: float = 1.0


CFG = DxfPreviewConfig()


@dataclass
class AutoPlaceConfig:
    part_gap: float = 4.0
    search_step_x: float = 10.0
    search_step_y: float = 10.0
    rotations_deg: tuple[float, ...] = (0.0, 90.0)
    sort_largest_first: bool = True


AUTO_CFG = AutoPlaceConfig()


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

    g = translate(g, xoff=x, yoff=y)
    return safe_geom(g)


def compute_cardboard_mm_scale(sheet, target_cardboard_width_mm):
    minx, miny, maxx, maxy = sheet.bounds
    span_x = maxx - minx  # cardboard length in current view
    span_y = maxy - miny  # cardboard width in current view

    if span_x <= 0 or span_y <= 0:
        raise RuntimeError("Selected sheet has non-positive span.")

    cardboard_width_view_units = span_y
    scale_factor = target_cardboard_width_mm / cardboard_width_view_units

    print(">>> Raw sheet span_x (view length):", span_x)
    print(">>> Raw sheet span_y (view width):", span_y)
    print(">>> Cardboard target width (mm):", target_cardboard_width_mm)
    print(">>> Cardboard scale to mm:", scale_factor)

    return scale_factor


def scale_geom_from_sheet_origin(geom, sheet, scale_factor):
    minx, miny, _, _ = sheet.bounds
    g = scale(geom, xfact=scale_factor, yfact=scale_factor, origin=(minx, miny))
    return safe_geom(g)


def compute_window0_centering_translation(sheet, feed_window_length_mm, offset_x=0.0, offset_y=0.0):
    minx, miny, maxx, maxy = sheet.bounds

    window0_x0 = minx
    window0_x1 = min(minx + feed_window_length_mm, maxx)

    cx = 0.5 * (window0_x0 + window0_x1)
    cy = 0.5 * (miny + maxy)

    dx = -cx + offset_x
    dy = -cy + offset_y

    return dx, dy


def translate_geometry(geom, dx, dy):
    return safe_geom(translate(geom, xoff=dx, yoff=dy))


def translate_geometries(geoms, dx, dy):
    out = []
    for g in geoms:
        tg = translate_geometry(g, dx, dy)
        if tg is not None and not tg.is_empty:
            out.append(tg)
    return out


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
        raise RuntimeError("No sheet-sized polygons found. Try lowering CFG.min_sheet_area.")

    return sheets


def build_usable_region(sheet, holes, edge_margin, cut_clearance):
    inner = safe_geom(sheet.buffer(-edge_margin))
    if inner is None:
        raise RuntimeError("Edge margin removed the entire sheet.")

    keepout = None
    if holes:
        keepout = safe_geom(unary_union(holes).buffer(cut_clearance))

    usable = inner if keepout is None else safe_geom(inner.difference(keepout))
    if usable is None:
        raise RuntimeError("No usable material remains after subtracting holes.")

    return usable


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


def load_all_slat_records(stl_path: Path, n_xy: int | None = None, n_xz: int | None = None):
    if not stl_path.exists():
        raise FileNotFoundError(f"STL not found: {stl_path}")

    data = compute_worldgrid_from_stl(stl_path, n_xy=n_xy, n_xz=n_xz)

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


def build_slat_lookup(all_slat_records):
    return {record_id(rec): rec for rec in all_slat_records}


def get_selected_slats(all_slat_records, worklist_ids):
    lookup = build_slat_lookup(all_slat_records)
    if not worklist_ids:
        return []

    selected = []
    for sid in worklist_ids:
        if sid not in lookup:
            available = "\n".join(sorted(lookup.keys()))
            raise ValueError(f"Unknown slat ID: {sid}\n\nAvailable IDs:\n{available}")
        selected.append(lookup[sid])
    return selected


def print_all_slat_ids(all_slat_records):
    print("\n>>> Available slat IDs:")
    for sid in sorted(record_id(r) for r in all_slat_records):
        print("   ", sid)


def manually_place_selected_slats(all_slat_records, manual_layout):
    lookup = build_slat_lookup(all_slat_records)
    placed = []

    for slat_id, x, y, rot_deg in manual_layout:
        if slat_id not in lookup:
            available = "\n".join(sorted(lookup.keys()))
            raise ValueError(f"Unknown slat_id: {slat_id}\n\nAvailable IDs:\n{available}")

        rec = lookup[slat_id]
        geom = safe_geom(record_geom(rec))
        if geom is None or geom.is_empty:
            continue

        placed_geom = place_geom(geom, x, y, rot_deg)
        placed.append((slat_id, placed_geom, (x, y, rot_deg), True, "manual"))

    return placed


def grid_points_left_to_right(bounds, step_x, step_y):
    minx, miny, maxx, maxy = bounds
    x = minx
    while x <= maxx:
        y = miny
        while y <= maxy:
            yield (x, y)
            y += step_y
        x += step_x


def fits_in_region(candidate, usable_region, placed_geoms, gap):
    if candidate is None or candidate.is_empty:
        return False

    if not candidate.buffer(1e-6).within(usable_region):
        return False

    for g in placed_geoms:
        if candidate.buffer(gap).intersects(g):
            return False

    return True


def auto_place_selected_slats(selected_slats, usable_region, cfg: AutoPlaceConfig):
    prepared = []
    for rec in selected_slats:
        geom = safe_geom(record_geom(rec))
        if geom is None or geom.is_empty:
            continue
        geom = normalize_part_to_origin(geom)
        prepared.append((record_id(rec), geom, geom.area))

    if cfg.sort_largest_first:
        prepared.sort(key=lambda x: x[2], reverse=True)

    placed = []
    placed_geoms = []

    for slat_id, base_geom, _ in prepared:
        best = None
        best_score = None

        for rot_deg in cfg.rotations_deg:
            for x, y in grid_points_left_to_right(
                usable_region.bounds,
                cfg.search_step_x,
                cfg.search_step_y,
            ):
                candidate = place_geom(base_geom, x, y, rot_deg)
                if not fits_in_region(candidate, usable_region, placed_geoms, cfg.part_gap):
                    continue

                score = (x, y)

                if best_score is None or score < best_score:
                    best_score = score
                    best = (slat_id, candidate, (x, y, rot_deg), True, "auto")

        if best is not None:
            placed.append(best)
            placed_geoms.append(best[1])
        else:
            placed.append((slat_id, None, (None, None, None), False, "no valid placement found"))

    return placed


def build_feed_windows_along_length(geom, feed_window_length_mm):
    minx, miny, maxx, maxy = geom.bounds
    windows = []

    x0 = minx
    idx = 0
    while x0 < maxx:
        x1 = min(x0 + feed_window_length_mm, maxx)
        windows.append((idx, x0, x1))
        x0 = x1
        idx += 1

    return windows


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


def draw_feed_windows(ax, geom, feed_window_length_mm):
    windows = build_feed_windows_along_length(geom, feed_window_length_mm)
    minx, miny, maxx, maxy = geom.bounds

    for idx, x0, x1 in windows:
        ax.plot([x0, x0], [miny, maxy], linestyle="--", color="blue", linewidth=1.0)
        ax.plot([x1, x1], [miny, maxy], linestyle="--", color="blue", linewidth=1.0)
        ax.text(
            0.5 * (x0 + x1),
            maxy + 2.0,
            f"window {idx}",
            color="blue",
            ha="left",
            va="bottom",
            fontsize=6,
        )


def preview_raw_dxf_contours(all_polys, title="Raw CV DXF contours"):
    fig, ax = plt.subplots(figsize=(12, 7))
    for poly in all_polys:
        if poly is None or poly.is_empty:
            continue
        x, y = poly.exterior.xy
        ax.plot(x, y, color="black", linewidth=1.0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.grid(True)


def preview_interpreted_cardboard(sheet, holes, usable_region, title="Interpreted cardboard view"):
    fig, ax = plt.subplots(figsize=(12, 7))
    plot_polygon(ax, sheet, color="black", linewidth=1.6)
    for h in holes:
        plot_polygon(ax, h, color="gray", linewidth=1.0)
    plot_geom_fill(ax, usable_region, facecolor="lightgreen", edgecolor="green", alpha=0.25, linewidth=1.0)

    if SHOW_FEED_WINDOWS:
        draw_feed_windows(ax, sheet, FEED_WINDOW_LENGTH_MM)

    ax.plot(0.0, 0.0, marker="o", color="red")
    ax.text(5.0, 5.0, "(0,0)", color="red")

    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.grid(True)


def arrange_geometries_in_rows(records, max_row_width=420.0, gap_x=20.0, gap_y=25.0):
    prepared = []
    for rec in records:
        geom = safe_geom(record_geom(rec))
        if geom is None or geom.is_empty:
            continue
        geom = normalize_part_to_origin(geom)
        minx, miny, maxx, maxy = geom.bounds
        w = maxx - minx
        h = maxy - miny
        prepared.append((rec, geom, w, h))

    arranged = []
    x_cursor = 0.0
    y_cursor = 0.0
    row_height = 0.0

    for rec, geom, w, h in prepared:
        if x_cursor > 0 and (x_cursor + w) > max_row_width:
            x_cursor = 0.0
            y_cursor += row_height + gap_y
            row_height = 0.0

        placed = translate(geom, xoff=x_cursor, yoff=y_cursor)
        arranged.append((rec, placed, placed.bounds))

        x_cursor += w + gap_x
        row_height = max(row_height, h)

    return arranged


def preview_arranged_slats(records, title, color="black", max_row_width=420.0):
    if not records:
        print(f">>> No records to preview for: {title}")
        return

    arranged = arrange_geometries_in_rows(records, max_row_width=max_row_width)
    fig, ax = plt.subplots(figsize=(14, 10))

    overall_minx = float("inf")
    overall_miny = float("inf")
    overall_maxx = float("-inf")
    overall_maxy = float("-inf")

    for rec, geom, bounds in arranged:
        sid = record_id(rec)
        plot_polygon(ax, geom, color=color, linewidth=1.4)
        minx, miny, maxx, maxy = bounds
        overall_minx = min(overall_minx, minx)
        overall_miny = min(overall_miny, miny)
        overall_maxx = max(overall_maxx, maxx)
        overall_maxy = max(overall_maxy, maxy)

        ax.text(minx, maxy + 6.0, sid, fontsize=9, ha="left", va="bottom")

    pad = 20.0
    ax.set_xlim(overall_minx - pad, overall_maxx + pad)
    ax.set_ylim(overall_miny - pad, overall_maxy + 20.0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.grid(True)


def preview_selected_slats_on_cardboard(sheet, holes, usable_region, placed_slats):
    fig, ax = plt.subplots(figsize=(12, 7))

    ax.plot(0.0, 0.0, marker="o", color="red")
    ax.text(5.0, 5.0, "(0,0)", color="red")

    plot_polygon(ax, sheet, color="black", linewidth=1.6)
    for h in holes:
        plot_polygon(ax, h, color="gray", linewidth=1.0)
    plot_geom_fill(ax, usable_region, facecolor="lightgreen", edgecolor="green", alpha=0.25, linewidth=1.0)

    if SHOW_FEED_WINDOWS:
        draw_feed_windows(ax, sheet, FEED_WINDOW_LENGTH_MM)

    for slat_id, geom, pose, ok, note in placed_slats:
        if not ok or geom is None:
            print(f">>> SKIPPED {slat_id}: {note}")
            continue
        plot_polygon(ax, geom, color="darkgreen", linewidth=1.6)

    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Selected slats on cardboard preview")
    ax.grid(True)


def main():
    print(f">>> Loading raw DXF: {DXF_PATH}")
    all_polys = load_closed_polygons_from_dxf(DXF_PATH)
    print(f">>> Raw contour count: {len(all_polys)}")

    preview_raw_dxf_contours(all_polys, title="Raw CV DXF contours")

    sheets = classify_sheet_candidates(all_polys, CFG.min_sheet_area)
    print(f">>> Sheet candidates found: {len(sheets)}")

    for i, (cand_sheet, cand_holes) in enumerate(sheets):
        minx, miny, maxx, maxy = cand_sheet.bounds
        print(
            f"    candidate {i}: area={cand_sheet.area:.2f}, "
            f"bounds={cand_sheet.bounds}, width={maxx-minx:.2f}, height={maxy-miny:.2f}, "
            f"holes={len(cand_holes)}"
        )

    if CFG.sheet_index >= len(sheets):
        raise IndexError(f"sheet_index={CFG.sheet_index} but only {len(sheets)} sheet candidates found")

    sheet_raw, holes_raw = sheets[CFG.sheet_index]

    cardboard_scale = compute_cardboard_mm_scale(sheet_raw, CARDBOARD_TARGET_WIDTH_MM)

    sheet_mm = scale_geom_from_sheet_origin(sheet_raw, sheet_raw, cardboard_scale)
    holes_mm = [scale_geom_from_sheet_origin(h, sheet_raw, cardboard_scale) for h in holes_raw]
    holes_mm = [h for h in holes_mm if h is not None and not h.is_empty]

    dx, dy = compute_window0_centering_translation(
        sheet_mm,
        FEED_WINDOW_LENGTH_MM,
        offset_x=CARDBOARD_OFFSET_X_MM,
        offset_y=CARDBOARD_OFFSET_Y_MM,
    )

    sheet_mm = translate_geometry(sheet_mm, dx, dy)
    holes_mm = translate_geometries(holes_mm, dx, dy)

    usable_region_mm = build_usable_region(
        sheet_mm,
        holes_mm,
        edge_margin=CFG.edge_margin,
        cut_clearance=CFG.cut_clearance,
    )

    print(">>> Window0-centered mm sheet bounds:", sheet_mm.bounds)
    print(">>> Window0-centered usable region bounds:", usable_region_mm.bounds)

    preview_interpreted_cardboard(
        sheet_mm,
        holes_mm,
        usable_region_mm,
        title="Interpreted cardboard view (mm-calibrated, window0-centered)",
    )

    print(f">>> Loading slat records from STL: {STL_PATH}")
    all_slat_records = load_all_slat_records(STL_PATH)
    print(f">>> Slat record count: {len(all_slat_records)}")
    print_all_slat_ids(all_slat_records)

    preview_arranged_slats(
        all_slat_records,
        title="Slat catalog preview",
        color="black",
        max_row_width=420.0,
    )

    selected_slats = get_selected_slats(all_slat_records, WORKLIST_SLAT_IDS)

    if WORKLIST_SLAT_IDS:
        print("\n>>> Selected worklist IDs:")
        for sid in WORKLIST_SLAT_IDS:
            print("   ", sid)
    else:
        print("\n>>> WORKLIST_SLAT_IDS is empty.")

    if AUTO_PLACE_SELECTED:
        print("\n>>> Using AUTO placement")
        placed_slats = auto_place_selected_slats(selected_slats, usable_region_mm, AUTO_CFG)
    else:
        print("\n>>> Using MANUAL placement")
        for row in MANUAL_LAYOUT:
            print("   ", row)
        placed_slats = manually_place_selected_slats(all_slat_records, MANUAL_LAYOUT)

    preview_selected_slats_on_cardboard(
        sheet_mm,
        holes_mm,
        usable_region_mm,
        placed_slats,
    )

    plt.show()


if __name__ == "__main__":
    main()