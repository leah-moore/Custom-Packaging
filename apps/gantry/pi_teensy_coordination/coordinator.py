from .config import DEFAULT_ROLLER_SPEED_MM_S


class Coordinator:
    def __init__(self, teensy, rollers):
        self.teensy = teensy
        self.rollers = rollers

    def run_feed_then_cut(self, feed_mm, gcode, roller_speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S):
        print("[COORD] Feeding rollers...")
        self.rollers.feed_distance(feed_mm, speed_mm_s=roller_speed_mm_s)

        print("[COORD] Running gantry...")
        self.teensy.stream(gcode)

        print("[COORD] Done")