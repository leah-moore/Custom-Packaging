"""
RSC toolpath extraction + visualization scaffold

Rules:
- Cuts = knife paths
- Creases = crease wheel paths
- NO cut path is allowed to lie on a crease line
- Preview uses RAW knife paths by default (no fake lead-in/lead-out geometry)
"""

import matplotlib.pyplot as plt
from apps.Box.boxes import gen_RSC, gen_OTE
from apps.Box.boxes import rebuild_edges_and_reclassify

import math


def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l)


# -------------------------------------------------
# MACHINE WORK AREA (mm)
# -------------------------------------------------

FEED_WINDOW_X = 200.0
GANTRY_WIDTH_Y = 300.0
FEED_START_CLEARANCE_X = 40.0


def _bbox_intersects_x_window(points, x0, x1):
    xs = [p[0] for p in points]
    return not (max(xs) < x0 or min(xs) > x1)


def _segment_intersects_x_window(a, b, x0, x1):
    return not (max(a[0], b[0]) < x0 or min(a[0], b[0]) > x1)


def _path_intersects_window(path, x0, x1):
    return _bbox_intersects_x_window(path, x0, x1)


def _crease_intersects_window(a, b, x0, x1):
    return _segment_intersects_x_window(a, b, x0, x1)


def _pick_section_for_path(path, sections):
    xs = [p[0] for p in path]
    xm = 0.5 * (min(xs) + max(xs))
    for s in sections:
        if s["x0"] <= xm < s["x1"]:
            return s["index"]
    return sections[-1]["index"]


def clip_segment_to_x_window(a, b, x0, x1, eps=1e-9):
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay

    if abs(dx) < eps:
        if ax < x0 - eps or ax > x1 + eps:
            return None
        if (abs(bx - ax) + abs(by - ay)) < 1e-12:
            return None
        return (ax, ay), (bx, by)

    t0, t1 = 0.0, 1.0

    tx0 = (x0 - ax) / dx
    tx1 = (x1 - ax) / dx
    t_enter = min(tx0, tx1)
    t_exit = max(tx0, tx1)

    t0 = max(t0, t_enter)
    t1 = min(t1, t_exit)

    if t1 < t0:
        return None

    p = (ax + t0 * dx, ay + t0 * dy)
    q = (ax + t1 * dx, ay + t1 * dy)

    if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6:
        return None

    return p, q


def clip_polyline_to_x_window(path, x0, x1):
    if len(path) < 2:
        return []

    fragments = []
    cur = []

    def addpt(pt):
        nonlocal cur
        if not cur:
            cur = [pt]
        else:
            if math.hypot(cur[-1][0] - pt[0], cur[-1][1] - pt[1]) > 1e-9:
                cur.append(pt)

    for i in range(len(path) - 1):
        a = path[i]
        b = path[i + 1]
        clipped = clip_segment_to_x_window(a, b, x0, x1)
        if clipped is None:
            if len(cur) >= 2:
                fragments.append(cur)
            cur = []
            continue

        p, q = clipped
        addpt(p)
        addpt(q)

        a_in = (x0 <= a[0] <= x1)
        b_in = (x0 <= b[0] <= x1)
        if a_in != b_in:
            if len(cur) >= 2:
                fragments.append(cur)
            cur = []

    if len(cur) >= 2:
        fragments.append(cur)

    return fragments


def split_toolpaths_by_section(toolpaths, sections):
    """
    Per-section operations in that window.
    Uses RAW knife geometry. No lead-in/lead-out assumptions.
    """
    per = {s["index"]: {"knife": [], "crease": []} for s in sections}

    for path in toolpaths["knife"]:
        xs = [p[0] for p in path]
        xmin, xmax = min(xs), max(xs)

        for s in sections:
            x0, x1 = s["x0"], s["x1"]
            if xmax < x0 or xmin > x1:
                continue
            frags = clip_polyline_to_x_window(path, x0, x1)
            per[s["index"]]["knife"].extend(frags)

    for (a, b) in toolpaths["crease"]:
        xmin, xmax = min(a[0], b[0]), max(a[0], b[0])
        for s in sections:
            x0, x1 = s["x0"], s["x1"]
            if xmax < x0 or xmin > x1:
                continue
            clipped = clip_segment_to_x_window(a, b, x0, x1)
            if clipped is not None:
                per[s["index"]]["crease"].append(clipped)

    return per


