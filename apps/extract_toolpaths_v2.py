"""
RSC toolpath extraction + visualization scaffold

Rules:
- Cuts   = knife paths (blue)
- Creases = crease wheel paths (red dashed)
- NO cut path is allowed to lie on a crease line
"""

import math
import matplotlib.pyplot as plt

from apps.Box.boxes import gen_RSC   # <-- adjust import to your project
from apps.Box.boxes import rebuild_edges_and_reclassify


# -------------------------------------------------
# MACHINE WORK AREA (mm)
# -------------------------------------------------
FEED_WINDOW_X = 300.0     # roller feed window (X)
GANTRY_WIDTH_Y = 400.0    # stationary width (Y)

FEED_START_CLEARANCE_X = 50.0   # mm before first cut


# -------------------------------------------------
# SMALL HELPERS
# -------------------------------------------------
def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l)


def _cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def _segment_on_segment(p, q, a, b, tol=1e-6):
    """
    Returns True if segment pq lies on the same line as ab
    and overlaps it by any positive length.
    """
    u = (q[0] - p[0], q[1] - p[1])
    v = (b[0] - a[0], b[1] - a[1])

    # must be collinear
    if abs(_cross(u, v)) > tol:
        return False
    if abs(_cross((a[0] - p[0], a[1] - p[1]), u)) > tol:
        return False

    # project onto dominant axis for overlap test
    if abs(u[0]) >= abs(u[1]):
        pmin, pmax = sorted([p[0], q[0]])
        amin, amax = sorted([a[0], b[0]])
    else:
        pmin, pmax = sorted([p[1], q[1]])
        amin, amax = sorted([a[1], b[1]])

    return max(pmin, amin) < min(pmax, amax)


def segment_intersects_x_window(p, q, x0, x1):
    return not (max(p[0], q[0]) < x0 or min(p[0], q[0]) > x1)


# -------------------------------------------------
# CLIPPING TO X-WINDOW (vertical slab)
# -------------------------------------------------
def clip_segment_to_x_window(a, b, x0, x1, eps=1e-9):
    """
    Clip segment AB to vertical slab x in [x0, x1].
    Returns (p, q) or None.
    """
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay

    t0, t1 = 0.0, 1.0  # param on segment

    def _clip(p, q):
        nonlocal t0, t1
        if abs(p) < eps:
            return q >= 0
        t = q / p
        if p < 0:
            if t > t1:
                return False
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return False
            if t < t1:
                t1 = t
        return True

    # x >= x0  =>  ax + t*dx >= x0  =>  t*dx >= x0-ax
    if not _clip(dx, x0 - ax):
        return None
    # x <= x1  =>  ax + t*dx <= x1  =>  -t*dx >= ax-x1
    if not _clip(-dx, ax - x1):
        return None
    if t1 < t0:
        return None

    p = (ax + t0 * dx, ay + t0 * dy)
    q = (ax + t1 * dx, ay + t1 * dy)

    if math.hypot(q[0]-p[0], q[1]-p[1]) < 1e-6:
        return None

    return p, q


def clip_polyline_to_x_window(path, x0, x1):
    """
    Clip a polyline to x in [x0, x1].
    Returns list of polyline fragments inside the window.
    """
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

        # finalize fragment on boundary-crossings
        a_in = (x0 <= a[0] <= x1)
        b_in = (x0 <= b[0] <= x1)
        if a_in != b_in:
            if len(cur) >= 2:
                fragments.append(cur)
            cur = []

    if len(cur) >= 2:
        fragments.append(cur)

    return fragments


# -------------------------------------------------
# LEADS FOR KNIFE ONLY
# -------------------------------------------------
def add_leads(path, lead_in=30.0, lead_out=30.0, min_len=30.0):
    """
    Add linear lead-in and lead-out to a knife path.
    """
    if len(path) < 2:
        return path

    total_len = 0.0
    for i in range(len(path) - 1):
        dx = path[i + 1][0] - path[i][0]
        dy = path[i + 1][1] - path[i][1]
        total_len += math.hypot(dx, dy)

    if total_len < min_len:
        return path

    # lead-in
    p0, p1 = path[0], path[1]
    dx0 = p1[0] - p0[0]
    dy0 = p1[1] - p0[1]
    l0 = math.hypot(dx0, dy0)
    if l0 < 1e-6:
        return path
    ux0, uy0 = dx0 / l0, dy0 / l0
    lead_start = (p0[0] - ux0 * lead_in, p0[1] - uy0 * lead_in)

    # lead-out
    pn_1, pn = path[-2], path[-1]
    dxn = pn[0] - pn_1[0]
    dyn = pn[1] - pn_1[1]
    ln = math.hypot(dxn, dyn)
    if ln < 1e-6:
        return path
    uxn, uyn = dxn / ln, dyn / ln
    lead_end = (pn[0] + uxn * lead_out, pn[1] + uyn * lead_out)

    return [lead_start] + path + [lead_end]


