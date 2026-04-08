# ------------------------
# Teensy (GRBL) settings
# ------------------------

TEENSY_PORT = "/dev/ttyACM0"   # Raspberry Pi
# TEENSY_PORT = "/dev/tty.usbmodem123"  # Mac (uncomment if testing locally)

TEENSY_BAUD = 115200


# ------------------------
# Roller (Stepper) GPIO
# ------------------------

# ⚠️ These are BCM (GPIO) numbers, NOT physical pin numbers

# GPIO17 → Physical pin 11
# Connect to TMC2209 STEP pin
#grey wire
ROLLER_STEP_PIN = 17 

# GPIO27 → Physical pin 13
# Connect to TMC2209 DIR pin
#white wire
ROLLER_DIR_PIN = 27

# GPIO22 → Physical pin 15
# Connect to TMC2209 EN / ENN pin (usually active-low)
#black wire
ROLLER_ENABLE_PIN = 22

# IMPORTANT:
# - You MUST connect a Raspberry Pi GND pin (e.g. pin 6) to the driver GND
# - Do NOT confuse GPIO numbers with physical pin numbers
# - Example wiring:
#     Pin 11 → STEP
#     Pin 13 → DIR
#     Pin 15 → EN
#     Pin 6  → GND


# ------------------------
# Roller Motion Settings
# ------------------------

# 28 mm direct-drive roller, NEMA 17 (1.8 deg), TMC2209 assumed 16 microsteps
ROLLER_STEPS_PER_MM = 36.4

# Default speed (mm/s)
DEFAULT_ROLLER_SPEED_MM_S = 8.0