def plot_section_start_end_figures(dl, toolpaths, sections, show_travel=True):
    per = split_toolpaths_by_section(toolpaths, sections)

    for s in sections:
        idx = s["index"]
        feed_offset = s["x0"]

        sec = per[idx]
        sec["knife"] = sorted(sec["knife"], key=lambda p: (p[0][0], p[0][1]))

        def to_machine(p):
            return (p[0] - feed_offset, p[1])

        fig, ax = plt.subplots(figsize=(11, 6))

        ax.axvspan(0, FEED_WINDOW_X, alpha=0.10, color="skyblue", zorder=0)
        ax.vlines(
            [0, FEED_WINDOW_X],
            ymin=0,
            ymax=GANTRY_WIDTH_Y,
            colors="blue",
            linewidth=1.0,
            alpha=0.7,
            zorder=1
        )

        for poly in dl.cuts:
            poly_m = [to_machine(p) for p in poly]
            ax.plot(
                [p[0] for p in poly_m],
                [p[1] for p in poly_m],
                color="black",
                linewidth=0.5,
                alpha=0.15,
                zorder=1
            )

        for (a, b) in sec["crease"]:
            a_m, b_m = to_machine(a), to_machine(b)
            ax.plot(
                [a_m[0], b_m[0]],
                [a_m[1], b_m[1]],
                color="red",
                linestyle="--",
                linewidth=2.2,
                zorder=3
            )

        for k, path in enumerate(sec["knife"]):
            path_m = [to_machine(p) for p in path]
            xs = [p[0] for p in path_m]
            ys = [p[1] for p in path_m]

            ax.plot(
                xs,
                ys,
                color="blue",
                linewidth=2.2,
                zorder=4
            )

            ax.scatter(xs[0], ys[0], s=60, color="green", zorder=6)
            ax.text(
                xs[0] + 4,
                ys[0],
                f"S{k}",
                color="green",
                fontsize=9,
                va="center",
                zorder=6
            )

            ax.scatter(xs[-1], ys[-1], s=60, color="purple", zorder=6)
            ax.text(
                xs[-1] + 4,
                ys[-1],
                f"E{k}",
                color="purple",
                fontsize=9,
                va="center",
                zorder=6
            )

        if show_travel and len(sec["knife"]) >= 2:
            for k in range(len(sec["knife"]) - 1):
                a = to_machine(sec["knife"][k][-1])
                b = to_machine(sec["knife"][k + 1][0])
                ax.plot(
                    [a[0], b[0]],
                    [a[1], b[1]],
                    color="gray",
                    linestyle=":",
                    linewidth=1.2,
                    alpha=0.9,
                    zorder=2
                )

        ax.set_aspect("equal")
        ax.invert_yaxis()
        ax.set_ylim(GANTRY_WIDTH_Y + 10, -10)
        ax.set_title(
            f"Feed step {idx} (offset {feed_offset:.0f} mm): START/END in gantry window"
        )
        ax.grid(True, alpha=0.2)

        plt.show()


def offset_dieline_in_x(dl, dx):
    def shift(p):
        return (p[0] + dx, p[1])

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for (a, b) in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {
            k: [shift(p) for p in poly]
            for k, poly in dl.debug["panels"].items()
        }

    rebuild_edges_and_reclassify(dl)


# -------------------------------------------------
# GEOMETRY HELPERS
# -------------------------------------------------

def _cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def _segment_on_segment(p, q, a, b, tol=1e-6):
    u = (q[0] - p[0], q[1] - p[1])
    v = (b[0] - a[0], b[1] - a[1])

    if abs(_cross(u, v)) > tol:
        return False
    if abs(_cross((a[0] - p[0], a[1] - p[1]), u)) > tol:
        return False

    if abs(u[0]) >= abs(u[1]):
        pmin, pmax = sorted([p[0], q[0]])
        amin, amax = sorted([a[0], b[0]])
    else:
        pmin, pmax = sorted([p[1], q[1]])
        amin, amax = sorted([a[1], b[1]])

    return max(pmin, amin) < min(pmax, amax)


def segment_intersects_x_window(p, q, x0, x1):
    return not (max(p[0], q[0]) < x0 or min(p[0], q[0]) > x1)


def clip_segment_to_y_bounds(a, b, y0, y1, eps=1e-9):
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay

    # horizontal segment
    if abs(dy) < eps:
        if ay < y0 - eps or ay > y1 + eps:
            return None
        if math.hypot(dx, dy) < 1e-12:
            return None
        return (ax, ay), (bx, by)

    t0, t1 = 0.0, 1.0
    ty0 = (y0 - ay) / dy
    ty1 = (y1 - ay) / dy

    t_enter = min(ty0, ty1)
    t_exit = max(ty0, ty1)

    t0 = max(t0, t_enter)
    t1 = min(t1, t_exit)

    if t1 < t0:
        return None

    p = (ax + t0 * dx, ay + t0 * dy)
    q = (ax + t1 * dx, ay + t1 * dy)

    if math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6:
        return None

    return p, q


