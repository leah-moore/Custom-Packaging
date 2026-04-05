from .teensy_controller import TeensyController
from .roller_controller import RollerController
from .coordinator import Coordinator


def main():
    teensy = TeensyController()
    rollers = RollerController()
    coord = Coordinator(teensy, rollers)

    teensy.connect()

    gcode = [
        "$X",
        "G21",
        "G90",
        "G1 X50 F1000",
        "G1 X0 F1000",
    ]

    coord.run_feed_then_cut(50, gcode)

    teensy.disconnect()


if __name__ == "__main__":
    main()