# -------------------------------------------------
# DIELINE BOUNDS / OFFSETS
# -------------------------------------------------
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


def dieline_x_bounds(dl):
    xs = []
    for poly in dl.cuts:
        xs.extend(p[0] for p in poly)
    for a, b in dl.creases:
        xs.append(a[0])
        xs.append(b[0])
    return min(xs), max(xs)


def offset_dieline_in_x(dl, dx):
    def shift(p):
        return (p[0] + dx, p[1])

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for (a, b) in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {k: [shift(p) for p in poly] for k, poly in dl.debug["panels"].items()}

    rebuild_edges_and_reclassify(dl)


def generate_x_sections(dl, section_width):
    xmin, xmax = dieline_x_bounds(dl)
    # IMPORTANT: start sections at 0 in dieline/world coords? your first figure does that.
    # Keep your current behavior (start at 0) so section lines match your first plot.
    sections = []
    x = 0.0
    i = 0
    while x < xmax:
        sections.append({"index": i, "x0": x, "x1": x + section_width})
        x += section_width
        i += 1
    return sections


# -------------------------------------------------
# SECTION OVERVIEW PLOT (YOUR FIRST FIGURE)
# -------------------------------------------------
def plot_sections(dl, sections):
    fig, ax = plt.subplots(figsize=(11, 6))

    knife_edges = dl.debug.get("knife_edges")

    # knife edges in black (clipped to each section for visibility)
    for s in sections:
        x0, x1 = s["x0"], s["x1"]
        for e in knife_edges:
            p, q = e.p1, e.p2
            if not segment_intersects_x_window(p, q, x0, x1):
                continue
            if (
                p[1] < 0 or p[1] > GANTRY_WIDTH_Y or
                q[1] < 0 or q[1] > GANTRY_WIDTH_Y
            ):
                continue
            ax.plot([p[0], q[0]], [p[1], q[1]], color="black", linewidth=1.2)

    # creases in red dashed
    for (a, b) in dl.creases:
        ax.plot([a[0], b[0]], [a[1], b[1]], color="red", linestyle="--", linewidth=1.0)

    # draw sections
    for s in sections:
        ax.axvspan(s["x0"], s["x1"], alpha=0.10, color="skyblue")
        ax.vlines([s["x0"], s["x1"]], ymin=0, ymax=GANTRY_WIDTH_Y,
                  colors="blue", linestyles="solid", linewidth=1.0, alpha=0.6)
        ax.text(0.5 * (s["x0"] + s["x1"]), 0, f'Section {s["index"]}',
                va="bottom", ha="center", fontsize=9, color="blue")

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
    """
    Chain unordered line segments into ordered polylines.
    """
    segments = sorted(segments, key=lambda s: (min(s[0][1], s[1][1]), min(s[0][0], s[1][0])))
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