def plot_section_geometry_baseline(dl, sections):
    knife_edges = dl.debug.get("knife_edges", [])

    for s in sections:
        idx = s["index"]
        x0, x1 = s["x0"], s["x1"]
        feed_offset = s["x0"]

        def to_machine(p):
            return (p[0] - feed_offset, p[1])

        fig, ax = plt.subplots(figsize=(11, 6))

        ax.axvspan(0, FEED_WINDOW_X, alpha=0.10, color="skyblue", zorder=0)
        ax.vlines([0, FEED_WINDOW_X], ymin=0, ymax=GANTRY_WIDTH_Y,
                  colors="blue", linewidth=1.2, alpha=0.7, zorder=1)

        drawn_black = 0
        for e in knife_edges:
            p, q = e.p1, e.p2

            if not segment_intersects_x_window(p, q, x0, x1):
                continue
            clipped_x = clip_segment_to_x_window(p, q, x0, x1)
            if clipped_x is None:
                continue

            p_c, q_c = clipped_x

            clipped_y = clip_segment_to_y_bounds(p_c, q_c, 0.0, GANTRY_WIDTH_Y)
            if clipped_y is None:
                continue

            p_m, q_m = to_machine(clipped_y[0]), to_machine(clipped_y[1])
            ax.plot([p_m[0], q_m[0]], [p_m[1], q_m[1]],
                    color="black", linewidth=2.0, zorder=3)
            drawn_black += 1

        drawn_red = 0
        for (a, b) in dl.creases:
            if not _segment_intersects_x_window(a, b, x0, x1):
                continue
            clipped_x = clip_segment_to_x_window(a, b, x0, x1)
            if clipped_x is None:
                continue

            clipped_y = clip_segment_to_y_bounds(clipped_x[0], clipped_x[1], 0.0, GANTRY_WIDTH_Y)
            if clipped_y is None:
                continue

            a_m, b_m = to_machine(clipped_y[0]), to_machine(clipped_y[1])
            ax.plot([a_m[0], b_m[0]], [a_m[1], b_m[1]],
                    color="red", linestyle="--", linewidth=2.5, zorder=4)
            drawn_red += 1

        ax.set_aspect("equal")
        ax.invert_yaxis()
        ax.set_ylim(GANTRY_WIDTH_Y + 10, -10)
        ax.set_title(f"BASELINE geometry step {idx} (offset {feed_offset:.0f}): "
                     f"black={drawn_black}, red={drawn_red}")
        ax.grid(True, alpha=0.2)
        plt.show()


def plot_section_geometry(dl, sections):
    knife_edges = dl.debug["knife_edges"]

    for s in sections:
        fig, ax = plt.subplots(figsize=(11, 6))

        for e in knife_edges:
            p, q = e.p1, e.p2
            clipped = clip_segment_to_y_bounds(p, q, 0.0, GANTRY_WIDTH_Y)
            if clipped is None:
                continue
            p, q = clipped
            ax.plot([p[0], q[0]], [p[1], q[1]],
                    color="black", linewidth=1)

        for (a, b) in dl.creases:
            clipped = clip_segment_to_y_bounds(a, b, 0.0, GANTRY_WIDTH_Y)
            if clipped is None:
                continue
            a_c, b_c = clipped
            ax.plot([a_c[0], b_c[0]], [a_c[1], b_c[1]],
                    color="red", linestyle="--", linewidth=1)

        ax.set_xlim(s["x0"], s["x1"])
        ax.set_ylim(GANTRY_WIDTH_Y, 0)
        ax.set_aspect("equal")

        ax.vlines([s["x0"], s["x1"]], 0, GANTRY_WIDTH_Y,
                  colors="blue", linewidth=1.5)

        ax.set_title(f"SECTION {s['index']} — BASELINE GEOMETRY")
        ax.grid(True, alpha=0.2)

        plt.show()


