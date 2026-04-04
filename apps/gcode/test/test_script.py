import sys
import os
import math
import re

# --- PATH SETUP ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from gcode.machine_ops_types import (
    RapidMove, ToolDown, ToolUp, CutPath, FeedAdvance, PivotAction
)
from gcode.emit_gcode import emit_gcode
from gcode.test.visualize_ops import visualize_operations

"""
--- COMMAND CHEAT SHEET ---
FEED [dist]                    -> Rollers (Axis A) move material forward.
MOVE [x] [y]                   -> Gantry (X, Y) moves with both tools lifted (Z=0).
CUT [x1] [y1] [x2] [y2]        -> Knife engages (Z-), starts oscillation (M3), pivots (B).
CREASE [x1] [y1] [x2] [y2]     -> Wheel engages (Z+), pivots (C).
CIRCLE [cx] [cy] [diam] [tool] -> Center X, Center Y, Diameter.
SQUARE [cx] [cy] [s] [tool]    -> Center X, Center Y, Side Length.
RECT [cx] [cy] [w] [h] [tool]  -> Center X, Center Y, Width, Height.
"""

# --- HARDWARE CALIBRATION ---
TOOL_X_OFFSET = 5.0
TOOL_Y_OFFSET = 45.0

# --- JOB NAME FOR OUTPUT FILES ---
JOB_NAME = "gantry_routine"

def sanitize_filename(text: str) -> str:
    text = text.strip().lower().replace(" ", "_")
    text = re.sub(r"[^a-z0-9._-]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")

def write_job_dxf(entities, out_path):
    lines = [
        "0", "SECTION", "2", "HEADER", "0", "ENDSEC",
        "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "2",
        "0", "LAYER", "2", "CUT", "70", "0", "62", "7", "6", "CONTINUOUS",
        "0", "LAYER", "2", "CREASE", "70", "0", "62", "3", "6", "CONTINUOUS",
        "0", "ENDTAB", "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
    ]

    for entity in entities:
        path = entity["path"]
        layer = entity["layer"]
        closed = len(path) > 2 and path[0] == path[-1]
        flag = 1 if closed else 0

        lines.extend(["0", "LWPOLYLINE", "8", layer, "90", str(len(path)), "70", str(flag)])
        for x, y in path:
            lines.extend(["10", f"{x}", "20", f"{y}"])

    lines.extend(["0", "ENDSEC", "0", "EOF"])
    with open(out_path, "w", newline="\n") as f:
        f.write("\n".join(lines))

def run_job():
    # --- DESIGN COMMANDS ---
    commands = [
        #"CIRCLE 0 0 50 knife",
        "SQUARE 0 0 100 knife",
        # Example of a crease that will now line up perfectly in DXF:
        # "SQUARE 0 0 40 crease" 
    ]

    ops = []
    dxf_entities = []
    y_offset = 0.0

    for line in commands:
        p = line.split()
        if not p:
            continue
        cmd = p[0].upper()

        if cmd == "FEED":
            dist = float(p[1])
            y_offset += dist
            ops.append(FeedAdvance(distance=dist))

        elif cmd == "MOVE":
            x, y = float(p[1]), float(p[2])
            ops.append(RapidMove(to=(x, y)))

        elif cmd in ["CUT", "CREASE", "SQUARE", "CIRCLE", "RECT"]:
            # Identify tool
            tool = p[-1].lower() if cmd in ["SQUARE", "CIRCLE", "RECT"] else (
                "crease" if cmd == "CREASE" else "knife"
            )

            # --- 1. GENERATE DESIGN PATH (Dimensionally Correct for DXF) ---
            design_path = []
            cx = float(p[1])
            cy = float(p[2])

            if cmd in ["CUT", "CREASE"]:
                design_path = [(float(p[1]), float(p[2])), (float(p[3]), float(p[4]))]

            elif cmd == "CIRCLE":
                r = float(p[3]) / 2.0
                segments = 64
                step_deg = 360.0 / segments
                design_path = [
                    (cx + r * math.cos(math.radians(-i * step_deg)),
                     cy + r * math.sin(math.radians(-i * step_deg)))
                    for i in range(segments + 1)
                ]

            elif cmd in ["SQUARE", "RECT"]:
                w = float(p[3])
                # Check if p[4] is a number (height) or the tool name
                try:
                    h = float(p[4]) if cmd == "RECT" else w
                except ValueError:
                    h = w # Fallback for SQUARE or malformed RECT
                
                w_half, h_half = w / 2.0, h / 2.0
                design_path = [
                    (cx - w_half, cy - h_half),
                    (cx - w_half, cy + h_half),
                    (cx + w_half, cy + h_half),
                    (cx + w_half, cy - h_half),
                    (cx - w_half, cy - h_half),
                ]

            # --- 2. ADD TO DXF (Pure Geometry) ---
            dxf_entities.append({
                "layer": "CREASE" if tool == "crease" else "CUT",
                "path": design_path,
            })

            # --- 3. APPLY OFFSETS FOR MACHINE OPS (G-Code ONLY) ---
            off_x = TOOL_X_OFFSET if tool == "crease" else 0.0
            off_y = TOOL_Y_OFFSET if tool == "crease" else 0.0
            
            machine_path = [(x + off_x, y + off_y) for x, y in design_path]

            entry_angle = math.degrees(math.atan2(
                machine_path[1][1] - machine_path[0][1],
                machine_path[1][0] - machine_path[0][0]
            ))

            ops.append(RapidMove(to=machine_path[0]))
            ops.append(PivotAction(tool=tool, angle=entry_angle))
            ops.append(ToolDown(tool=tool))
            ops.append(CutPath(path=machine_path))
            ops.append(ToolUp())

    # --- EXPORT & VISUALIZE ---
    visualize_operations(ops)
    gcode_content = emit_gcode(ops)

    final_gcode = f"M8\nG4 P1\n{gcode_content}\nM9\nM2"
    
    output_dir = os.path.join(os.path.dirname(current_dir), "output")
    os.makedirs(output_dir, exist_ok=True)

    gcode_path = os.path.join(output_dir, f"{sanitize_filename(JOB_NAME)}.nc")
    dxf_path = os.path.join(output_dir, f"{sanitize_filename(JOB_NAME)}.dxf")

    with open(gcode_path, "w") as f: f.write(final_gcode)
    write_job_dxf(dxf_entities, dxf_path)

    print(f"\n--- SUCCESS ---\nG-code: {gcode_path}\nDXF: {dxf_path}")

if __name__ == "__main__":
    run_job()