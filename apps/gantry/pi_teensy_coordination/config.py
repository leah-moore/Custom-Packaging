import platform


def running_on_pi():
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/device-tree/model", "r") as f:
            return "Raspberry Pi" in f.read()
    except Exception:
        return False


if running_on_pi():
    TEENSY_PORT = "/dev/ttyACM0"
else:
    TEENSY_PORT = "/dev/tty.usbmodem123"  # update if needed on Mac

TEENSY_BAUD = 115200

ROLLER_STEP_PIN = 17
ROLLER_DIR_PIN = 27
ROLLER_ENABLE_PIN = 22
ROLLER_STEPS_PER_MM = 10.0
DEFAULT_ROLLER_SPEED_MM_S = 10.0