def add_leads(
    path,
    lead_in=30.0,
    lead_out=30.0,
    min_len=30.0
):
    if len(path) < 2:
        return path

    total_len = 0.0
    for i in range(len(path) - 1):
        dx = path[i + 1][0] - path[i][0]
        dy = path[i + 1][1] - path[i][1]
        total_len += math.hypot(dx, dy)

    if total_len < min_len:
        return path

    p0, p1 = path[0], path[1]
    dx0 = p1[0] - p0[0]
    dy0 = p1[1] - p0[1]
    l0 = math.hypot(dx0, dy0)

    if l0 < 1e-6:
        return path

    ux0, uy0 = dx0 / l0, dy0 / l0

    lead_start = (
        p0[0] - ux0 * lead_in,
        p0[1] - uy0 * lead_in
    )

    pn_1, pn = path[-2], path[-1]
    dxn = pn[0] - pn_1[0]
    dyn = pn[1] - pn_1[1]
    ln = math.hypot(dxn, dyn)

    if ln < 1e-6:
        return path

    uxn, uyn = dxn / ln, dyn / ln

    lead_end = (
        pn[0] + uxn * lead_out,
        pn[1] + uyn * lead_out
    )

    return [lead_start] + path + [lead_end]


def dieline_y_bounds(dl):
    ys = []
    for poly in dl.cuts:
        ys.extend(p[1] for p in poly)
    for a, b in dl.creases:
        ys.append(a[1])
        ys.append(b[1])
    return min(ys), max(ys)


def center_dieline_in_workable_y(dl, workable_y):
    ymin, ymax = dieline_y_bounds(dl)
    dieline_h = ymax - ymin

    offset = (workable_y - dieline_h) * 0.5 - ymin

    def shift(p):
        return (p[0], p[1] + offset)

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for (a, b) in dl.creases]
    rebuild_edges_and_reclassify(dl)


def dieline_x_bounds(dl):
    xs = []
    for poly in dl.cuts:
        xs.extend(p[0] for p in poly)
    for a, b in dl.creases:
        xs.append(a[0])
        xs.append(b[0])
    return min(xs), max(xs)


def generate_x_sections(dl, section_width):
    x_min, x_max = dieline_x_bounds(dl)

    sections = []
    x = x_min
    i = 0

    while x < x_max:
        sections.append({
            "index": i,
            "x0": x,
            "x1": x + section_width
        })
        x += section_width
        i += 1

    return sections


def center_dieline_in_workable_x(dl, workable_x):
    xmin, xmax = dieline_x_bounds(dl)
    dieline_w = xmax - xmin

    offset = (workable_x - dieline_w) * 0.5 - xmin

    def shift(p):
        return (p[0] + offset, p[1])

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for (a, b) in dl.creases]
    rebuild_edges_and_reclassify(dl)

    return offset


# -------------------------------------------------
# SECTIONING
# -------------------------------------------------

def plot_sections(dl, sections):
    fig, ax = plt.subplots(figsize=(11, 6))

    knife_edges = dl.debug.get("knife_edges")

    for s in sections:
        x0, x1 = s["x0"], s["x1"]

        for e in knife_edges:
            p, q = e.p1, e.p2

            if not segment_intersects_x_window(p, q, x0, x1):
                continue

            clipped_x = clip_segment_to_x_window(p, q, x0, x1)
            if clipped_x is None:
                continue

            clipped_y = clip_segment_to_y_bounds(clipped_x[0], clipped_x[1], 0.0, GANTRY_WIDTH_Y)
            if clipped_y is None:
                continue

            p_c, q_c = clipped_y

            ax.plot(
                [p_c[0], q_c[0]],
                [p_c[1], q_c[1]],
                color="black",
                linewidth=1.2
            )

    for (a, b) in dl.creases:
        clipped = clip_segment_to_y_bounds(a, b, 0.0, GANTRY_WIDTH_Y)
        if clipped is None:
            continue

        a_c, b_c = clipped
        ax.plot(
            [a_c[0], b_c[0]],
            [a_c[1], b_c[1]],
            color="red",
            linestyle="--",
            linewidth=1.0
        )

    for s in sections:
        ax.axvspan(
            s["x0"],
            s["x1"],
            ymin=0.0,
            ymax=1.0,
            alpha=0.10,
            color="skyblue"
        )

        ax.vlines(
            [s["x0"], s["x1"]],
            ymin=0,
            ymax=GANTRY_WIDTH_Y,
            colors="blue",
            linestyles="solid",
            linewidth=1.0,
            alpha=0.6
        )

        ax.text(
            0.5 * (s["x0"] + s["x1"]),
            0,
            f'Section {s["index"]}',
            va="bottom",
            ha="center",
            fontsize=9,
            color="blue"
        )

    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_title(f"Dieline sectioned into {FEED_WINDOW_X:.0f} mm X feed windows", y=1.02)
    ax.grid(True, alpha=0.2)
    plt.show()


