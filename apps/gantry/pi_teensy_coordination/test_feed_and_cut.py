from .teensy_controller import TeensyController
from .roller_controller import RollerController
from .coordinator import Coordinator


def main():
    teensy = TeensyController()
    rollers = RollerController()
    coord = Coordinator(teensy, rollers)

    try:
        teensy.connect()

        gcode = [
            "$X",
            "G21",
            "G90",
            "G1 X20 F600",
            "G1 X0 F600",
        ]

        coord.run_feed_then_cut(feed_mm=25, gcode=gcode)

    finally:
        teensy.disconnect()
        rollers.stop()


if __name__ == "__main__":
    main()