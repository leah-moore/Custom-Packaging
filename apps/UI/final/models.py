from dataclasses import dataclass
from typing import Tuple


@dataclass
class GCodeSegment:
    """
    Represents one motion segment in G-code.
    """

    start: Tuple[float, float, float, float, float, float]
    end: Tuple[float, float, float, float, float, float]
    motion_type: str  # G0, G1, G2, G3
    line_num: int