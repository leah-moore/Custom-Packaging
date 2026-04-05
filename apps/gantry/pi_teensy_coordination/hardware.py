import platform


def running_on_raspberry_pi():
    try:
        # Must be Linux
        if platform.system() != "Linux":
            print("[HW] Not Linux → not Pi")
            return False

        # Check device tree (most reliable)
        with open("/proc/device-tree/model", "r") as f:
            model = f.read()
            is_pi = "Raspberry Pi" in model
            print(f"[HW] Detected model: {model.strip()}")
            print(f"[HW] running_on_raspberry_pi = {is_pi}")
            return is_pi

    except Exception as e:
        print(f"[HW] Detection failed: {e}")
        return False