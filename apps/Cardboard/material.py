from dataclasses import dataclass

@dataclass
class Material:
    thickness: float

@dataclass
class Tooling:
    score_width: float = 2.5
    score_to_cut: float = 1.5
    knife_width: float = 0.5
    bleed: float = 3.0

    @property
    def EX(self):
        return self.score_width / 2 + self.score_to_cut


def thickness_compensation(T):
    # placeholder for flute logic
    return dict(panel_gain=T)
