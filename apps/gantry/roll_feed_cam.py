"""
Roll-feed CAM execution model.

Takes WORLD-SPACE toolpaths (knife + crease) and executes them
in fixed gantry feed windows, advancing material between windows.

This models machines where:
- X is fed by rollers (unbounded job length)
- Y is limited by gantry width
- The gantry executes, stops, feed advances, repeats
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from gcode.machine_ops_planner import RapidMove, ToolDown, ToolUp, CutPath
from gcode.machine_ops_types import FeedAdvance


Point = Tuple[float, float]

BOARD_CLEARANCE = 5.0  # mm
VIEW_MARGIN = 20.0      # how much extra context to show outside window

# =================================================
# Machine definition
# =================================================

@dataclass
class RollFeedGantry:
    feed_window_y: float     # how far material advances each feed step (Y direction)
    gantry_width_x: float    # fixed cutting width of the gantry (X direction)
    feed_clearance_y: float = 0.0  # optional lead-in before first cut

# =================================================
# Geometry helpers
# =================================================
def _segment_intersects_y_window(a, b, y0, y1):
    return not (max(a[1], b[1]) < y0 or min(a[1], b[1]) > y1)


def _clip_segment_to_y_window(a, b, y0, y1, eps=1e-9):
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay

    # horizontal segment
    if abs(dy) < eps:
        if ay < y0 - eps or ay > y1 + eps:
            return None
        return (ax, ay), (bx, by)

    t0, t1 = 0.0, 1.0
    ty0 = (y0 - ay) / dy
    ty1 = (y1 - ay) / dy

    t_enter = min(ty0, ty1)
    t_exit  = max(ty0, ty1)

    t0 = max(t0, t_enter)
    t1 = min(t1, t_exit)

    if t1 < t0:
        return None

    p = (ax + t0*dx, ay + t0*dy)
    q = (ax + t1*dx, ay + t1*dy)

    MIN_LEN = 0.1  # mm — below this is numerically meaningless for cutting

    if ((p[0]-q[0])**2 + (p[1]-q[1])**2)**0.5 < MIN_LEN:
        return None


    return p, q


def _clip_polyline_to_y_window(path, y0, y1):
    if len(path) < 2:
        return []

    frags = []
    cur = []

    def add(pt):
        if not cur or abs(cur[-1][0]-pt[0]) + abs(cur[-1][1]-pt[1]) > 1e-9:
            cur.append(pt)

    for i in range(len(path) - 1):
        clipped = _clip_segment_to_y_window(path[i], path[i+1], y0, y1)
        if clipped is None:
            if len(cur) >= 2:
                frags.append(cur)
            cur = []
            continue

        p, q = clipped
        add(p)
        add(q)

        a_in = y0 <= path[i][1] <= y1
        b_in = y0 <= path[i+1][1] <= y1
        if a_in != b_in:
            if len(cur) >= 2:
                frags.append(cur)
            cur = []

    if len(cur) >= 2:
        frags.append(cur)

    return frags

# =================================================
# Sectioning
# =================================================
def _toolpaths_y_bounds(toolpaths):
    ys = []
    for path in toolpaths.get("knife", []):
        ys.extend(p[1] for p in path)
    for (a, b) in toolpaths.get("crease", []):
        ys.extend([a[1], b[1]])
    return (min(ys), max(ys)) if ys else (0.0, 0.0)


def generate_feed_windows(toolpaths, gantry: RollFeedGantry):
    ymin, ymax = _toolpaths_y_bounds(toolpaths)
    y = min(ymin, gantry.feed_clearance_y)

    windows = []
    i = 0
    while y < ymax:
        windows.append({
            "index": i,
            "y0": y,
            "y1": y + gantry.feed_window_y
        })
        y += gantry.feed_window_y
        i += 1

    return windows

def split_toolpaths_by_feed_window(toolpaths, windows, gantry):
    per = {w["index"]: {"knife": [], "crease": []} for w in windows}

    for path in toolpaths.get("knife", []):
        ymin = min(p[1] for p in path)
        ymax = max(p[1] for p in path)

        assigned = False

        for w in windows:
            feed_offset = w["index"] * gantry.feed_window_y

            # Convert to machine coordinates
            min_local = ymin - feed_offset
            max_local = ymax - feed_offset

            # ✅ must lie entirely inside workable machine window
            if min_local >= 0 and max_local <= gantry.feed_window_y:
                per[w["index"]]["knife"].append(path)
                assigned = True
                break

        # path does not fully fit any window → handled dynamically later
        if not assigned:
            continue


    # ---- crease segments (same logic) ----
    for (a, b) in toolpaths.get("crease", []):
        seg_ymin = min(a[1], b[1])
        seg_ymax = max(a[1], b[1])

        assigned = False

        for w in windows:
            feed_offset = w["index"] * gantry.feed_window_y

            min_local = seg_ymin - feed_offset
            max_local = seg_ymax - feed_offset

            if min_local >= 0 and max_local <= gantry.feed_window_y:
                per[w["index"]]["crease"].append((a, b))
                assigned = True
                break

        if not assigned:
            raise RuntimeError("Crease segment too tall for feed window")

    return per

# =================================================

def order_paths_by_nearest(paths):
    if not paths:
        return []

    remaining = list(paths)        # copy (do not mutate caller)
    ordered = [remaining.pop(0)]

    while remaining:
        last = ordered[-1][-1]

        def dist2(p):
            dx = p[0][0] - last[0]
            dy = p[0][1] - last[1]
            return dx*dx + dy*dy

        i = min(range(len(remaining)), key=lambda i: dist2(remaining[i]))
        ordered.append(remaining.pop(i))

    return ordered


def orient_path_towards(path, target):
    def d2(a, b):
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        return dx*dx + dy*dy

    if d2(path[0], target) <= d2(path[-1], target):
        return path
    return list(reversed(path))



# =================================================
# Execution → machine ops
# =================================================

def _section_to_ops(section, gantry: RollFeedGantry, feed_offset: float):
    ops = []

    x0 = gantry.gantry_width_x / 2.0
    y0 = gantry.feed_window_y / 2.0

    cursor = (-x0, -y0)

    def to_machine(p):
        return (
            p[0] - x0,
            (p[1] - feed_offset) - y0,
        )

    knife_paths = order_paths_by_nearest(section.get("knife", []))

    for path in knife_paths:
        path = orient_path_towards(
            path,
            target=(cursor[0] + x0, cursor[1] + y0 + feed_offset),
        )

        local = [to_machine(p) for p in path]
        ops.append(RapidMove(to=local[0]))
        ops.append(ToolDown(tool="knife"))
        ops.append(CutPath(path=local))
        ops.append(ToolUp())

        cursor = local[-1]

    for (a, b) in section.get("crease", []):
        a_m, b_m = to_machine(a), to_machine(b)
        ops.append(RapidMove(to=a_m))
        ops.append(ToolDown(tool="crease"))
        ops.append(CutPath(path=[a_m, b_m]))
        ops.append(ToolUp())
        cursor = b_m

    return ops

# =================================================
# Public entry point
# =================================================

def build_roll_feed_ops(toolpaths, gantry: RollFeedGantry):
    """
    Roll-feed policy (your requirement):

    - If a path CAN fit in one window (height <= feed_window_y),
      never cut it partially. Feed until it is fully visible, then cut whole.
    - Only clip-cut when a path is taller than the window (cannot ever fit).
    - If nothing is actionable, feed forward to the next geometry.
    """

    remaining = list(toolpaths.get("knife", []))
    ops = []
    tool_is_down = False


    current_feed_offset = 0.0
    feed_history = [current_feed_offset]

    def y_min(path): return min(p[1] for p in path)
    def y_max(path): return max(p[1] for p in path)
    def height(path): return y_max(path) - y_min(path)

    EPS = 1e-6  # boundary tolerance

    SAFETY_ITERS = 50000
    iters = 0

    while remaining:
        iters += 1
        if iters > SAFETY_ITERS:
            raise RuntimeError("Feed runaway (too many iterations)")

        feed_offset = current_feed_offset
        window_top = feed_offset + gantry.feed_window_y

        # prune paths fully behind current feed
        remaining = [p for p in remaining if y_max(p) >= feed_offset - EPS]
        if not remaining:
            break

        full = []                 # fully visible now
        clip_needed = []          # taller than window, intersects
        partial_but_fits = []     # intersects but not fully visible, and can fit in one window

        for path in remaining:
            ymin = y_min(path)
            ymax = y_max(path)
            h = ymax - ymin

            local_min = ymin - feed_offset
            local_max = ymax - feed_offset

            fits_now = (local_min >= -EPS and local_max <= gantry.feed_window_y + EPS)
            intersects = (local_max >= -EPS and local_min <= gantry.feed_window_y + EPS)
            taller_than_window = (h > gantry.feed_window_y + EPS)

            if fits_now:
                full.append(path)
            elif intersects and taller_than_window:
                clip_needed.append(path)
            elif intersects:
                # intersects, NOT tall => it CAN be cut in one window, just not yet
                partial_but_fits.append(path)

        # ------------------------------------------------
        # 1) Cut any fully visible work (single-window completion)
        # ------------------------------------------------
        if full:
            lowest_y = min(y_min(p) for p in full)
            ROW_EPS = 1.0

            lowest_full = [p for p in full if abs(y_min(p) - lowest_y) <= ROW_EPS]
            section = {"knife": lowest_full, "crease": []}

            # ✅ EMIT CUT OPS HERE
            ops.extend(_section_to_ops(section, gantry, feed_offset))
            tool_is_down = False


            full_ids = set(map(id, lowest_full))
            remaining = [p for p in remaining if id(p) not in full_ids]
            continue


        # ------------------------------------------------
        # 2) If something is partial-but-can-fit, FEED until it fits (do NOT cut)
        # ------------------------------------------------
        if partial_but_fits:
            # Feed to the earliest position where ANY of them becomes fully contained
            required_offsets = [
                y_max(p) - gantry.feed_window_y
                for p in partial_but_fits
            ]

            new_feed_offset = max(current_feed_offset, min(required_offsets))
            feed_dist = new_feed_offset - current_feed_offset

            if feed_dist <= EPS:
                feed_dist = 0.01

            if tool_is_down:
                ops.append(ToolUp())
                tool_is_down = False

            ops.append(FeedAdvance(distance=feed_dist))
            current_feed_offset += feed_dist
            feed_history.append(current_feed_offset)
            continue


        # ------------------------------------------------
        # 3) Tall paths: clip-cut visible fragments, then advance one window
        # ------------------------------------------------
        if clip_needed:
            y0, y1 = feed_offset, window_top
            clipped_frags = []
            for path in clip_needed:
                clipped_frags.extend(_clip_polyline_to_y_window(path, y0, y1))

            if clipped_frags:
                section = {"knife": clipped_frags, "crease": []}
                ops.extend(_section_to_ops(section, gantry, feed_offset))

            if tool_is_down:
                ops.append(ToolUp())
                tool_is_down = False

            ops.append(FeedAdvance(distance=gantry.feed_window_y))
            current_feed_offset += gantry.feed_window_y
            feed_history.append(current_feed_offset)
            continue

        # ------------------------------------------------
        # 4) Nothing intersects: feed to next geometry start (flexible feed)
        # ------------------------------------------------
        next_starts = [y_min(p) for p in remaining if y_min(p) > window_top + EPS]

        # --------------------------------------------
        # normal flexible feed to next geometry
        # --------------------------------------------
        if next_starts:
            next_y = min(next_starts)
            feed_dist = next_y - window_top
            if feed_dist <= EPS:
                feed_dist = 0.01

            if tool_is_down:
                ops.append(ToolUp())
                tool_is_down = False

            ops.append(FeedAdvance(distance=feed_dist))
            current_feed_offset += feed_dist
            feed_history.append(current_feed_offset)
            continue

        # --------------------------------------------
        # FAILSAFE — something exists but we cannot act
        # force forward progress by one full window
        # --------------------------------------------
        if tool_is_down:
            ops.append(ToolUp())
            tool_is_down = False

        ops.append(FeedAdvance(distance=gantry.feed_window_y))
        current_feed_offset += gantry.feed_window_y
        feed_history.append(current_feed_offset)
        continue


    return ops, feed_history

# =================================================
# Visualization (debug / sanity)
# =================================================

def plot_roll_feed_execution(toolpaths, gantry, feed_positions, show_travel=True):

    
    """
    CNC-style visualization (STRICT):

    - MACHINE coordinates only
    - Origin (0,0) at bottom-left of gantry
    - NOTHING outside the workable (shaded) area is drawn
    - Shaded region == truth
    """

    import matplotlib.pyplot as plt


    def get_board_bounds(toolpaths):
        xs, ys = [], []
        for path in toolpaths["knife"]:
            for x, y in path:
                xs.append(x)
                ys.append(y)
        return min(xs), max(xs), min(ys), max(ys)

    board_xmin, board_xmax, board_ymin, board_ymax = \
        get_board_bounds(toolpaths)


    # -------------------------------------------------
    # Draw each feed window view
    # -------------------------------------------------
    for idx, feed_offset in enumerate(feed_positions):

        def to_machine(p):
            return (
                p[0] - gantry.gantry_width_x / 2.0,
                (p[1] - feed_offset) - gantry.feed_window_y / 2.0,
            )

        xmin = -gantry.gantry_width_x / 2.0
        xmax =  gantry.gantry_width_x / 2.0
        ymin = -gantry.feed_window_y / 2.0
        ymax =  gantry.feed_window_y / 2.0

        fig, ax = plt.subplots(figsize=(10, 6))

        # ---------------------------------------------
        # label collision avoidance helper
        # ---------------------------------------------
        placed_labels = []

        def place_label(x, y, text, color):
            tx, ty = x + 2, y
            MIN_DIST = 3.0
            SHIFT = 2.0

            while any((tx - px)**2 + (ty - py)**2 < MIN_DIST**2
                      for px, py in placed_labels):
                tx += SHIFT
                ty += SHIFT

            ax.text(tx, ty, text, color=color, fontsize=6)
            placed_labels.append((tx, ty))

        # -------------------------------------------------
        # WORKABLE GANTRY WINDOW (machine frame)
        # -------------------------------------------------
        ax.axvspan(xmin, xmax, alpha=0.2, color="tan", zorder=0)

        ax.vlines([xmin, xmax],
                  ymin=ymin, ymax=ymax,
                  colors="blue", linewidth=2, zorder=1)

        ax.hlines([ymin, ymax],
                  xmin=xmin, xmax=xmax,
                  colors="blue", linewidth=2, zorder=1)

        # -------------------------------------------------
        # CLIP WORLD GEOMETRY INTO THIS WINDOW
        # -------------------------------------------------
        y0 = feed_offset
        y1 = feed_offset + gantry.feed_window_y

        knife = []
        for path in toolpaths["knife"]:
            knife.extend(_clip_polyline_to_y_window(path, y0, y1))

        # -------------------------------------------------
        # DRAW KNIFE PATHS
        # -------------------------------------------------
        drawn_paths = []

        for k, frag_world in enumerate(knife):

            frag = [to_machine(p) for p in frag_world]

            xs = [p[0] for p in frag]
            ys = [p[1] for p in frag]
            ax.plot(xs, ys, color="blue", linewidth=2.2, zorder=3)

            sx, sy = frag[0]
            ax.scatter(sx, sy, s=80, marker="x", color="green",
                       linewidths=2, zorder=5)
            place_label(sx, sy, f"S{k}", "green")

            ex, ey = frag[-1]
            ax.scatter(ex, ey, s=70, marker="o", facecolors="none",
                       edgecolors="purple", linewidths=2, zorder=5)
            place_label(ex, ey, f"E{k}", "purple")

            drawn_paths.append(frag)

        # -------------------------------------------------
        # TRAVEL MOVES (visual only)
        # -------------------------------------------------
        if show_travel and len(drawn_paths) >= 2:
            for i in range(len(drawn_paths) - 1):
                a = drawn_paths[i][-1]
                b = drawn_paths[i + 1][0]

                if (
                    xmin <= a[0] <= xmax and
                    xmin <= b[0] <= xmax and
                    ymin <= a[1] <= ymax and
                    ymin <= b[1] <= ymax
                ):
                    ax.plot(
                        [a[0], b[0]],
                        [a[1], b[1]],
                        linestyle=":",
                        color="gray",
                        linewidth=1.2,
                        zorder=2,
                    )

        # -------------------------------------------------
        # CNC CONVENTIONS
        # -------------------------------------------------
        ax.set_xlim(xmin - VIEW_MARGIN, xmax + VIEW_MARGIN)
        ax.set_ylim(ymin - VIEW_MARGIN, ymax + VIEW_MARGIN)
        
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.25)

        ax.set_title(f"CNC VIEW — Feed Offset {feed_offset:.2f}")
        ax.set_xlabel("X (machine)")
        ax.set_ylabel("Y (machine)")

        ax.axhline(board_ymin - feed_offset,
                   color="red", linestyle="--", linewidth=1)
        ax.axhline(board_ymax - feed_offset,
                   color="red", linestyle="--", linewidth=1)

        plt.show()
