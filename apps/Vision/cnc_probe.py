#!/usr/bin/env python3
"""
Webcam diagnostics — run this first to figure out what your camera supports.
Tries every relevant property and saves test shots at different exposures.
"""

import cv2
import numpy as np
import time

DEVICE = 1  # Change if needed

props = {
    "FRAME_WIDTH":    cv2.CAP_PROP_FRAME_WIDTH,
    "FRAME_HEIGHT":   cv2.CAP_PROP_FRAME_HEIGHT,
    "FPS":            cv2.CAP_PROP_FPS,
    "EXPOSURE":       cv2.CAP_PROP_EXPOSURE,
    "AUTO_EXPOSURE":  cv2.CAP_PROP_AUTO_EXPOSURE,
    "GAIN":           cv2.CAP_PROP_GAIN,
    "BRIGHTNESS":     cv2.CAP_PROP_BRIGHTNESS,
    "CONTRAST":       cv2.CAP_PROP_CONTRAST,
    "SHARPNESS":      cv2.CAP_PROP_SHARPNESS,
    "AUTO_WB":        cv2.CAP_PROP_AUTO_WB,
    "WB_TEMP":        cv2.CAP_PROP_WB_TEMPERATURE,
}

def grab_frame(cap, settle=5):
    """Discard a few frames so the sensor settles after a settings change."""
    for _ in range(settle):
        cap.read()
    ret, frame = cap.read()
    return frame if ret else None


def mean_brightness(img):
    if img is None:
        return -1
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


# ── 1. Print current property values ─────────────────────────────────────────
print("=" * 52)
print(" Camera property read-out")
print("=" * 52)
cap = cv2.VideoCapture(DEVICE, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

for name, prop_id in props.items():
    val = cap.get(prop_id)
    print(f"  {name:<18}: {val}")

cap.release()
print()

# ── 2. Sweep AUTO_EXPOSURE values ─────────────────────────────────────────────
# Different drivers use different values to mean "manual":
#   V4L2 chipsets:  1 = manual, 3 = aperture priority (auto)
#   Some others:    0 = manual, 1 = auto
print("=" * 52)
print(" AUTO_EXPOSURE sweep (with exposure = -6)")
print("=" * 52)
for ae_val in [0, 1, 3]:
    cap = cv2.VideoCapture(DEVICE, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, ae_val)
    time.sleep(0.2)
    cap.set(cv2.CAP_PROP_EXPOSURE, -6)
    frame = grab_frame(cap, settle=10)
    brightness = mean_brightness(frame)
    accepted_ae  = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    accepted_exp = cap.get(cv2.CAP_PROP_EXPOSURE)
    print(f"  AE set={ae_val} → accepted AE={accepted_ae}, "
          f"EXP accepted={accepted_exp}, mean brightness={brightness:.1f}")
    if frame is not None:
        cv2.imwrite(f"probe_ae{ae_val}.png", frame)
        print(f"    → saved probe_ae{ae_val}.png")
    cap.release()
print()

# ── 3. Sweep exposure values (with the most common manual AE setting) ─────────
print("=" * 52)
print(" Exposure sweep (AUTO_EXPOSURE=1, manual mode)")
print("=" * 52)
exposure_values = [-13, -10, -8, -6, -4, -2, 0, 2, 50, 100, 200]
for exp in exposure_values:
    cap = cv2.VideoCapture(DEVICE, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
    time.sleep(0.2)
    cap.set(cv2.CAP_PROP_EXPOSURE, exp)
    frame = grab_frame(cap, settle=10)
    brightness = mean_brightness(frame)
    accepted = cap.get(cv2.CAP_PROP_EXPOSURE)
    print(f"  EXP set={exp:>5} → accepted={accepted:>6.1f}, "
          f"mean brightness={brightness:.1f}", end="")
    if brightness < 5:
        print("  ← too dark / blank")
    elif brightness > 250:
        print("  ← overexposed")
    else:
        print("  ← looks usable")
        if frame is not None:
            cv2.imwrite(f"probe_exp{exp}.png", frame)
            print(f"    → saved probe_exp{exp}.png")
    cap.release()

print()
print("Done. Check the saved probe_*.png files and the brightness values above.")
print("Use the exposure value that gives brightness in the 100–200 range.")