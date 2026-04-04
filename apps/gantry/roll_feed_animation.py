import math
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation


# -------------------------------------------------
# geometry helpers
# -------------------------------------------------
def polyline_length(points):
    total = 0.0
    for i in range(len(points) - 1):
        dx = points[i + 1][0] - points[i][0]
        dy = points[i + 1][1] - points[i][1]
        total += math.hypot(dx, dy)
    return total


def polyline_up_to_length(points, target_len):
    if not points:
        return []

    out = [points[0]]
    travelled = 0.0

    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        seg_len = math.hypot(x2 - x1, y2 - y1)

        if travelled + seg_len <= target_len:
            out.append((x2, y2))
            travelled += seg_len
        else:
            remain = target_len - travelled
            if seg_len > 0:
                t = remain / seg_len
                out.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
            break

    return out


# -------------------------------------------------
# main animation
# -------------------------------------------------
def animate_roll_feed_execution(
    toolpaths,
    gantry,
    feed_positions,
    clip_polyline_to_y_window,
    interval_ms=40,
    cut_speed_mm_per_frame=25,
    feed_speed_mm_per_frame=80,
    dwell_frames_after_cut=15,
):

    VIEW_MARGIN = 20.0

    # -----------------------------
    # safety checks
    # -----------------------------
    if not toolpaths.get("knife"):
        print("No knife toolpaths")
        return

    if not feed_positions:
        print("No feed positions")
        return

    # -----------------------------
    # board bounds
    # -----------------------------
    xs, ys = [], []
    for path in toolpaths["knife"]:
        for x, y in path:
            xs.append(x)
            ys.append(y)

    if not ys:
        print("No geometry points")
        return

    board_ymin = min(ys)
    board_ymax = max(ys)

    fig, ax = plt.subplots(figsize=(10, 6))

    def to_machine(p, feed_offset):
        return (p[0], p[1] - feed_offset)

    # -----------------------------
    # build feed jobs
    # -----------------------------
    feed_jobs = []
    for feed in feed_positions:
        y0 = feed
        y1 = feed + gantry.feed_window_y

        clipped = []
        for path in toolpaths["knife"]:
            clipped.extend(clip_polyline_to_y_window(path, y0, y1))

        total_len = sum(polyline_length(f) for f in clipped)

        feed_jobs.append(
            dict(feed=feed, fragments=clipped, total_len=total_len)
        )

    if not feed_jobs:
        print("No feed jobs created")
        return

    # -----------------------------
    # state machine
    # -----------------------------
    CUTTING = 0
    ROLLING = 1
    DWELL = 2

    mode = CUTTING
    feed_index = 0
    cut_progress = 0.0
    dwell_counter = 0

    current_feed = feed_jobs[0]["feed"]
    target_feed = current_feed

    # -----------------------------
    # draw frame
    # -----------------------------
    def draw(frame_index):
        nonlocal mode, feed_index, cut_progress
        nonlocal current_feed, target_feed, dwell_counter

        ax.clear()

        job = feed_jobs[feed_index]

        # state update
        if mode == CUTTING:
            cut_progress += cut_speed_mm_per_frame
            if cut_progress >= job["total_len"]:
                cut_progress = job["total_len"]
                mode = DWELL
                dwell_counter = dwell_frames_after_cut

        elif mode == DWELL:
            dwell_counter -= 1
            if dwell_counter <= 0 and feed_index < len(feed_jobs) - 1:
                target_feed = feed_jobs[feed_index + 1]["feed"]
                mode = ROLLING

        elif mode == ROLLING:
            delta = target_feed - current_feed
            step = math.copysign(min(abs(delta), feed_speed_mm_per_frame), delta)
            current_feed += step

            if abs(target_feed - current_feed) < 1e-6:
                current_feed = target_feed
                feed_index += 1
                cut_progress = 0.0
                mode = CUTTING

        feed_offset = current_feed
        y0 = feed_offset
        y1 = feed_offset + gantry.feed_window_y

        # gantry window
        ax.axvspan(0, gantry.gantry_width_x, alpha=0.2, color="tan")
        ax.vlines([0, gantry.gantry_width_x], 0, gantry.feed_window_y, colors="blue")
        ax.hlines([0, gantry.feed_window_y], 0, gantry.gantry_width_x, colors="blue")

        # clip geometry
        clipped = []
        for path in toolpaths["knife"]:
            clipped.extend(clip_polyline_to_y_window(path, y0, y1))

        # draw uncut
        for frag in clipped:
            local = [to_machine(p, feed_offset) for p in frag]
            ax.plot([p[0] for p in local], [p[1] for p in local],
                    color="lightgray", linewidth=1)

        # draw cut
        remaining = cut_progress
        knife_pos = None

        for frag in clipped:
            L = polyline_length(frag)
            if remaining <= 0:
                break

            draw_len = min(remaining, L)
            part = polyline_up_to_length(frag, draw_len)
            local = [to_machine(p, feed_offset) for p in part]

            xs = [p[0] for p in local]
            ys = [p[1] for p in local]

            ax.plot(xs, ys, color="blue", linewidth=2)
            knife_pos = (xs[-1], ys[-1])

            remaining -= draw_len

        if knife_pos:
            ax.scatter(*knife_pos, color="red", s=60)

        ax.axhline(board_ymin - feed_offset, color="red", linestyle="--")
        ax.axhline(board_ymax - feed_offset, color="red", linestyle="--")

        ax.set_xlim(-VIEW_MARGIN, gantry.gantry_width_x + VIEW_MARGIN)
        ax.set_ylim(-VIEW_MARGIN, gantry.feed_window_y + VIEW_MARGIN)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.25)

        mode_name = ["CUTTING", "ROLLING", "DWELL"][mode]
        ax.set_title(f"ROLL FEED — {mode_name} — feed {feed_index+1}/{len(feed_jobs)}")

    # -----------------------------
    # animation
    # -----------------------------
    FuncAnimation(fig, draw, frames=2000, interval=interval_ms, repeat=False)
    plt.show()