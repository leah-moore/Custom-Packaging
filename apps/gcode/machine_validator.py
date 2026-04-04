from typing import List
from gcode.machine_ops_types import (
    Operation, RapidMove, ToolDown, ToolUp,
    CutPath, FeedAdvance
)

def validate_operations(ops: List[Operation]) -> None:
    tool_down = False

    for i, op in enumerate(ops):

        if isinstance(op, ToolDown):
            if tool_down:
                raise ValueError(f"Tool already down at op {i}")
            tool_down = True

        elif isinstance(op, ToolUp):
            if not tool_down:
                raise ValueError(f"Tool already up at op {i}")
            tool_down = False

        elif isinstance(op, RapidMove):
            if tool_down:
                raise ValueError(f"Rapid move while tool down at op {i}")

        elif isinstance(op, FeedAdvance):
            if tool_down:
                raise ValueError(f"Feed advance while tool down at op {i}")

        elif isinstance(op, CutPath):
            if not tool_down:
                raise ValueError(f"CutPath while tool up at op {i}")
            if not op.path:
                raise ValueError(f"Empty CutPath at op {i}")

    if tool_down:
        raise ValueError("Program ends with tool still down")