def extract_toolpaths(dl):
    """
    Knife paths come ONLY from classified knife edges.
    Creases come ONLY from dl.creases.
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

        # drop if outside gantry Y
        if (
            p[1] < USABLE_Y_MIN or p[1] > USABLE_Y_MAX or
            q[1] < USABLE_Y_MIN or q[1] > USABLE_Y_MAX
        ):
            continue

        knife_segs.append((p, q))

    knife_paths = chain_segments(knife_segs)
    knife_paths = [add_leads(path) for path in knife_paths]

    return {
        "knife": knife_paths,
        "crease": list(dl.creases),
    }


# -------------------------------------------------
# SECTION EXECUTION PLOTS (YOUR SECOND FIGURE)  ✅ FIXED
# -------------------------------------------------
def plot_section_start_end_figures(dl, toolpaths, sections, show_travel=True):
    """
    One figure per feed step (section), shown in MACHINE FRAME:
      - Gantry window is always x in [0, FEED_WINDOW_X]
      - We plot the *executed* knife + crease content that lies in that step
      - Start/End markers are shown for each clipped knife fragment
    """
    for s in sections:
        idx = s["index"]
        x0, x1 = s["x0"], s["x1"]
        feed_offset = idx * FEED_WINDOW_X  # stepwise feed (machine frame shift)

        def to_machine(p):
            return (p[0] - feed_offset, p[1])

        fig, ax = plt.subplots(figsize=(11, 6))

        # --- gantry window (fixed in machine frame) ---
        ax.axvspan(0, FEED_WINDOW_X, alpha=0.10, color="skyblue", zorder=0)
        ax.vlines([0, FEED_WINDOW_X], ymin=0, ymax=GANTRY_WIDTH_Y,
                  colors="blue", linewidth=1.2, alpha=0.7, zorder=1)

        # --- faint dieline context (shifted) ---
        for poly in dl.cuts:
            poly_m = [to_machine(p) for p in poly]
            ax.plot([p[0] for p in poly_m], [p[1] for p in poly_m],
                    color="black", linewidth=0.6, alpha=0.15, zorder=1)

        # =========================================================
        # EXECUTED CREASES IN THIS FEED WINDOW (RED DASHED)
        # =========================================================
        for (a, b) in toolpaths["crease"]:
            # clip crease to this section in dieline/world frame
            clipped = clip_segment_to_x_window(a, b, x0, x1)
            if clipped is None:
                continue
            a_c, b_c = clipped
            a_m, b_m = to_machine(a_c), to_machine(b_c)

            ax.plot([a_m[0], b_m[0]], [a_m[1], b_m[1]],
                    color="red", linestyle="--", linewidth=2.0, zorder=3)

        # =========================================================
        # EXECUTED KNIFE CUTS IN THIS FEED WINDOW (BLUE) + START/END
        # =========================================================
        frag_count = 0
        knife_frags = []

        for path in toolpaths["knife"]:
            # remove leads for "executed cut core"
            core = path[:]   # include leads for clipping
            if len(core) < 2:
                continue

            frags = clip_polyline_to_x_window(core, x0, x1)
            for frag in frags:
                if len(frag) < 2:
                    continue
                knife_frags.append(frag)

        # stable ordering for labels
        knife_frags = sorted(knife_frags, key=lambda p: (p[0][0], p[0][1]))

        for frag in knife_frags:
            frag_m = [to_machine(p) for p in frag]
            xs = [p[0] for p in frag_m]
            ys = [p[1] for p in frag_m]

            ax.plot(xs, ys, color="blue", linewidth=2.0, zorder=4)

            # start/end markers for this fragment
            ax.scatter(xs[0], ys[0], s=60, color="green", zorder=6)
            ax.text(xs[0] + 4, ys[0], f"S{frag_count}", color="green",
                    fontsize=9, va="center", zorder=6)

            ax.scatter(xs[-1], ys[-1], s=60, color="purple", zorder=6)
            ax.text(xs[-1] + 4, ys[-1], f"E{frag_count}", color="purple",
                    fontsize=9, va="center", zorder=6)

            frag_count += 1

        # --- travel moves (visual only) ---
        if show_travel and len(knife_frags) >= 2:
            for k in range(len(knife_frags) - 1):
                a = to_machine(knife_frags[k][-1])
                b = to_machine(knife_frags[k + 1][0])
                ax.plot([a[0], b[0]], [a[1], b[1]],
                        color="gray", linestyle=":", linewidth=1.2, alpha=0.9, zorder=2)

        ax.set_aspect("equal")
        ax.invert_yaxis()
        ax.set_ylim(GANTRY_WIDTH_Y + 10, -10)
        ax.set_title(f"Feed step {idx} (offset {feed_offset:.0f} mm): START/END in gantry window")
        ax.grid(True, alpha=0.2)
        plt.show()


# -------------------------------------------------
# OPTIONAL: GLOBAL TOOLPATH PLOT (not sectioned)
# -------------------------------------------------
def plot_toolpaths(toolpaths, title="Toolpaths"):
    fig, ax = plt.subplots(figsize=(11, 6))

    ax.axhspan(0, GANTRY_WIDTH_Y, color="green", alpha=0.06, label="Gantry usable Y")

    for (a, b) in toolpaths["crease"]:
        ax.plot([a[0], b[0]], [a[1], b[1]], color="red", linestyle="--", linewidth=2.0, zorder=1)

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
    dim = dict(L=200, W=200, H=100)

    class Material:
        thickness = 2.8

    class Tooling:
        EX = 0
        score_width = 1.2

    dl = gen_RSC(dim, Material(), Tooling())

    # center under gantry width (Y constraint)
    center_dieline_in_workable_y(dl, GANTRY_WIDTH_Y)

    # add feed-in clearance before first cut
    offset_dieline_in_x(dl, FEED_START_CLEARANCE_X)

    # slice along feed direction (your first figure)
    sections = generate_x_sections(dl, FEED_WINDOW_X)
    plot_sections(dl, sections)

    # extract + plot per-section executed content (your second figures)
    toolpaths = extract_toolpaths(dl)
    plot_section_start_end_figures(dl, toolpaths, sections, show_travel=True)
