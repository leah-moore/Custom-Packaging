from dataclasses import dataclass, field
from typing import List, Tuple, Dict

Point = Tuple[float, float]
Polygon = List[Point]

def rect(x1, x2, y1, y2):
    return [(x1,y1),(x1,y2),(x2,y2),(x2,y1),(x1,y1)]

@dataclass
class Dieline:
    cuts: List[Polygon] = field(default_factory=list)
    creases: List[Tuple[Point, Point]] = field(default_factory=list)
    edges: list = field(default_factory=list)   # 👈 ADD THIS
    debug: Dict = field(default_factory=dict)


from Box.edges import Edge

def polygon_edges(poly):
    """
    Convert a closed polygon [(x,y), ...] into Edge objects.
    Assumes last point == first point.
    """
    return [
        Edge(a, b)
        for a, b in zip(poly, poly[1:])
    ]
