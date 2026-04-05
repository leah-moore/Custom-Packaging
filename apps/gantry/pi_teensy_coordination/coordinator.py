class Coordinator:
    def __init__(self, teensy, rollers):
        self.teensy = teensy
        self.rollers = rollers

    def run_feed_then_cut(self, feed_mm, gcode):
        print("[COORD] Feeding rollers...")
        self.rollers.feed_distance(feed_mm)

        print("[COORD] Running gantry...")
        self.teensy.stream(gcode)

        print("[COORD] Done")