# -------------------------------------------------
# TOOLPATH EXTRACTION
# -------------------------------------------------

def segment_is_on_any_crease(p, q, creases):
    for (a, b) in creases:
        if _segment_on_segment(p, q, a, b):
            return True
    return False


def chain_segments(segments, tol=1e-6):
    segments = sorted(
        segments,
        key=lambda s: (min(s[0][1], s[1][1]), min(s[0][0], s[1][0]))
    )
    unused = segments[:]
    paths = []

    def close(p, q):
        return abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol

    while unused:
        p, q = unused.pop(0)
        path = [p, q]

        changed = True
        while changed:
            changed = False
            for i, (a, b) in enumerate(unused):
                if close(path[-1], a):
                    path.append(b)
                elif close(path[-1], b):
                    path.append(a)
                elif close(path[0], b):
                    path.insert(0, a)
                elif close(path[0], a):
                    path.insert(0, b)
                else:
                    continue

                unused.pop(i)
                changed = True
                break

        paths.append(path)

    return paths


def extract_toolpaths(dl, add_knife_leads=False):
    """
    Knife paths come ONLY from classified knife edges.
    Creases come ONLY from dl.creases.

    add_knife_leads=False by default so preview matches real dieline geometry.
    """
    USABLE_Y_MIN = 0.0
    USABLE_Y_MAX = GANTRY_WIDTH_Y

    knife_edges = dl.debug.get("knife_edges")

    if knife_edges is None:
        from apps.Box.edges import classify_edges
        knife_edges, _ = classify_edges(dl.edges)

    knife_segs = []

    for e in knife_edges:
        p, q = e.p1, e.p2

        clipped = clip_segment_to_y_bounds(p, q, USABLE_Y_MIN, USABLE_Y_MAX)
        if clipped is None:
            continue

        p, q = clipped

        if segment_is_on_any_crease(p, q, dl.creases):
            continue

        knife_segs.append((p, q))

    knife_paths = chain_segments(knife_segs)

    if add_knife_leads:
        knife_paths = [add_leads(path) for path in knife_paths]

    return {
        "knife": knife_paths,
        "crease": list(dl.creases),
    }


# -------------------------------------------------
# VISUALIZATION
# -------------------------------------------------

def plot_toolpaths(toolpaths, title="Toolpaths"):
    fig, ax = plt.subplots(figsize=(11, 6))

    ax.axhspan(
        0, GANTRY_WIDTH_Y,
        color="green",
        alpha=0.06,
        label="Gantry usable Y"
    )

    for (a, b) in toolpaths["crease"]:
        clipped = clip_segment_to_y_bounds(a, b, 0.0, GANTRY_WIDTH_Y)
        if clipped is None:
            continue
        a_c, b_c = clipped
        ax.plot(
            [a_c[0], b_c[0]],
            [a_c[1], b_c[1]],
            color="red",
            linestyle="--",
            linewidth=2.0,
            zorder=1
        )

    for poly in toolpaths["knife"]:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]

        ax.plot(xs, ys, color="blue", linewidth=1.5, zorder=2)

        ax.scatter(xs[0], ys[0], color="green", s=40, zorder=5)
        ax.text(xs[0] + 5, ys[0], "START", color="green", fontsize=8, va="center")

        ax.scatter(xs[-1], ys[-1], color="purple", s=40, zorder=5)
        ax.text(xs[-1] + 5, ys[-1], "END", color="purple", fontsize=8, va="center")

    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    plt.show()


# -------------------------------------------------
# ENTRY POINT
# -------------------------------------------------

if __name__ == "__main__":

    dim = dict(L=180, W=150, H=100)

    class Material:
        thickness = 2.8

    class Tooling:
        EX = 0
        score_width = 1.2

    dl = gen_RSC(dim, Material(), Tooling())

    center_dieline_in_workable_y(dl, GANTRY_WIDTH_Y)
    offset_dieline_in_x(dl, FEED_START_CLEARANCE_X)

    rebuild_edges_and_reclassify(dl)

    sections = generate_x_sections(dl, FEED_WINDOW_X)
    plot_sections(dl, sections)
    plot_section_geometry(dl, sections)

    toolpaths = extract_toolpaths(dl, add_knife_leads=False)
    plot_toolpaths(toolpaths, title="RAW toolpaths (no leads)")
    plot_section_start_end_figures(dl, toolpaths, sections, show_travel=True)

    # Optional:
    # gcode_toolpaths = extract_toolpaths(dl, add_knife_leads=True)