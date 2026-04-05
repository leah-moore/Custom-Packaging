# ------------------------
# Teensy (GRBL) settings
# ------------------------

TEENSY_PORT = "/dev/ttyACM0"   # Raspberry Pi
# TEENSY_PORT = "/dev/tty.usbmodem123"  # Mac (uncomment if testing locally)

TEENSY_BAUD = 115200


# ------------------------
# Roller (Stepper) GPIO
# ------------------------

# BCM pin numbers
ROLLER_STEP_PIN = 17
ROLLER_DIR_PIN = 27
ROLLER_ENABLE_PIN = 22


# ------------------------
# Roller Motion Settings
# ------------------------

# Steps per mm of material feed
# (depends on motor steps/rev, microstepping, roller diameter)
ROLLER_STEPS_PER_MM = 10.0

# Default speed (mm/s)
DEFAULT_ROLLER_SPEED_MM_S = 10.0