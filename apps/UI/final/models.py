from dataclasses import dataclass
from typing import Tuple


@dataclass
class GCodeSegment:
    start: Tuple[float, float, float, float, float, float]
    end: Tuple[float, float, float, float, float, float]
    motion_type: str
    line_num: int

    feed_rate: float = 1000.0
    spindle_on: bool = False
    spindle_speed: float = 0.0

    distance_mm: float = 0.0
    duration_s: float = 0.0
    start_time_s: float = 0.0
    end_time_s: float = 0.0

    is_dwell: bool = False
    dwell_s: float = 0.0