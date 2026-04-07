from dataclasses import dataclass
from typing import List

from gcode.machine_ops_types import (
    RapidMove, ToolDown, ToolUp, CutPath, PivotAction
)


@dataclass
class PreviewAction:
    kind: str
    start_time_s: float
    end_time_s: float
    start_state: dict
    end_state: dict


# --- Tunables ---
XY_FEED_MM_PER_S = 50.0
B_ROT_SPEED_DEG_PER_S = 90.0
Z_MOVE_TIME_S = 0.2  # pivot up/down time


def build_preview_actions(ops) -> List[PreviewAction]:
    actions = []
    t = 0.0

    state = {
        "x": 0.0,
        "y": 0.0,
        "z": 10.0,
        "b": 0.0,
        "tool_down": False,
    }

    for op in ops:

        # -----------------
        # RAPID MOVE
        # -----------------
        if isinstance(op, RapidMove):
            x, y = op.to

            dx = x - state["x"]
            dy = y - state["y"]
            dist = (dx**2 + dy**2) ** 0.5
            duration = dist / XY_FEED_MM_PER_S if dist > 0 else 0.0

            new_state = state.copy()
            new_state["x"] = x
            new_state["y"] = y

            actions.append(PreviewAction(
                kind="rapid",
                start_time_s=t,
                end_time_s=t + duration,
                start_state=state.copy(),
                end_state=new_state.copy(),
            ))

            state = new_state
            t += duration

        # -----------------
        # TOOL DOWN
        # -----------------
        elif isinstance(op, ToolDown):
            new_state = state.copy()
            new_state["tool_down"] = True
            new_state["z"] = 0.0

            actions.append(PreviewAction(
                kind="tool_down",
                start_time_s=t,
                end_time_s=t + Z_MOVE_TIME_S,
                start_state=state.copy(),
                end_state=new_state.copy(),
            ))

            state = new_state
            t += Z_MOVE_TIME_S

        # -----------------
        # TOOL UP
        # -----------------
        elif isinstance(op, ToolUp):
            new_state = state.copy()
            new_state["tool_down"] = False
            new_state["z"] = 10.0

            actions.append(PreviewAction(
                kind="tool_up",
                start_time_s=t,
                end_time_s=t + Z_MOVE_TIME_S,
                start_state=state.copy(),
                end_state=new_state.copy(),
            ))

            state = new_state
            t += Z_MOVE_TIME_S

        # -----------------
        # PIVOT (B AXIS)
        # -----------------
        elif isinstance(op, PivotAction):
            target_angle = op.angle

            delta = abs(target_angle - state["b"])
            duration = delta / B_ROT_SPEED_DEG_PER_S if delta > 0 else 0.0

            new_state = state.copy()
            new_state["b"] = target_angle

            actions.append(PreviewAction(
                kind="pivot",
                start_time_s=t,
                end_time_s=t + duration,
                start_state=state.copy(),
                end_state=new_state.copy(),
            ))

            state = new_state
            t += duration

        # -----------------
        # CUT PATH
        # -----------------
        elif isinstance(op, CutPath):
            path = op.path

            for i in range(len(path) - 1):
                x1, y1 = path[i]
                x2, y2 = path[i + 1]

                dx = x2 - x1
                dy = y2 - y1
                dist = (dx**2 + dy**2) ** 0.5
                duration = dist / XY_FEED_MM_PER_S if dist > 0 else 0.0

                new_state = state.copy()
                new_state["x"] = x2
                new_state["y"] = y2

                actions.append(PreviewAction(
                    kind="cut",
                    start_time_s=t,
                    end_time_s=t + duration,
                    start_state=state.copy(),
                    end_state=new_state.copy(),
                ))

                state = new_state
                t += duration

    return actions