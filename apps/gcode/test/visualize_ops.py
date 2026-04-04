import matplotlib.pyplot as plt
from typing import List
from gcode.machine_ops_types import Operation, RapidMove, ToolDown, ToolUp, CutPath, FeedAdvance

def visualize_operations(ops: List[Operation], bed_size=(400, 400)):
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_aspect('equal')

    half_w = bed_size[0] / 2
    half_h = bed_size[1] / 2

    # Make (0,0) the visual center
    ax.set_xlim(-half_w - 50, half_w + 50)
    ax.set_ylim(-half_h - 50, half_h + 50)
    ax.set_title("Gantry Preview: Red=Knife, Blue=Crease, Gray=Travel")

    # Bed limits centered on (0,0)
    rect = plt.Rectangle(
        (-half_w, -half_h),
        bed_size[0],
        bed_size[1],
        fill=False,
        color='black',
        alpha=0.1,
        linestyle='--'
    )
    ax.add_patch(rect)

    # Draw origin crosshair
    ax.axhline(0, linewidth=1, alpha=0.3)
    ax.axvline(0, linewidth=1, alpha=0.3)

    current_pos = (0.0, 0.0)
    current_tool = None
    y_offset = 0.0  # Represents Axis A (Rollers)

    for op in ops:
        if isinstance(op, FeedAdvance):
            y_offset += op.distance
            # Visual marker for material advancement
            ax.axhline(y_offset, alpha=0.1, linewidth=1)
            ax.text(-half_w - 40, y_offset, f"A+{op.distance}", fontsize=7, va='center')

        elif isinstance(op, ToolDown):
            current_tool = op.tool

        elif isinstance(op, ToolUp):
            current_tool = None

        elif isinstance(op, RapidMove):
            # World/work coordinates directly, with feed offset applied on Y
            new_pos = (op.to[0], op.to[1] - y_offset)
            ax.plot(
                [current_pos[0], new_pos[0]],
                [current_pos[1], new_pos[1]],
                color='gray',
                linestyle=':',
                alpha=0.3
            )
            current_pos = new_pos

        elif isinstance(op, CutPath):
            # Start from current visualized position, then plot rest of path with Y feed offset
            full_path = [current_pos] + [(p[0], p[1] - y_offset) for p in op.path[1:]]

            px = [p[0] for p in full_path]
            py = [p[1] for p in full_path]

            color = 'red' if current_tool == 'knife' else 'blue'
            ls = '-' if current_tool == 'knife' else '--'

            ax.plot(px, py, color=color, linestyle=ls, linewidth=2, alpha=0.8)
            current_pos = (px[-1], py[-1])

    plt.grid(True, which='both', linestyle='--', alpha=0.2)
    plt.xlabel("X")
    plt.ylabel("Y")
    plt.show()