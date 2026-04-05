import platform


def running_on_raspberry_pi() -> bool:
    if platform.system() != "Linux":
        return False

    try:
        with open("/proc/device-tree/model", "r") as f:
            return "Raspberry Pi" in f.read()
    except Exception:
        return False