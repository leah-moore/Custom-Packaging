# ===== User Variables =====
diameter = 8          # circle diameter (mm)
square_size = 5      # square side length (mm)
feedrate = 20         # mm/min

circle_filename = "circleAGAINmeow.nc"
square_filename = "square.nc"
# ===========================


# ---------- CIRCLE ----------
radius = diameter / 2

circle_gcode = f"""
M3
G21
G17
G90
G0 X{radius} Y0
G2 X{radius} Y0 I-{radius} J0 F{feedrate}
M5
M2
"""

with open(circle_filename, "w") as f:
    f.write(circle_gcode)

print(f"Created {circle_filename} with diameter {diameter}mm")


# ---------- SQUARE ----------
s = square_size

square_gcode = f"""
M3
G21
G17
G90

G0 X0 Y0
G1 X{s} Y0 F{feedrate}
G1 X{s} Y{s}
G1 X0 Y{s}
G1 X0 Y0

M5
M2
"""

with open(square_filename, "w") as f:
    f.write(square_gcode)

print(f"Created {square_filename} with side {square_size}mm")