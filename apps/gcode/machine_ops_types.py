from dataclasses import dataclass
from typing import List, Tuple, Literal

# --- TYPE DEFINITIONS ---
Point = Tuple[float, float]

# ToolType maps to your See-Saw + Tangential Axis:
# "knife"  -> Axis C Pivot + Z Negative + M3 Spindle
# "crease" -> Axis B Pivot + Z Positive
ToolType = Literal["knife", "crease"]

@dataclass
class Operation:
    """Base class for all G-code generating operations."""
    pass

@dataclass
class RapidMove(Operation):
    """G0 move with tools retracted (Z=0)."""
    to: Point

@dataclass
class ToolDown(Operation):
    """Engages the specified tool via the See-Saw Z-axis."""
    tool: ToolType

@dataclass
class ToolUp(Operation):
    """Retracts tool to Z=0 (Neutral)."""
    pass

@dataclass
class CutPath(Operation):
    """
    Sequence of lines. The Emitter will calculate the 
    required B/C angles for tangential tracking.
    """
    path: List[Point]

@dataclass
class FeedAdvance(Operation):
    """Moves the Axis-A rollers to pull cardboard."""
    distance: float

@dataclass
class PivotAction(Operation):
    """
    Explicitly rotates the B (Creaser) or C (Knife) axis.
    Used for 'Dry Pivots' while the tool is in the air.
    """
    tool: ToolType
    angle: float

@dataclass
class SetLights(Operation):
    """
    Controls the Gantry Lights. 
    Mapped to M8 (Flood ON) and M9 (Flood OFF).
    """
    state: bool  # True = M8, False = M9