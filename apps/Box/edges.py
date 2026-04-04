# edges.py
from math import hypot
from collections import defaultdict


class Edge:
    def __init__(self, p1, p2, tol=1e-6):
        self.p1 = p1
        self.p2 = p2
        self.tol = tol

        self.horizontal = abs(p1[1] - p2[1]) < tol
        self.vertical   = abs(p1[0] - p2[0]) < tol

        # normalize direction
        if self.horizontal and p1[0] > p2[0]:
            self.p1, self.p2 = p2, p1
        if self.vertical and p1[1] > p2[1]:
            self.p1, self.p2 = p2, p1

    def key(self):
        return (
            round(self.p1[0], 6), round(self.p1[1], 6),
            round(self.p2[0], 6), round(self.p2[1], 6)
        )

    def length(self):
        return hypot(self.p2[0] - self.p1[0],
                     self.p2[1] - self.p1[1])


def classify_edges(edges):
    """
    Separate edges into:
      - knife edges (appear once)
      - shared edges (appear multiple times)
    """
    counts = defaultdict(int)
    lookup = {}

    for e in edges:
        k = e.key()
        counts[k] += 1
        lookup[k] = e

    knife = []
    shared = []

    for k, n in counts.items():
        if n == 1:
            knife.append(lookup[k])
        else:
            shared.append(lookup[k])

    return knife, shared
