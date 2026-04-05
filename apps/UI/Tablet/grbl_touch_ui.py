"""
Enhanced grblHAL Touch UI
Full integration: Serial control + G-code + Vision + DXF die-lines + Slats + 3D Preview

Features:
- Manual jogging with validated input
- G-code file loading, viewing, and 3D preview
- 2D toolpath preview
- Vision image loading and stitching placeholder
- DXF die-line loading, visualization, and placement (manual + auto)
- Mesh loading and slat generation
- 3D visualization of cuts and tool paths
- Cross-platform (Windows/Mac/Linux/Raspberry Pi)

Dependencies:
- tkinter (built-in)
- serial, numpy, trimesh, matplotlib, shapely
- ezdxf (optional, for DXF support)
- opencv-python (optional, for vision stitching)
"""

import os
import sys
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)

FILE_PATH = Path(__file__).resolve()
APPS_DIR = FILE_PATH.parents[2]
PROJECT_ROOT = APPS_DIR.parent

sys.path.insert(0, str(APPS_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from matplotlib import pyplot as plt
import numpy as np
import serial
import serial.tools.list_ports
import trimesh

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from shapely.geometry import Polygon
from shapely.ops import unary_union

from gantry.pi_teensy_coordination.roller_controller import RollerController

# Import our custom modules
try:
    from dxf_handler import DXFDieline, VisionDXFAligner
    HAS_DXF_HANDLER = True
except ImportError:
    HAS_DXF_HANDLER = False
    print("Warning: dxf_handler module not found. DXF features will be limited.")

try:
    from Filler.grid_slats import compute_worldgrid_from_stl
    HAS_SLATS = True
except ImportError:
    HAS_SLATS = False
    print("Warning: Filler.grid_slats module not found. Slats features will be limited.")


# ---------------------------
# HMI Theme
# ---------------------------
BG = "#1E1E1E"
PANEL_BG = "#2A2A2A"
FG = "#F5F5F5"

ENTRY_BG = "#F2F2F2"
ENTRY_FG = "#111111"

CONSOLE_BG = "#111111"
CONSOLE_FG = "#F5F5F5"

BTN_NEUTRAL = "#D9D9D9"
BTN_NEUTRAL_FG = "#111111"
BTN_BLUE = "#4EA1FF"
BTN_BLUE_FG = "#111111"
BTN_GREEN = "#5FD16F"
BTN_GREEN_FG = "#111111"
BTN_YELLOW = "#FFD54A"
BTN_YELLOW_FG = "#111111"
BTN_ORANGE = "#FFB347"
BTN_ORANGE_FG = "#111111"
BTN_RED = "#FF6B6B"
BTN_RED_FG = "#111111"

BTN_PRESSED = "#666666"


# ---------------------------
# Machine Commands
# ---------------------------
LIGHT_ON_CMD = "M8"
LIGHT_OFF_CMD = "M9"
SPINDLE_OFF_CMD = "M5"
DEFAULT_SPINDLE_SPEED = "12000"


# ---------------------------
# Data Classes
# ---------------------------
@dataclass
class JogSettings:
    """Validated jog parameters"""
    step: float
    feed: float
    
    def validate(self) -> bool:
        return self.step > 0 and self.feed > 0


@dataclass
class GCodeSegment:
    """Parsed G-code segment for 3D preview"""
    start: Tuple[float, float, float, float, float, float]
    end: Tuple[float, float, float, float, float, float]
    motion_type: str
    line_num: int


# ---------------------------
# Serial Controller
# ---------------------------
class GrblHALController:
    """Thread-safe GRBL controller"""
    
    def __init__(self):
        self.ser = None
        self.read_thread = None
        self.read_running = False
        self.rx_queue = queue.Queue(maxsize=500)
        self.lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self, port: str, baudrate: int = 115200, timeout: float = 0.1) -> None:
        self.disconnect()
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(2.0)
        self.read_running = True
        self.read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.read_thread.start()
        time.sleep(0.5)  # Let reader thread start first
        self.write_raw("\r\n\r\n")
        time.sleep(0.5)  # Longer wait
        self.send_realtime(b'\x18')  # Soft reset
        time.sleep(0.3)
        self.flush_input()

    def disconnect(self) -> None:
        self.read_running = False
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=0.5)
        self.read_thread = None
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def flush_input(self) -> None:
        if self.is_connected:
            with self.lock:
                self.ser.reset_input_buffer()

    def write_line(self, line: str) -> None:
        if not self.is_connected:
            print(f"[ERROR] Not connected - dropped: {line.strip()}")
            return
        if not line.endswith("\n"):
            line += "\n"
        with self.lock:
            try:
                self.ser.write(line.encode("ascii", errors="ignore"))
                print(f"[SENT] {line.strip()}")  # DEBUG
            except Exception as e:
                print(f"[ERROR] Send failed: {e}")

    def write_raw(self, text: str) -> None:
        if not self.is_connected:
            return
        with self.lock:
            try:
                self.ser.write(text.encode("ascii", errors="ignore"))
            except Exception:
                pass

    def send_realtime(self, cmd: bytes) -> None:
        if not self.is_connected:
            return
        with self.lock:
            try:
                self.ser.write(cmd)
            except Exception:
                pass

    def get_rx_lines(self) -> List[str]:
        lines = []
        while True:
            try:
                lines.append(self.rx_queue.get_nowait())
            except queue.Empty:
                break
        return lines

    def _reader_loop(self) -> None:
        while self.read_running and self.is_connected:
            try:
                line = self.ser.readline()
                if line:
                    text = line.decode(errors="replace").strip()
                    if text:
                        print(f"[RX] {text}")  # DEBUG
                        try:
                            self.rx_queue.put_nowait(text)
                        except queue.Full:
                            print(f"[WARNING] Queue full, dropped: {text}")
            except Exception as e:
                print(f"[READER ERROR] {e}")  # DEBUG
                break


# ---------------------------
# G-code Parser
# ---------------------------
class GCodeParser:
    """Fast G-code parser"""
    
    @staticmethod
    def parse_lines(lines: List[str]) -> Tuple[List[GCodeSegment], Dict]:
        segments = []
        state = {
            "x": 0.0, "y": 0.0, "z": 0.0,
            "a": 0.0, "b": 0.0, "c": 0.0,
            "absolute": True,
            "motion": "G1",
        }
        bounds = {"min": [float('inf')] * 6, "max": [float('-inf')] * 6}
        
        for line_num, raw in enumerate(lines, 1):
            line = raw.upper().strip()
            
            if "(" in line:
                line = line[:line.find("(")]
            if ";" in line:
                line = line[:line.find(";")]
            
            line = line.strip()
            if not line:
                continue
            
            words = line.split()
            old_state = state.copy()
            
            for w in words:
                if w == "G90":
                    state["absolute"] = True
                elif w == "G91":
                    state["absolute"] = False
                elif w in ("G0", "G00"):
                    state["motion"] = "G0"
                elif w in ("G1", "G01"):
                    state["motion"] = "G1"
                elif w in ("G2", "G02"):
                    state["motion"] = "G2"
                elif w in ("G3", "G03"):
                    state["motion"] = "G3"
            
            coords = {}
            for w in words:
                if len(w) < 2:
                    continue
                axis = w[0]
                if axis not in "XYZABC":
                    continue
                try:
                    val = float(w[1:])
                    coords[axis] = val
                except ValueError:
                    continue
            
            if coords:
                for axis in "XYZABC":
                    if axis in coords:
                        if state["absolute"]:
                            state[axis.lower()] = coords[axis]
                        else:
                            state[axis.lower()] += coords[axis]
                
                start = tuple(old_state[a] for a in "xyzabc")
                end = tuple(state[a] for a in "xyzabc")
                
                segments.append(GCodeSegment(
                    start=start,
                    end=end,
                    motion_type=state["motion"],
                    line_num=line_num
                ))
                
                for i, (v_start, v_end) in enumerate(zip(start, end)):
                    bounds["min"][i] = min(bounds["min"][i], v_start, v_end)
                    bounds["max"][i] = max(bounds["max"][i], v_start, v_end)
        
        return segments, bounds


# ---------------------------
# Main UI
# ---------------------------
class TouchUI(tk.Tk):
    POLL_MS = 200
    RX_PROCESS_MS = 50
    JOG_REPEAT_S = 0.12
    GCODE_ACK_TIMEOUT_S = 8.0
    MAX_PLOT_FACES = 80000

    def __init__(self):
        super().__init__()
        self.title("grblHAL Touch UI — Complete [1024x600]")
        self.geometry("1024x600")
        self.minsize(1024, 600)
        self.configure(bg=BG)

        self.ctrl = GrblHALController()
        
        # Initialize rollers with error handling
        try:
            self.rollers = RollerController()
            print("[INIT] ✓ RollerController initialized")
        except Exception as e:
            print(f"[INIT] ✗ RollerController failed: {e}")
            self.rollers = None
        
        self.roller_jogging = False
        self.roller_jog_thread = None

        # Machine state
        self.machine_state = "Disconnected"
        self.polling = False
        self.homed = False
        self.in_alarm = False
        self.waiting_for_ack = False
        self.last_controller_reply = None

        # Jogging
        self.jogging = False
        self.jog_thread = None

        # G-code job
        self.gcode_lines = []
        self.gcode_segments = []
        self.gcode_bounds = {}
        self.current_line_index = 0
        self.job_running = False
        self.job_paused = False
        self.job_stopping = False
        self.job_thread = None
        self.current_tool_pos = [0.0, 0.0, 0.0]  # Current tool XYZ position

        # Previews
        self.preview_canvas = None
        self.preview_info_text = tk.StringVar(value="No preview loaded")
        self.preview_3d_rotation = True  # Auto-rotation flag
        self.preview_3d_azim = 45  # Current azimuth angle
        self.preview_3d_animation_id = None  # Animation timer ID
        self.preview_scrub_index = 0  # For timeline scrubber (0 = start, 1.0 = end)
        
        # Playback control
        self.preview_is_playing = False
        self.preview_playback_speed = 1.0  # Speed multiplier
        self.preview_estimated_time = 0.0  # Total job time in seconds
        self.preview_animation_id = None

        # Vision
        self.vision_images = []
        self.vision_info_text = tk.StringVar(value="No vision images loaded")
        self.vision_canvas = None

        # DXF
        self.dxf_dieline = None
        self.dxf_file_path = None  # Store path for drawing
        self.dxf_info_text = tk.StringVar(value="No DXF loaded")
        self.dxf_canvas = None

        # Mesh & Slats
        self.scan_mesh_path = None
        self.raw_mesh = None
        self.slats_data = None
        self.mesh_info_text = tk.StringVar(value="No mesh loaded")
        self.mesh_azim = 35  # Mesh view azimuth
        self.mesh_elev = 20  # Mesh view elevation
        self.slats_info_text = tk.StringVar(value="No slat grid generated")
        self.slats_2d_zoom_level = 1.0  # Zoom state for 2D slats view

        # Status vars
        self.status_text = tk.StringVar(value="Disconnected")
        self.state_text = tk.StringVar(value="State: --")
        self.machine_pos_text = tk.StringVar(value="MPos: --")
        self.work_pos_text = tk.StringVar(value="WPos: --")
        self.job_progress_text = tk.StringVar(value="Job: idle")
        self.file_text = tk.StringVar(value="No file loaded")
        self.last_status_text = tk.StringVar(value="Last status: --")

        # Individual axis position variables (for Manual+Setup tab display)
        self.machine_pos_x_text = tk.StringVar(value="--")
        self.machine_pos_y_text = tk.StringVar(value="--")
        self.machine_pos_z_text = tk.StringVar(value="--")
        self.machine_pos_a_text = tk.StringVar(value="--")
        self.machine_pos_b_text = tk.StringVar(value="--")
        self.machine_pos_c_text = tk.StringVar(value="--")

        # UI vars
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")

        self.jog_step_var = tk.StringVar(value="1.0")
        self.jog_feed_var = tk.StringVar(value="1000")

        self.a_rot_step_var = tk.StringVar(value="5.0")
        self.a_rot_feed_var = tk.StringVar(value="300")
        self.b_rot_step_var = tk.StringVar(value="5.0")
        self.b_rot_feed_var = tk.StringVar(value="300")
        self.c_rot_step_var = tk.StringVar(value="5.0")
        self.c_rot_feed_var = tk.StringVar(value="300")

        self.mdi_var = tk.StringVar()
        self.spindle_speed_var = tk.StringVar(value=DEFAULT_SPINDLE_SPEED)
        self.spindle_oscillation_rpm_var = tk.StringVar(value="2000")

        self.n_xy_var = tk.StringVar(value="5")
        self.n_xz_var = tk.StringVar(value="5")
        self.show_mesh_in_slats_var = tk.BooleanVar(value=True)

        # Slats CAM workflow state
        self.slats_cam_stl_file = None
        self.slats_cam_raw_slats = []
        self.slats_cam_laid_out_slats = []
        self.slats_cam_toolpaths = {}
        self.slats_cam_gcode_path = None
        self.slats_cam_stage = "idle"
        
        self.slat_workspace_offsets = {} 
        self.selected_slat_idx = None
        self._drag_start_pos = (0, 0)

        # UI state
        self.slats_cam_stl_path_var = tk.StringVar(value="(no file selected)")
        self.slats_cam_status_var = tk.StringVar(value="Ready")
        self.slats_cam_slats_info_var = tk.StringVar(value="No slats loaded")
        self.slats_cam_n_xy_var = tk.StringVar(value="5")
        self.slats_cam_n_xz_var = tk.StringVar(value="5")
        
        # Config variables for Slats CAM
        self.slats_cam_gantry_vars = {}
        self.slats_cam_machine_vars = {}
        self.dxf_tx_var = tk.StringVar(value="0.0")
        self.dxf_ty_var = tk.StringVar(value="0.0")
        self.dxf_rot_var = tk.StringVar(value="0.0")
        self.dxf_scale_var = tk.StringVar(value="1.0")
        
        # DXF canvas view state
        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0
        self.dxf_canvas_pan_y = 0

        # Slats CAM Packing Workspace
        self.slats_cam_dxf_packing = None
        self.slats_cam_packed_slats = []
        self.slats_cam_packing_dxf_bounds = None

        # Matplotlib figures
        self.mesh_figure = None
        self.mesh_ax = None
        self.mesh_canvas = None

        self.slats_3d_figure = None
        self.slats_3d_ax = None
        self.slats_3d_canvas = None

        self.slats_2d_figure = None
        self.slats_2d_canvas = None

        self.gcode_3d_figure = None
        self.gcode_3d_ax = None
        self.gcode_3d_canvas = None

        self._build_ui()
        self._refresh_ports()
        
        self.after(self.RX_PROCESS_MS, self._process_rx)
        self.after(self.POLL_MS, self._status_poll_loop)

    # ===== UI BUILD =====
    def _build_ui(self) -> None:
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel", font=default_font, background=BG, foreground=FG)
        style.configure("TButton", font=default_font, padding=3)
        style.configure("TEntry", font=default_font, fieldbackground=ENTRY_BG, foreground=ENTRY_FG)
        style.configure("TCombobox", font=default_font, fieldbackground=ENTRY_BG, background=ENTRY_BG, foreground=ENTRY_FG)
        style.configure("TCheckbutton", background=BG, foreground=FG, font=default_font)

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(6, 1), font=default_font)
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL_BG), ("!selected", BTN_NEUTRAL)],
            foreground=[("selected", FG), ("!selected", "#111111")]
        )

        self._build_header()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=0, pady=0)

        # Create tabs (9 tabs: Manual+Setup, Run, Preview, G-code, Vision+DXF, Mesh, Slats, Slats CAM, Diagnostics)
        tabs = {
            "Manual + Setup": self._build_manual_setup_tab,
            "Run": self._build_run_tab,
            "Preview": self._build_unified_preview_tab,
            "G-code Viewer": self._build_gcode_viewer_tab,
            "Vision + DXF": self._build_vision_dxf_tab,
            "Mesh": self._build_mesh_tab,
            "Slats": self._build_slats_tab,
            "Slats CAM": self._build_slats_cam_tab,
            "Diagnostics": self._build_diagnostics_tab,
        }

        self.tab_frames = {}
        for name, builder in tabs.items():
            frame = tk.Frame(self.notebook, bg=BG)
            self.tab_frames[name] = frame
            self.notebook.add(frame, text=name)
            builder(frame)

    def _build_header(self) -> None:
        """Build top connection bar"""
        default_font = ("Arial", 12, "bold")
        big_font = ("Arial", 18, "bold")

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=0, pady=0)

        # LEFT SIDE: Port controls
        left_frame = tk.Frame(top, bg=BG)
        left_frame.pack(side="left", fill="x", expand=True)

        tk.Label(left_frame, text="Port", bg=BG, fg=FG, font=default_font).pack(side="left", padx=5)
        self.port_combo = ttk.Combobox(left_frame, textvariable=self.port_var, width=20, state="readonly")
        self.port_combo.pack(side="left", padx=5)

        tk.Button(
            left_frame, text="Refresh", command=self._refresh_ports,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=8, bd=2, relief="raised"
        ).pack(side="left", padx=5)

        tk.Label(left_frame, text="Baud", bg=BG, fg=FG, font=default_font).pack(side="left", padx=5)
        ttk.Entry(left_frame, textvariable=self.baud_var, width=9).pack(side="left", padx=5)

        tk.Button(
            left_frame, text="Connect", command=self._connect,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=8, bd=2, relief="raised"
        ).pack(side="left", padx=5)

        tk.Button(
            left_frame, text="Disconnect", command=self._disconnect,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=9, bd=2, relief="raised"
        ).pack(side="left", padx=5)

        # RIGHT SIDE: Status info
        right_frame = tk.Frame(top, bg=BG)
        right_frame.pack(side="right", fill="x", padx=(20, 0))

        tk.Label(right_frame, textvariable=self.status_text, bg=BG, fg=FG,
                 font=big_font).pack(anchor="w")
        tk.Label(right_frame, textvariable=self.state_text, bg=BG, fg=FG,
                 font=default_font).pack(anchor="w")
        tk.Label(right_frame, textvariable=self.job_progress_text, bg=BG, fg=BTN_GREEN,
                 font=default_font).pack(anchor="w")

    def _build_manual_setup_tab(self, parent) -> None:
        """Jog tab"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        button_font = ("Arial", 18, "bold")

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # TOP SECTION: Left sidebar + Center content (side by side)
        top_section = tk.Frame(main, bg=BG)
        top_section.pack(fill="both", expand=True, pady=(0, 2))

        left = tk.Frame(top_section, bg=BG, width=340)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        center = tk.Frame(top_section, bg=BG)
        center.pack(side="left", fill="both", expand=True)

        # BOTTOM SECTION: Home Axis (full width)
        home_section = tk.Frame(main, bg=BG)
        home_section.pack(fill="x", pady=(2, 0))

        # Merged Jog Settings
        settings_box = tk.LabelFrame(left, text="Jog Settings", bg=PANEL_BG, fg=FG,
                                     font=("Arial", 9, "bold"), padx=2, pady=1, bd=2, relief="solid")
        settings_box.pack(fill="x", pady=(16, 6))

        # Feed Distance (mm) - Radio buttons
        tk.Label(settings_box, text="Feed Distance (mm)", bg=PANEL_BG, fg=FG, font=("Arial", 8, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(4, 2))
        
        feed_distance_frame = tk.Frame(settings_box, bg=PANEL_BG)
        feed_distance_frame.grid(row=1, column=0, columnspan=4, sticky="w", padx=(20, 0), pady=(0, 6))
        
        for i, val in enumerate(["0.1", "1", "10", "20"]):
            tk.Radiobutton(
                feed_distance_frame, text=val, variable=self.jog_step_var, value=val,
                bg=PANEL_BG, fg=FG, selectcolor=BTN_BLUE, font=("Arial", 8, "bold")
            ).pack(side="left", padx=8)
        self.jog_step_var.set("1")  # Default

        # Feed Rate (mm/min) - Radio buttons
        tk.Label(settings_box, text="Feed Rate (mm/min)", bg=PANEL_BG, fg=FG, font=("Arial", 8, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 2))
        
        feed_rate_frame = tk.Frame(settings_box, bg=PANEL_BG)
        feed_rate_frame.grid(row=3, column=0, columnspan=4, sticky="w", padx=(20, 0), pady=(0, 6))
        
        for i, val in enumerate(["100", "500", "1000", "2000"]):
            tk.Radiobutton(
                feed_rate_frame, text=val, variable=self.jog_feed_var, value=val,
                bg=PANEL_BG, fg=FG, selectcolor=BTN_BLUE, font=("Arial", 8, "bold")
            ).pack(side="left", padx=8)
        self.jog_feed_var.set("1000")  # Default

        # Feed Angle (deg) - Radio buttons
        tk.Label(settings_box, text="Feed Angle (deg)", bg=PANEL_BG, fg=FG, font=("Arial", 8, "bold")).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 2))
        
        feed_angle_frame = tk.Frame(settings_box, bg=PANEL_BG)
        feed_angle_frame.grid(row=5, column=0, columnspan=4, sticky="w", padx=(20, 0), pady=(0, 6))
        
        for i, val in enumerate(["1", "5", "10", "45"]):
            tk.Radiobutton(
                feed_angle_frame, text=val, variable=self.a_rot_step_var, value=val,
                bg=PANEL_BG, fg=FG, selectcolor=BTN_BLUE, font=("Arial", 8, "bold")
            ).pack(side="left", padx=8)
        self.a_rot_step_var.set("5")  # Default

        # Spindle Oscillation RPM - Radio buttons
        tk.Label(settings_box, text="Spindle Oscillation (RPM)", bg=PANEL_BG, fg=FG, font=("Arial", 8, "bold")).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 2))
        
        spindle_osc_frame = tk.Frame(settings_box, bg=PANEL_BG)
        spindle_osc_frame.grid(row=7, column=0, columnspan=4, sticky="w", padx=(20, 0), pady=(0, 4))
        
        for i, val in enumerate(["1000", "2000", "3000", "4000"]):
            tk.Radiobutton(
                spindle_osc_frame, text=val, variable=self.spindle_oscillation_rpm_var, value=val,
                bg=PANEL_BG, fg=FG, selectcolor=BTN_BLUE, font=("Arial", 8, "bold")
            ).pack(side="left", padx=8)
        self.spindle_oscillation_rpm_var.set("2000")  # Default

        # ===== MACHINE CONTROL =====
        ctrl_box = tk.LabelFrame(left, text="Machine Control", bg=PANEL_BG, fg=FG,
                                 font=("Arial", 9, "bold"), padx=2, pady=1, bd=2, relief="solid")
        ctrl_box.pack(fill="x", pady=(0, 6))

        machine_buttons = [
            ("Home", self._home, BTN_BLUE, BTN_BLUE_FG),
            ("Unlock", self._unlock, BTN_YELLOW, BTN_YELLOW_FG),
            ("Hold", self._hold, BTN_ORANGE, BTN_ORANGE_FG),
            ("Resume", self._resume, BTN_GREEN, BTN_GREEN_FG),
            ("Reset", self._reset, BTN_RED, BTN_RED_FG),
        ]
        
        # Create grid frame for equal button sizes
        btn_frame = tk.Frame(ctrl_box, bg=PANEL_BG)
        btn_frame.pack(fill="both", expand=True)
        
        for i, (label, fn, color, fgcolor) in enumerate(machine_buttons):
            tk.Button(
                btn_frame,
                text=label,
                command=fn,
                bg=color,
                fg=fgcolor,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                font=("Arial", 9, "bold"),
                bd=2,
                relief="raised"
            ).grid(row=i, column=0, sticky="ew", pady=2, padx=0)
        
        btn_frame.grid_columnconfigure(0, weight=1)

        # Force Stop button - prominent red (using Label for full control)
        estop_label = tk.Label(
            ctrl_box,
            text="E-STOP",
            bg="#CC0000",
            fg="#FFFFFF",
            font=("Arial", 9, "bold"),
            pady=8,
            relief="raised",
            bd=3
        )
        estop_label.pack(fill="both", expand=True, pady=(6, 2))
        
        # Bind click and visual feedback
        def estop_press(event=None):
            estop_label.config(bg="#990000", relief="sunken")
            ctrl_box.after(100, lambda: estop_label.config(bg="#CC0000", relief="raised"))
            self._force_stop()
        
        estop_label.bind("<Button-1>", estop_press)
        estop_label.config(cursor="hand2")

        # Jog Buttons
        jog_box = tk.LabelFrame(center, text="Jog Controls", bg=PANEL_BG, fg=FG,
                                font=("Arial", 9, "bold"), padx=2, pady=1, bd=2, relief="solid")
        jog_box.pack(anchor="n", fill="x", expand=False, pady=(16, 0))

        self.jog_buttons = []

        def make_jog_button(parent_widget, text, axis_moves, row, col):
            btn = tk.Button(
                parent_widget,
                text=text,
                font=button_font,
                width=3,
                height=2,
                bg=BTN_NEUTRAL,
                fg=BTN_NEUTRAL_FG,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                bd=4,
                relief="raised"
            )
            btn.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            btn.bind("<ButtonPress-1>", lambda _e, a=axis_moves, b=btn: self._on_jog_press(a, b))
            btn.bind("<ButtonRelease-1>", lambda _e, b=btn: self._on_jog_release(b))
            self.jog_buttons.append(btn)
            return btn

        for c in range(7):
            jog_box.grid_columnconfigure(c, weight=1, minsize=78)
        for r in range(3):
            jog_box.grid_rowconfigure(r, weight=0, minsize=78)

        make_jog_button(jog_box, "Y+", {"Y": 1}, 0, 1)
        make_jog_button(jog_box, "X-", {"X": -1}, 1, 0)
        make_jog_button(jog_box, "X+", {"X": 1}, 1, 2)
        make_jog_button(jog_box, "Y-", {"Y": -1}, 2, 1)

        make_jog_button(jog_box, "Z+", {"Z": 1}, 0, 3)
        make_jog_button(jog_box, "Z-", {"Z": -1}, 1, 3)

        make_jog_button(jog_box, "A+", {"A": 1}, 0, 4)
        make_jog_button(jog_box, "A-", {"A": -1}, 1, 4)

        make_jog_button(jog_box, "B+", {"B": 1}, 0, 5)
        make_jog_button(jog_box, "B-", {"B": -1}, 1, 5)

        make_jog_button(jog_box, "C+", {"C": 1}, 0, 6)
        make_jog_button(jog_box, "C-", {"C": -1}, 1, 6)

        # Outputs
        outputs_box = tk.LabelFrame(center, text="Outputs", bg=PANEL_BG, fg=BTN_YELLOW,
                                    font=("Arial", 9, "bold"), padx=2, pady=1, bd=2, relief="solid")
        outputs_box.pack(anchor="n", fill="x", pady=(10, 0))

        # ===== POSITION & ZERO (side by side) =====
        pos_zero_box = tk.LabelFrame(center, text="Position & Zero", bg=PANEL_BG, fg=FG,
                                     font=("Arial", 9, "bold"), padx=2, pady=1, bd=2, relief="solid")
        pos_zero_box.pack(anchor="n", fill="x", pady=(8, 0))

        # LEFT: Current Position
        left_col = tk.Frame(pos_zero_box, bg=PANEL_BG)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        pos_label = tk.Label(left_col, text="Current Position", bg=PANEL_BG, fg="#FFD54A",
                            font=("Arial", 9, "bold"))
        pos_label.pack(anchor="w", pady=(0, 4))

        axes_info = [("X", self.machine_pos_x_text), ("Y", self.machine_pos_y_text), 
                     ("Z", self.machine_pos_z_text), ("A", self.machine_pos_a_text),
                     ("B", self.machine_pos_b_text), ("C", self.machine_pos_c_text)]

        pos_frame = tk.Frame(left_col, bg=PANEL_BG)
        pos_frame.pack(fill="x")

        for row in range(2):
            for col in range(3):
                idx = row * 3 + col
                if idx < len(axes_info):
                    axis_name, pos_var = axes_info[idx]
                    tk.Label(pos_frame, text=f"{axis_name}:", bg=PANEL_BG, fg=FG, 
                            font=("Arial", 8, "bold"), width=2).grid(row=row, column=col*2, sticky="e", padx=(2, 1), pady=2)
                    tk.Label(pos_frame, textvariable=pos_var, bg=PANEL_BG, fg="#FFD54A",
                            font=("Courier", 13, "bold"), width=8, anchor="e").grid(row=row, column=col*2+1, sticky="w", padx=(0, 4), pady=2)

        # RIGHT: Set Zero buttons
        right_col = tk.Frame(pos_zero_box, bg=PANEL_BG)
        right_col.pack(side="left", fill="both", expand=True, padx=(10, 0))

        zero_label = tk.Label(right_col, text="Set Zero", bg=PANEL_BG, fg="#FFD54A",
                             font=("Arial", 9, "bold"))
        zero_label.pack(anchor="w", pady=(0, 4))

        zero_buttons = [
            ("Zero X", "G10 L20 P1 X0"),
            ("Zero Y", "G10 L20 P1 Y0"),
            ("Zero Z", "G10 L20 P1 Z0"),
            ("Zero A", "G10 L20 P1 A0"),
            ("Zero B", "G10 L20 P1 B0"),
            ("Zero C", "G10 L20 P1 C0"),
        ]

        zero_frame = tk.Frame(right_col, bg=PANEL_BG)
        zero_frame.pack(fill="x")

        for row, (label, cmd) in enumerate(zero_buttons):
            col = row % 2
            actual_row = row // 2
            tk.Button(
                zero_frame,
                text=label,
                command=lambda c=cmd: self._send_line(c),
                bg=BTN_NEUTRAL,
                fg=BTN_NEUTRAL_FG,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                font=("Arial", 9, "bold"),
                width=10,
                height=1,
                bd=2,
                relief="raised"
            ).grid(row=actual_row, column=col, padx=1, pady=1, sticky="ew")

        # Configure grid columns
        zero_frame.grid_columnconfigure(0, weight=1)
        zero_frame.grid_columnconfigure(1, weight=1)

        # ===== HOME AXIS - Full width panel at bottom =====
        home_box = tk.LabelFrame(home_section, text="Home Axis", bg=PANEL_BG, fg=FG,
                                font=("Arial", 9, "bold"), padx=10, pady=12, bd=2, relief="solid")
        home_box.pack(anchor="n", fill="x", pady=(0, 0))

        home_buttons = [
            ("Home X", "$HX"),
            ("Home Y", "$HY"),
            ("Home Z", "$HZ"),
            ("Home A", "$HA"),
            ("Home B", "$HB"),
            ("Home C", "$HC"),
        ]

        home_frame = tk.Frame(home_box, bg=PANEL_BG)
        home_frame.pack(fill="x")

        for idx, (label, cmd) in enumerate(home_buttons):
            col = idx % 3
            row = idx // 3
            tk.Button(
                home_frame,
                text=label,
                command=lambda c=cmd: self._send_line(c),
                bg=BTN_BLUE,
                fg=BTN_BLUE_FG,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                font=("Arial", 8, "bold"),
                width=18,
                height=2,
                bd=2,
                relief="raised"
            ).grid(row=row, column=col, padx=2, pady=4, sticky="ew")

        # Configure grid columns
        home_frame.grid_columnconfigure(0, weight=1)
        home_frame.grid_columnconfigure(1, weight=1)
        home_frame.grid_columnconfigure(2, weight=1)

        outputs_box.grid_columnconfigure(0, weight=1)
        outputs_box.grid_columnconfigure(1, weight=1)

        tk.Button(
            outputs_box, text="Light ON", command=self._light_on,
            bg=BTN_YELLOW, fg=BTN_YELLOW_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        tk.Button(
            outputs_box, text="Light OFF", command=self._light_off,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        tk.Button(
            outputs_box, text="Spindle ON", command=self._spindle_on,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=1, column=0, padx=4, pady=4, sticky="ew")

        tk.Button(
            outputs_box, text="Spindle OFF", command=self._spindle_off,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=1, column=1, padx=4, pady=4, sticky="ew")

    def _start_gcode_job(self) -> None:
        if not self._can_run_job():
            messagebox.showerror("Run Error", "Machine must be connected, idle, and not in alarm.")
            return
        if not self.gcode_lines:
            messagebox.showerror("Run Error", "No G-code loaded.")
            return

        self.job_running = True
        self.job_paused = False
        self.job_stopping = False
        self.waiting_for_ack = False
        self.last_controller_reply = None

        self.job_thread = threading.Thread(target=self._gcode_job_loop, daemon=True)
        self.job_thread.start()
        self._append_console("> Starting G-code job")

    def _pause_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_paused = True
        self.ctrl.send_realtime(b"!")
        self._append_console(">> [JOB HOLD] !")

    def _resume_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_paused = False
        self.ctrl.send_realtime(b"~")
        self._append_console(">> [JOB RESUME] ~")

    def _stop_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_stopping = True
        self.job_paused = False
        self.ctrl.send_realtime(b"\x18")
        self._append_console(">> [JOB STOP] Ctrl-X")

    def _build_run_tab(self, parent) -> None:
        """Job execution tab"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        small_font = ("Courier", 12)

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        job_box = tk.LabelFrame(main, text="G-code Job", bg=PANEL_BG, fg=FG,
                                font=default_font, padx=2, pady=1, bd=2, relief="solid")
        job_box.pack(fill="x", pady=(0, 8))

        tk.Label(job_box, textvariable=self.file_text, bg=PANEL_BG, fg=FG,
                 font=default_font, anchor="w", justify="left", wraplength=800).pack(fill="x", pady=(0, 6))

        job_btns = tk.Frame(job_box, bg=PANEL_BG)
        job_btns.pack(fill="x")

        tk.Button(
            job_btns, text="Load File", command=self._load_gcode_file,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=default_font, width=10,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=0, padx=4, pady=4)

        tk.Button(
            job_btns, text="Run", command=self._start_gcode_job,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=1, padx=4, pady=4)

        tk.Button(
            job_btns, text="Pause", command=self._pause_gcode_job,
            bg=BTN_ORANGE, fg=BTN_ORANGE_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=2, padx=4, pady=4)

        tk.Button(
            job_btns, text="Resume", command=self._resume_gcode_job,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=3, padx=4, pady=4)

        tk.Button(
            job_btns, text="Stop", command=self._stop_gcode_job,
            bg=BTN_RED, fg=BTN_RED_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=4, padx=4, pady=4)

        mdi_box = tk.LabelFrame(main, text="MDI / Console", bg=PANEL_BG, fg=FG,
                                font=default_font, padx=2, pady=1, bd=2, relief="solid")
        mdi_box.pack(fill="both", expand=True)

        mdi_top = tk.Frame(mdi_box, bg=PANEL_BG)
        mdi_top.pack(fill="x", pady=(0, 8))

        ttk.Entry(mdi_top, textvariable=self.mdi_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(
            mdi_top, text="Send", command=self._send_mdi,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).pack(side="left")

        self.console = tk.Text(
            mdi_box,
            font=small_font,
            bg=CONSOLE_BG,
            fg=CONSOLE_FG,
            insertbackground=FG,
            wrap="word",
            bd=2, relief="solid"
        )
        self.console.pack(fill="both", expand=True)

        tk.Button(
            mdi_box, text="Clear Console", command=self._clear_console,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=default_font, width=12,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).pack(anchor="w", pady=(8, 0))

    def _build_unified_preview_tab(self, parent) -> None:
        """Professional CNC preview with playback controls and timeline scrubber"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        control_font = ("Arial", 12, "bold")

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # ===== TOP TOOLBAR (thin and compact) =====
        top = tk.Frame(main, bg=PANEL_BG, height=50)
        top.pack(fill="x", padx=0, pady=0)
        top.pack_propagate(False)

        # Left: Mode selector
        mode_frame = tk.Frame(top, bg=PANEL_BG)
        mode_frame.pack(side="left", padx=10, pady=6)

        self.preview_mode = tk.StringVar(value="2d")
        
        tk.Radiobutton(
            mode_frame, text="2D XY", variable=self.preview_mode, value="2d",
            bg=PANEL_BG, fg=FG, activebackground=BG, selectcolor=BTN_BLUE,
            font=("Arial", 9, "bold"), command=self._switch_preview_mode
        ).pack(side="left", padx=8)
        
        tk.Radiobutton(
            mode_frame, text="3D Path", variable=self.preview_mode, value="3d",
            bg=PANEL_BG, fg=FG, activebackground=BG, selectcolor=BTN_BLUE,
            font=("Arial", 9, "bold"), command=self._switch_preview_mode
        ).pack(side="left", padx=8)

        # Center: Playback controls
        playback_frame = tk.Frame(top, bg=PANEL_BG)
        playback_frame.pack(side="left", padx=20, pady=6)

        self.preview_play_btn = tk.Button(
            playback_frame, text="▶ Play", command=self._preview_play,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=control_font, width=6, bd=2, relief="raised"
        )
        self.preview_play_btn.pack(side="left", padx=2)

        self.preview_pause_btn = tk.Button(
            playback_frame, text="⏸ Pause", command=self._preview_pause,
            bg=BTN_ORANGE, fg=BTN_ORANGE_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=control_font, width=6, bd=2, relief="raised", state="disabled"
        )
        self.preview_pause_btn.pack(side="left", padx=2)

        tk.Button(
            playback_frame, text="⏭ Step", command=self._preview_step_frame,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=control_font, width=6, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            playback_frame, text="⏹ Stop", command=self._preview_stop,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=control_font, width=6, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        # Speed control
        tk.Label(playback_frame, text="Speed:", bg=PANEL_BG, fg=FG, font=("Arial", 11, "bold")).pack(side="left", padx=(20, 4))
        
        self.preview_speed_var = tk.StringVar(value="1.0x")
        speed_combo = ttk.Combobox(
            playback_frame, textvariable=self.preview_speed_var,
            values=["0.25x", "0.5x", "0.75x", "1.0x", "1.5x", "2.0x", "4.0x"],
            width=6, state="readonly", font=("Arial", 11, "bold")
        )
        speed_combo.pack(side="left", padx=2)
        speed_combo.current(3)  # Default to 1.0x
        speed_combo.bind("<<ComboboxSelected>>", lambda e: self._update_preview_speed())

        # Right: Info display
        info_frame = tk.Frame(top, bg=PANEL_BG)
        info_frame.pack(side="right", padx=10, pady=6, fill="x", expand=True)

        self.preview_time_var = tk.StringVar(value="Time: --:--")
        self.preview_segment_var = tk.StringVar(value="Segments: 0/0")
        
        tk.Label(info_frame, textvariable=self.preview_segment_var, bg=PANEL_BG, fg=FG, 
                font=("Arial", 11, "bold")).pack(side="left", padx=(0, 20))
        tk.Label(info_frame, textvariable=self.preview_time_var, bg=PANEL_BG, fg=FG, 
                font=("Arial", 11, "bold")).pack(side="left", padx=0)

        # ===== CANVAS AREA (main content, takes all remaining space) =====
        self.preview_container = tk.Frame(main, bg=BG)
        self.preview_container.pack(fill="both", expand=True)

        # Create both canvases upfront (hidden by default)
        # 2D Canvas
        self.preview_canvas_2d = tk.Canvas(
            self.preview_container,
            bg="#0D0D0D",
            highlightthickness=0
        )

        # 3D Figure - larger size for better quality
        self.preview_3d_figure = Figure(figsize=(14, 10), dpi=100)
        self.preview_3d_ax = self.preview_3d_figure.add_subplot(111, projection="3d")
        self.preview_3d_figure.patch.set_facecolor("#111111")
        self.preview_3d_ax.set_facecolor("#111111")
        self.preview_3d_canvas = FigureCanvasTkAgg(self.preview_3d_figure, master=self.preview_container)

        # ===== BOTTOM SCRUBBER BAR =====
        scrubber_frame = tk.Frame(main, bg=PANEL_BG, height=40)
        scrubber_frame.pack(fill="x", padx=0, pady=0)
        scrubber_frame.pack_propagate(False)

        self.preview_scrubber_var = tk.DoubleVar(value=0.0)
        self.preview_scrubber = tk.Scale(
            scrubber_frame,
            from_=0.0, to=100.0,
            orient="horizontal",
            variable=self.preview_scrubber_var,
            bg=PANEL_BG, fg=FG,
            troughcolor="#1A1A1A",
            activebackground=BTN_BLUE,
            highlightthickness=0,
            command=self._preview_scrubber_moved
        )
        self.preview_scrubber.pack(fill="both", expand=True, padx=2, pady=1)

        # Show 2D by default
        self._switch_preview_mode()

    def _switch_preview_mode(self) -> None:
        """Switch between 2D and 3D preview"""
        # Clear the container
        for widget in self.preview_container.winfo_children():
            widget.pack_forget()

        try:
            if self.preview_mode.get() == "2d":
                self._draw_toolpath_preview()
                # Ensure 2D canvas is visible
                if self.preview_canvas_2d:
                    self.preview_canvas_2d.pack(fill="both", expand=True)
            else:
                # Make sure 3D figure has dark background
                self.preview_3d_figure.patch.set_facecolor("#111111")
                self.preview_3d_ax.set_facecolor("#111111")
                self._draw_gcode_3d_preview()
                # Ensure 3D canvas is visible
                if self.preview_3d_canvas:
                    tk_widget = self.preview_3d_canvas.get_tk_widget()
                    tk_widget.pack(fill="both", expand=True)
        except Exception as e:
            self._append_console(f"Error switching preview mode: {e}")

    def _refresh_preview_unified(self) -> None:
        """Refresh current preview (2D or 3D)"""
        if self.preview_mode.get() == "2d":
            self._draw_toolpath_preview()
        else:
            self._draw_gcode_3d_preview()

    def _build_gcode_viewer_tab(self, parent) -> None:
        """G-code viewer"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        mono_font = ("Courier New", 11)

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        top = tk.Frame(main, bg=BG)
        top.pack(fill="x", pady=(0, 8))

        tk.Label(top, text="G-code File", bg=BG, fg=FG, font=default_font).pack(side="left", padx=(0, 8))
        tk.Label(top, textvariable=self.file_text, bg=BG, fg=FG, font=default_font).pack(side="left", padx=8)

        tk.Button(
            top, text="Load File", command=self._load_gcode_file,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=12, bd=3, relief="raised"
        ).pack(side="right", padx=(8, 0))

        frame = tk.Frame(main, bg=BG)
        frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.gcode_viewer = tk.Text(
            frame,
            font=mono_font,
            bg=CONSOLE_BG,
            fg=CONSOLE_FG,
            insertbackground=FG,
            wrap="none",
            yscrollcommand=scrollbar.set,
            bd=2, relief="solid"
        )
        self.gcode_viewer.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.gcode_viewer.yview)

    def _build_vision_dxf_tab(self, parent) -> None:
        """Vision + DXF integrated tab"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        small_font = ("Arial", 11)

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # ===== VISION SECTION =====
        vision_box = tk.LabelFrame(main, text="Vision: Image Stitching", bg=PANEL_BG, fg=FG,
                                  font=default_font, padx=2, pady=1, bd=2, relief="solid")
        vision_box.pack(fill="x", pady=(0, 10))

        vision_top = tk.Frame(vision_box, bg=PANEL_BG)
        vision_top.pack(fill="x", pady=(0, 8))

        tk.Button(
            vision_top, text="Load Images", command=self._load_vision_images,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=14, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            vision_top, text="Stitch", command=self._stitch_vision_images,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            vision_top, text="Clear", command=self._clear_vision_images,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=8, bd=3, relief="raised"
        ).pack(side="left")

        tk.Label(vision_top, text="No vision images loaded", bg=PANEL_BG, fg="#CCCCCC", 
                font=small_font).pack(side="left", padx=12)

        # ===== DXF SECTION =====
        dxf_box = tk.LabelFrame(main, text="DXF: Die-line Placement", bg=PANEL_BG, fg=FG,
                               font=default_font, padx=2, pady=1, bd=2, relief="solid")
        dxf_box.pack(fill="x", pady=(0, 10))

        dxf_top = tk.Frame(dxf_box, bg=PANEL_BG)
        dxf_top.pack(fill="x", pady=(0, 8))

        tk.Button(
            dxf_top, text="Load DXF", command=self._load_dxf_file,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=12, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            dxf_top, text="Auto Register", command=self._auto_register_dxf,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=14, bd=3, relief="raised"
        ).pack(side="left")

        tk.Label(dxf_top, text="No DXF loaded", bg=PANEL_BG, fg="#CCCCCC", 
                font=small_font).pack(side="left", padx=12)

        # ===== TRANSFORM CONTROLS =====
        trans_box = tk.LabelFrame(main, text="Die-line Placement Controls", bg=PANEL_BG, fg=FG,
                                  font=default_font, padx=2, pady=1, bd=2, relief="solid")
        trans_box.pack(fill="x", pady=(0, 10))

        # Grid layout for controls
        control_grid = tk.Frame(trans_box, bg=PANEL_BG)
        control_grid.pack(fill="x", padx=4, pady=4)

        tk.Label(control_grid, text="Translate X (mm)", bg=PANEL_BG, fg=FG, font=small_font).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(control_grid, textvariable=self.dxf_tx_var, width=12).grid(row=0, column=1, padx=(0, 20), sticky="ew")

        tk.Label(control_grid, text="Rotate (deg)", bg=PANEL_BG, fg=FG, font=small_font).grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(control_grid, textvariable=self.dxf_rot_var, width=12).grid(row=0, column=3, padx=(0, 20), sticky="ew")

        tk.Label(control_grid, text="Translate Y (mm)", bg=PANEL_BG, fg=FG, font=small_font).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(control_grid, textvariable=self.dxf_ty_var, width=12).grid(row=1, column=1, padx=(0, 20), sticky="ew")

        tk.Label(control_grid, text="Scale", bg=PANEL_BG, fg=FG, font=small_font).grid(row=1, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(control_grid, textvariable=self.dxf_scale_var, width=12).grid(row=1, column=3, padx=(0, 20), sticky="ew")

        # Buttons
        btn_frame = tk.Frame(trans_box, bg=PANEL_BG)
        btn_frame.pack(fill="x", padx=4, pady=4)

        tk.Button(btn_frame, text="Apply Transform", command=self._apply_dxf_transform, 
                 bg=BTN_BLUE, fg=BTN_BLUE_FG, font=small_font, width=14, bd=3, relief="raised").pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Reset", command=self._reset_dxf_transform,
                 bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=small_font, width=10, bd=3, relief="raised").pack(side="left", padx=(0, 8))
        
        # Zoom controls
        zoom_frame = tk.Frame(trans_box, bg=PANEL_BG)
        zoom_frame.pack(fill="x", padx=4, pady=4)
        
        tk.Label(zoom_frame, text="Zoom:", bg=PANEL_BG, fg=FG, font=small_font).pack(side="left", padx=(0, 4))
        tk.Button(zoom_frame, text="−", command=lambda: self._zoom_dxf(-1),
                 bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=("Arial", 8, "bold"), width=3, bd=2, relief="raised").pack(side="left", padx=2)
        tk.Button(zoom_frame, text="+", command=lambda: self._zoom_dxf(1),
                 bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=("Arial", 8, "bold"), width=3, bd=2, relief="raised").pack(side="left", padx=2)
        tk.Button(zoom_frame, text="Fit View", command=self._dxf_fit_view,
                 bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=small_font, width=10, bd=3, relief="raised").pack(side="left", padx=(4, 0))

        # ===== PREVIEW CANVAS =====
        canvas_frame = tk.LabelFrame(main, text="Preview", bg=PANEL_BG, fg=FG,
                                    font=default_font, padx=2, pady=1, bd=2, relief="solid")
        canvas_frame.pack(fill="both", expand=True)

        self.vision_dxf_canvas = tk.Canvas(
            canvas_frame,
            bg="#0D0D0D",
            highlightthickness=2,
            highlightbackground="#444444"
        )
        self.vision_dxf_canvas.pack(fill="both", expand=True)
        
        # Canvas bindings for zoom and pan
        self.vision_dxf_canvas.bind("<MouseWheel>", self._dxf_canvas_zoom)  # Windows
        self.vision_dxf_canvas.bind("<Button-4>", self._dxf_canvas_zoom)     # Linux scroll up
        self.vision_dxf_canvas.bind("<Button-5>", self._dxf_canvas_zoom)     # Linux scroll down
        self.vision_dxf_canvas.bind("<Button-1>", self._dxf_canvas_pan_start)    # Left click start
        self.vision_dxf_canvas.bind("<B1-Motion>", self._dxf_canvas_pan_move)    # Left click drag
        self.vision_dxf_canvas.bind("<ButtonRelease-1>", self._dxf_canvas_pan_end)  # Left click release
        self.vision_dxf_canvas.bind("<Button-3>", self._dxf_canvas_pan_start)    # Right click start (backup)
        self.vision_dxf_canvas.bind("<B3-Motion>", self._dxf_canvas_pan_move)    # Right click drag
        self.vision_dxf_canvas.bind("<ButtonRelease-3>", self._dxf_canvas_pan_end)  # Right click release

    def _build_mesh_tab(self, parent) -> None:
        """Mesh viewer"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        small_font = ("Arial", 11, "bold")

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # TOP: File controls
        top = tk.Frame(main, bg=BG)
        top.pack(fill="x", pady=(0, 8))

        tk.Button(
            top, text="Load STL / OBJ", command=self._load_scan_mesh_file,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG,
            activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=14, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            top, text="Refresh Mesh", command=self._draw_mesh_preview,
            bg=BTN_BLUE, fg=BTN_BLUE_FG,
            activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=12, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Label(top, textvariable=self.mesh_info_text, bg=BG, fg=FG, font=default_font).pack(side="left", padx=12, fill="x", expand=True)

        # CONTROLS: Rotation and zoom
        controls = tk.Frame(main, bg=BG)
        controls.pack(fill="x", pady=(0, 8))

        # Rotation controls
        rot_label = tk.Label(controls, text="Rotate:", bg=BG, fg=FG, font=small_font)
        rot_label.pack(side="left", padx=(0, 8))

        tk.Button(
            controls, text="↶", command=lambda: self._adjust_mesh_view(-15, 0),
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            font=("Arial", 9, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="↷", command=lambda: self._adjust_mesh_view(15, 0),
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            font=("Arial", 9, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="↑", command=lambda: self._adjust_mesh_view(0, 10),
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            font=("Arial", 9, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="↓", command=lambda: self._adjust_mesh_view(0, -10),
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            font=("Arial", 9, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=(2, 20))

        # Zoom controls
        zoom_label = tk.Label(controls, text="Zoom:", bg=BG, fg=FG, font=small_font)
        zoom_label.pack(side="left", padx=(0, 8))

        tk.Button(
            controls, text="+", command=lambda: self._adjust_mesh_zoom(1.2),
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            font=("Arial", 9, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="−", command=lambda: self._adjust_mesh_zoom(0.85),
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            font=("Arial", 9, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=(2, 20))

        # View presets
        view_label = tk.Label(controls, text="View:", bg=BG, fg=FG, font=small_font)
        view_label.pack(side="left", padx=(0, 8))

        tk.Button(
            controls, text="Top", command=lambda: self._set_mesh_view(0, 90),
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            font=("Arial", 8, "bold"), width=5, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="Front", command=lambda: self._set_mesh_view(0, 0),
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            font=("Arial", 8, "bold"), width=5, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="Side", command=lambda: self._set_mesh_view(90, 0),
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            font=("Arial", 8, "bold"), width=5, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="Iso", command=lambda: self._set_mesh_view(45, 30),
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            font=("Arial", 8, "bold"), width=5, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        tk.Button(
            controls, text="Reset", command=self._reset_mesh_view,
            bg=BTN_ORANGE, fg=BTN_ORANGE_FG, activebackground=BTN_PRESSED,
            font=("Arial", 8, "bold"), width=5, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        # Canvas
        frame = tk.Frame(main, bg=BG)
        frame.pack(fill="both", expand=True)

        self.mesh_figure = Figure(figsize=(10, 7), dpi=100)
        self.mesh_ax = self.mesh_figure.add_subplot(111, projection="3d")
        self.mesh_figure.patch.set_facecolor("#111111")
        self.mesh_ax.set_facecolor("#111111")

        self.mesh_canvas = FigureCanvasTkAgg(self.mesh_figure, master=frame)
        self.mesh_canvas.get_tk_widget().pack(fill="both", expand=True)

        self._style_3d_axes(self.mesh_ax)
        self.mesh_canvas.draw()
        
        # Initialize mesh view angles
        self.mesh_azim = 35
        self.mesh_elev = 20

    def _build_slats_tab(self, parent) -> None:
        """Slats generation"""
        if not HAS_SLATS:
            tk.Label(parent, text="Slats module not available. Install Filler.grid_slats", 
                    bg=BG, fg="red", font=("Arial", 14)).pack(padx=20, pady=20)
            return

        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        top = tk.Frame(main, bg=BG)
        top.pack(fill="x", pady=(0, 8))

        tk.Button(
            top, text="Use Loaded Mesh", command=self._sync_mesh_to_slats,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG,
            activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=14, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Label(top, text="XY slats", bg=BG, fg=FG, font=default_font).pack(side="left", padx=(8, 4))
        ttk.Combobox(top, textvariable=self.n_xy_var, width=4, state="readonly",
                     values=[str(v) for v in range(2, 17)]).pack(side="left", padx=(0, 8))

        tk.Label(top, text="XZ slats", bg=BG, fg=FG, font=default_font).pack(side="left", padx=(8, 4))
        ttk.Combobox(top, textvariable=self.n_xz_var, width=4, state="readonly",
                     values=[str(v) for v in range(2, 17)]).pack(side="left", padx=(0, 8))

        ttk.Checkbutton(top, text="Show mesh in 3D", variable=self.show_mesh_in_slats_var).pack(side="left", padx=(8, 8))

        tk.Button(
            top, text="Build Slats", command=self._compute_slats_preview,
            bg=BTN_BLUE, fg=BTN_BLUE_FG,
            activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            top, text="Clear Slats", command=self._clear_slats_preview,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG,
            activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 8))

        tk.Label(top, textvariable=self.slats_info_text, bg=BG, fg=FG, font=default_font).pack(side="left", padx=12)
        
        # Add zoom controls for 2D view
        zoom_frame = tk.Frame(top, bg=BG)
        zoom_frame.pack(side="left", padx=(20, 0))
        
        tk.Label(zoom_frame, text="2D Zoom:", bg=BG, fg=FG, font=default_font).pack(side="left", padx=(0, 8))
        
        tk.Button(
            zoom_frame, text="+", command=lambda: self._zoom_slats_2d(1.2),
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=("Arial", 11, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=2)
        
        tk.Button(
            zoom_frame, text="−", command=lambda: self._zoom_slats_2d(0.8),
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=("Arial", 11, "bold"), width=3, bd=2, relief="raised"
        ).pack(side="left", padx=2)
        
        tk.Button(
            zoom_frame, text="Reset", command=self._reset_slats_2d_zoom,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=("Arial", 10), width=5, bd=2, relief="raised"
        ).pack(side="left", padx=2)

        inner_notebook = ttk.Notebook(main)
        inner_notebook.pack(fill="both", expand=True)

        slats_3d_tab = tk.Frame(inner_notebook, bg=BG)
        slats_2d_tab = tk.Frame(inner_notebook, bg=BG)

        inner_notebook.add(slats_3d_tab, text="3D Grid")
        inner_notebook.add(slats_2d_tab, text="2D Cut Patterns")

        frame3d = tk.Frame(slats_3d_tab, bg=BG)
        frame3d.pack(fill="both", expand=True)

        self.slats_3d_figure = Figure(figsize=(10, 7), dpi=100)
        self.slats_3d_ax = self.slats_3d_figure.add_subplot(111, projection="3d")
        self.slats_3d_figure.patch.set_facecolor("#111111")
        self.slats_3d_ax.set_facecolor("#111111")

        self.slats_3d_canvas = FigureCanvasTkAgg(self.slats_3d_figure, master=frame3d)
        self.slats_3d_canvas.get_tk_widget().pack(fill="both", expand=True)

        self._style_3d_axes(self.slats_3d_ax)
        self.slats_3d_canvas.draw()

        frame2d = tk.Frame(slats_2d_tab, bg=BG)
        frame2d.pack(fill="both", expand=True)
        self.slats_2d_container = frame2d  # Store reference for later use

        self.slats_2d_figure = Figure(figsize=(18, 14), dpi=100)
        self.slats_2d_figure.patch.set_facecolor("#111111")
        self.slats_2d_canvas = FigureCanvasTkAgg(self.slats_2d_figure, master=frame2d)
        self.slats_2d_canvas.get_tk_widget().pack(fill="both", expand=True)
        self.slats_2d_canvas.draw()

        """Unified Slats CAM: Library + Interactive DXF Workspace"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        small_font = ("Arial", 11)
        
        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # --- STAGE 1: LOADING (Header Row) ---
        load_frame = tk.Frame(main, bg=PANEL_BG, bd=2, relief="solid")
        load_frame.pack(fill="x", pady=(0, 5), ipady=5)
        
        tk.Button(load_frame, text="1. Load STL", command=self._slats_cam_browse_stl,
                  bg=BTN_NEUTRAL, font=small_font, width=12).pack(side="left", padx=10)
        
        tk.Label(load_frame, text="XY:", bg=PANEL_BG, fg=FG).pack(side="left")
        ttk.Combobox(load_frame, textvariable=self.slats_cam_n_xy_var, width=3, values=[str(i) for i in range(2,16)]).pack(side="left", padx=5)
        
        tk.Label(load_frame, text="XZ:", bg=PANEL_BG, fg=FG).pack(side="left")
        ttk.Combobox(load_frame, textvariable=self.slats_cam_n_xz_var, width=3, values=[str(i) for i in range(2,16)]).pack(side="left", padx=5)
        
        tk.Button(load_frame, text="2. Generate Slats", command=self._slats_cam_load_and_compute,
                  bg=BTN_BLUE, font=small_font).pack(side="left", padx=10)

        # --- SLAT LIBRARY (Top Preview) ---
        lib_label = tk.Label(main, text="SLAT LIBRARY (Blue=XY, Orange=XZ)", bg=BG, fg=FG, font=("Arial", 8, "bold"))
        lib_label.pack(anchor="w")
        
        self.slats_cam_preview_canvas = tk.Canvas(main, bg="#0D0D0D", height=120, highlightthickness=1, highlightbackground=BTN_BLUE)
        self.slats_cam_preview_canvas.pack(fill="x", pady=(0, 10))

        # --- MAIN WORKSPACE (DXF + Draggable Slats) ---
        work_label = tk.Label(main, text="DXF WORKSPACE (Drag slats onto cardboard)", bg=BG, fg=FG, font=("Arial", 8, "bold"))
        work_label.pack(anchor="w")
        
        self.slats_cam_dxf_canvas = tk.Canvas(main, bg="#0D0D0D", highlightthickness=2, highlightbackground="#444444")
        self.slats_cam_dxf_canvas.pack(fill="both", expand=True)
        
        # Persistent data for interaction
        self.slat_workspace_offsets = {} # Stores {index: (dx, dy)}
        self.selected_slat_idx = None

        # --- BOTTOM CONTROLS ---
        ctrl_frame = tk.Frame(main, bg=PANEL_BG, pady=5)
        ctrl_frame.pack(fill="x", pady=(5, 0))
        
        tk.Button(ctrl_frame, text="Reset Positions", command=self._reset_slat_positions, bg=BTN_ORANGE).pack(side="left", padx=10)
        tk.Button(ctrl_frame, text="GENERATE G-CODE", command=self._slats_cam_generate_gcode, 
                  bg=BTN_GREEN, font=default_font, width=20).pack(side="right", padx=10)

    def _build_slats_cam_tab(self, parent) -> None:
        """Unified Slats CAM: STL → Auto-Pack → DXF Workspace with Interactive Drag"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        small_font = ("Arial", 11)
        
        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # --- STAGE 1: LOAD STL & GENERATE ---
        load_frame = tk.LabelFrame(main, text="1. Load STL & Generate Slats", 
                                   bg=PANEL_BG, fg=FG, font=default_font, 
                                   padx=2, pady=1, bd=2, relief="solid")
        load_frame.pack(fill="x", pady=(0, 10))
        
        load_top = tk.Frame(load_frame, bg=PANEL_BG)
        load_top.pack(fill="x")
        
        tk.Button(load_top, text="Browse STL", command=self._slats_cam_browse_stl,
                  bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=small_font, width=12).pack(side="left", padx=(0, 10))
        
        tk.Label(load_top, text="XY Slats:", bg=PANEL_BG, fg=FG, font=small_font).pack(side="left", padx=(0, 4))
        ttk.Combobox(load_top, textvariable=self.slats_cam_n_xy_var, width=3, state="readonly",
                     values=[str(i) for i in range(2,16)]).pack(side="left", padx=(0, 10))
        
        tk.Label(load_top, text="XZ Slats:", bg=PANEL_BG, fg=FG, font=small_font).pack(side="left", padx=(0, 4))
        ttk.Combobox(load_top, textvariable=self.slats_cam_n_xz_var, width=3, state="readonly",
                     values=[str(i) for i in range(2,16)]).pack(side="left", padx=(0, 10))
        
        tk.Button(load_top, text="Generate Slats", command=self._slats_cam_load_and_compute,
                  bg=BTN_BLUE, fg=BTN_BLUE_FG, font=small_font, activebackground=BTN_PRESSED).pack(side="left", padx=(0, 10))
        
        tk.Label(load_top, textvariable=self.slats_cam_slats_info_var, bg=PANEL_BG, fg="#FFD54A", 
                font=small_font).pack(side="left", padx=10)

        # --- STAGE 2: DXF & PACKING ---
        pack_frame = tk.LabelFrame(main, text="2. Load Cardboard DXF & Auto-Pack", 
                                   bg=PANEL_BG, fg=FG, font=default_font, 
                                   padx=2, pady=1, bd=2, relief="solid")
        pack_frame.pack(fill="x", pady=(0, 10))
        
        pack_top = tk.Frame(pack_frame, bg=PANEL_BG)
        pack_top.pack(fill="x")
        
        tk.Button(pack_top, text="Load DXF", command=self._slats_cam_load_dxf_for_packing,
                  bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=small_font, width=12).pack(side="left", padx=(0, 10))
        
        tk.Button(pack_top, text="Auto-Pack Slats", command=self._slats_cam_auto_pack,
                  bg=BTN_BLUE, fg=BTN_BLUE_FG, font=small_font, activebackground=BTN_PRESSED).pack(side="left", padx=(0, 10))
        
        tk.Button(pack_top, text="Repack", command=self._slats_cam_auto_pack,
                  bg=BTN_ORANGE, fg=BTN_ORANGE_FG, font=("Arial", 10), activebackground=BTN_PRESSED).pack(side="left", padx=(0, 10))
        
        tk.Label(pack_top, text="Status:", bg=PANEL_BG, fg=FG, font=small_font).pack(side="left", padx=(0, 4))
        tk.Label(pack_top, textvariable=self.slats_cam_status_var, bg=PANEL_BG, fg="#FFD54A", 
                font=small_font).pack(side="left")

        # --- VIEW CONTROLS ---
        view_ctrl = tk.Frame(main, bg=BG)
        view_ctrl.pack(fill="x", pady=(0, 8))

        tk.Label(view_ctrl, text="Workspace View:", bg=BG, fg=FG, font=("Arial", 8, "bold")).pack(side="left", padx=(0, 10))
        tk.Button(view_ctrl, text="−", command=lambda: self._zoom_dxf(-1), 
                  bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, width=3).pack(side="left", padx=1)
        tk.Button(view_ctrl, text="+", command=lambda: self._zoom_dxf(1), 
                  bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, width=3).pack(side="left", padx=1)
        tk.Button(view_ctrl, text="Fit View", command=self._slats_cam_fit_view, 
                  bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG).pack(side="left", padx=10)
        tk.Button(view_ctrl, text="Reset Positions", command=self._reset_slat_positions, 
                  bg=BTN_ORANGE, fg=BTN_ORANGE_FG).pack(side="left", padx=10)
        
        tk.Label(view_ctrl, text="Drag slats to reposition • Right-click to pan", 
                bg=BG, fg="#CCCCCC", font=("Arial", 9)).pack(side="left", padx=20)

        # --- MAIN WORKSPACE CANVAS ---
        canvas_frame = tk.LabelFrame(main, text="Packing Workspace", bg=PANEL_BG, fg=FG,
                                     font=("Arial", 11, "bold"), padx=2, pady=2, bd=2, relief="solid")
        canvas_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        self.slats_cam_dxf_canvas = tk.Canvas(canvas_frame, bg="#0D0D0D", highlightthickness=1, 
                                              highlightbackground="#444444", cursor="hand2")
        self.slats_cam_dxf_canvas.pack(fill="both", expand=True)
        
        # --- BOTTOM: GENERATE G-CODE ---
        tk.Button(main, text="✓ GENERATE G-CODE", command=self._slats_cam_generate_gcode, 
                  bg=BTN_GREEN, fg=BTN_GREEN_FG, font=default_font, height=2,
                  activebackground=BTN_PRESSED, activeforeground="#000000").pack(fill="x")

    def _refresh_slat_library(self) -> None:
        """Draws all slats in a single row at the top"""
        canvas = self.slats_cam_preview_canvas
        canvas.delete("all")
        if not self.slats_cam_raw_slats: return
        
        w, h, gap, margin = canvas.winfo_width(), canvas.winfo_height(), 15, 20
        total_w = sum(s.bounds[2]-s.bounds[0] for s in self.slats_cam_raw_slats) + (gap * len(self.slats_cam_raw_slats))
        scale = min((w - 2*margin)/total_w, (h - 2*margin)/max(s.bounds[3]-s.bounds[1] for s in self.slats_cam_raw_slats))
        
        curr_x = margin
        for i, slat in enumerate(self.slats_cam_raw_slats):
            # Color all XY slats (left + right) blue, others orange
            n_xy_total = int(self.slats_cam_n_xy_var.get()) * 2
            color = "#0088FF" if i < n_xy_total else "#FF8800"
            b = slat.bounds
            for poly in self._explode_polys(slat):
                pts = []
                for x, y in poly.exterior.coords:
                    pts.extend([curr_x + (x-b[0])*scale, (h/2) - (y-(b[1]+b[3])/2)*scale])
                canvas.create_polygon(pts, fill=color, outline="white", width=1, stipple="gray50")
            curr_x += (b[2]-b[0] + gap) * scale

    def _slats_cam_overlay_dxf(self) -> None:
        """Unified Workspace: Grid + Green DXF + Movable Slats with Pan/Zoom logic from Vision Tab."""
        canvas = self.slats_cam_dxf_canvas
        canvas.delete("all")
        if not self.dxf_dieline: return

        # 1. Coordinate Setup (Listening to global Zoom and Pan vars)
        info = self.dxf_dieline.get_info()
        bounds = info['bounds']  
        canvas.update()
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw <= 1: cw, ch = 1200, 800

        margin = 40
        d_w, d_h = max(bounds[2]-bounds[0], 1), max(bounds[3]-bounds[1], 1)
        base_scale = min((cw - 2*margin) / d_w, (ch - 2*margin) / d_h)
        fit_scale = base_scale * self.dxf_canvas_zoom

        def to_canvas(x, y):
            cx = (cw/2) + self.dxf_canvas_pan_x + (x - (bounds[0] + bounds[2])/2) * fit_scale
            cy = (ch/2) + self.dxf_canvas_pan_y - (y - (bounds[1] + bounds[3])/2) * fit_scale
            return cx, cy

        # 2. Draw Dynamic Grid
        grid_step = 50 * self.dxf_canvas_zoom
        if grid_step > 5:
            for x_line in np.arange(self.dxf_canvas_pan_x % grid_step, cw, grid_step):
                canvas.create_line(x_line, 0, x_line, ch, fill="#1A1A1A", width=1)
            for y_line in np.arange(self.dxf_canvas_pan_y % grid_step, ch, grid_step):
                canvas.create_line(0, y_line, cw, y_line, fill="#1A1A1A", width=1)

        # 3. Draw Home Reference
        ox, oy = to_canvas(0, 0)
        canvas.create_line(ox, 0, ox, ch, fill="#333333", dash=(4, 4))
        canvas.create_line(0, oy, cw, oy, fill="#333333", dash=(4, 4))

        # 4. Draw DXF (Green Outline)
        try:
            for geom in self.dxf_dieline.get_geometries(): 
                for poly in self._explode_polys(geom):
                    pts = []
                    for x, y in poly.exterior.coords:
                        pts.extend(to_canvas(x, y))
                    canvas.create_line(pts, fill="#00FF00", width=2)
        except Exception as e:
            print(f"DXF Draw Error: {e}")

        # 5. Draw Interactive Slats
        if self.slats_cam_raw_slats:
            n_xy_total = int(self.slats_cam_n_xy_var.get()) * 2
            for i, slat in enumerate(self.slats_cam_raw_slats):
                offset = self.slat_workspace_offsets.get(i, {'x': 0, 'y': 0})
                is_selected = (self.selected_slat_idx == i)
                color = "white" if is_selected else ("#4EA1FF" if i < n_xy_total else "#FFB347")
                
                for poly in self._explode_polys(slat):
                    pts = []
                    for x, y in poly.exterior.coords:
                        bx, by = to_canvas(x, y)
                        pts.extend([bx + offset['x'], by + offset['y']])
                    canvas.create_polygon(pts, fill=color, outline="white", 
                                        tags=("slat_obj", f"slat_{i}"), alpha=0.7)

        # 6. Bind Controls
        self._bind_slat_cam_controls()

    def _bind_slat_cam_controls(self):
        c = self.slats_cam_dxf_canvas
        c.tag_bind("slat_obj", "<Button-1>", self._on_slat_click)
        c.tag_bind("slat_obj", "<B1-Motion>", self._on_slat_drag)
        # Match your exact Vision Tab Pan/Zoom names
        c.bind("<Button-3>", self._dxf_canvas_pan_start)
        c.bind("<B3-Motion>", self._dxf_canvas_pan_move)
        c.bind("<ButtonRelease-3>", self._dxf_canvas_pan_end)
        c.bind("<MouseWheel>", self._dxf_canvas_zoom)

    def _bind_slat_cam_controls(self):
        canvas = self.slats_cam_dxf_canvas
        # Drag Slats (Left Click)
        canvas.tag_bind("slat_obj", "<Button-1>", self._on_slat_click)
        canvas.tag_bind("slat_obj", "<B1-Motion>", self._on_slat_drag)
        
        # Pan Workspace (Right Click)
        canvas.bind("<Button-3>", self._dxf_canvas_pan_start) # Match your function name
        canvas.bind("<B3-Motion>", self._dxf_canvas_pan_move) # Match your function name
        canvas.bind("<ButtonRelease-3>", self._dxf_canvas_pan_end)
        
        # Zoom Workspace (Scroll)
        canvas.bind("<MouseWheel>", self._dxf_canvas_zoom) # Match your function name

    def _on_workspace_zoom(self, event):
        # Determine direction
        if event.num == 4 or event.delta > 0: self.dxf_canvas_zoom *= 1.1
        else: self.dxf_canvas_zoom *= 0.9
        self.dxf_canvas_zoom = max(0.1, min(10.0, self.dxf_canvas_zoom))
        self._slats_cam_overlay_dxf() # Redraw Slats Tab
        self._draw_dxf_on_canvas()    # Redraw Vision Tab

    def _on_workspace_pan_move(self, event):
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y
        self.dxf_canvas_pan_x += dx
        self.dxf_canvas_pan_y += dy
        self._pan_start_x, self._pan_start_y = event.x, event.y
        self._slats_cam_overlay_dxf()
        self._draw_dxf_on_canvas()

    def _on_slat_click(self, event):
        """Standard selection using the 'current' tag for precision"""
        # 1. find_withtag("current") picks up the specific polygon under the mouse
        item = self.slats_cam_dxf_canvas.find_withtag("current")
        if not item: 
            self.selected_slat_idx = None
            return
        
        tags = self.slats_cam_dxf_canvas.gettags(item[0])
        for t in tags:
            # 2. Check for the 'slat_N' tag we added in the drawing loop
            if t.startswith("slat_") and t != "slat_obj":
                self.selected_slat_idx = int(t.split("_")[1])
                self._drag_start_pos = (event.x, event.y)
                
                # 3. Visual feedback: Bring the whole group to the front
                self.slats_cam_dxf_canvas.tag_raise(f"slat_{self.selected_slat_idx}")
                self._slats_cam_overlay_dxf() 
                break

    def _on_slat_drag(self, event):
        """Update slat offset based on pixel deltas"""
        if self.selected_slat_idx is None: return
        
        # Calculate how many pixels moved
        dx = event.x - self._drag_start_pos[0]
        dy = event.y - self._drag_start_pos[1]
        
        # Update persistent pixel storage
        off = self.slat_workspace_offsets.get(self.selected_slat_idx, {'x': 0, 'y': 0})
        self.slat_workspace_offsets[self.selected_slat_idx] = {
            'x': off['x'] + dx, 
            'y': off['y'] + dy
        }
        
        # Reset anchor for next frame
        self._drag_start_pos = (event.x, event.y)
        self._slats_cam_overlay_dxf()

    def _reset_slat_positions(self):
        self.slat_workspace_offsets = {i: {'x': 0, 'y': 0} for i in range(len(self.slats_cam_raw_slats))}
        self.selected_slat_idx = None
        self._slats_cam_overlay_dxf()

    def _slats_cam_log(self, text: str) -> None:
        """Log message to console"""
        if hasattr(self, "slats_cam_console"):
            self.slats_cam_console.insert("end", text + "\n")
            self.slats_cam_console.see("end")
            self.slats_cam_console.update()
        print(text)

    def _slats_cam_browse_stl(self) -> None:
        """Browse for STL file"""
        path = filedialog.askopenfilename(
            title="Select STL File",
            initialdir=str(Path.home()),
            filetypes=[("STL Files", "*.stl"), ("All Files", "*.*")],
        )
        if path:
            self.slats_cam_stl_file = Path(path)
            self.slats_cam_stl_path_var.set(self.slats_cam_stl_file.name)
            self._slats_cam_log(f"> Selected: {path}")

    def _slats_cam_load_and_compute(self) -> None:
        """Computes slats and runs the shelf-nesting script."""
        if not self.slats_cam_stl_file:
            messagebox.showerror("Error", "Select an STL first")
            return

        try:
            self._slats_cam_log(">>> Auto-Packing Slats...")
            n_xy, n_xz = int(self.slats_cam_n_xy_var.get()), int(self.slats_cam_n_xz_var.get())
            data = compute_worldgrid_from_stl(self.slats_cam_stl_file, n_xy=n_xy, n_xz=n_xz)
            
            raw_list = [g for g in (data.get("worldXY_left", []) + data.get("worldXY_right", []) + 
                                    data.get("worldXZ_left", []) + data.get("worldXZ_right", [])) if g and not g.is_empty]

            # Use DXF bounds or default 1000mm
            d_w = self.dxf_dieline.get_info()['bounds_width'] if self.dxf_dieline else 1000
            d_h = self.dxf_dieline.get_info()['bounds_height'] if self.dxf_dieline else 1000

            from gantry.slat_nesting import nest_slats_shelf
            layouts = nest_slats_shelf(raw_list, sheet_w=d_w, sheet_h=d_h)

            self.slats_cam_raw_slats = []
            self.slat_workspace_offsets = {}
            for layout in layouts:
                for part in layout.parts:
                    idx = len(self.slats_cam_raw_slats)
                    self.slats_cam_raw_slats.append(part.placed)
                    self.slat_workspace_offsets[idx] = {'x': 0, 'y': 0}

            self._refresh_slat_library()
            self._slats_cam_overlay_dxf()
        except Exception as e:
            self._slats_cam_log(f"✗ Error: {e}")


    def _world_to_canvas(self, x, y):
        """Helper to map world coordinates (mm) to DXF workspace canvas pixels"""
        if not self.dxf_dieline: return x, y
        
        info = self.dxf_dieline.get_info()
        bounds = info['bounds']  # [min_x, min_y, max_x, max_y]
        canvas = self.slats_cam_dxf_canvas
        
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw <= 1: cw, ch = 1000, 600  # Fallback for initial load
        
        margin = 40
        d_w = max(bounds[2] - bounds[0], 1.0)
        d_h = max(bounds[3] - bounds[1], 1.0)
        fit_scale = min((cw - 2*margin)/d_w, (ch - 2*margin)/d_h)
        
        # Center the DXF and flip Y for screen coordinates
        canvas_x = (cw/2) + (x - (bounds[0] + bounds[2])/2) * fit_scale
        canvas_y = (ch/2) - (y - (bounds[1] + bounds[3])/2) * fit_scale
        return canvas_x, canvas_y

    def _refresh_slat_library(self) -> None:
        """Draws all generated slats side-by-side in the top library bar"""
        canvas = self.slats_cam_preview_canvas
        canvas.delete("all")
        if not self.slats_cam_raw_slats: return
        
        canvas.update()
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w <= 1: w, h = 1000, 120
        
        gap, margin = 10, 20
        # Calculate scale to fit all slats in a single row
        total_world_w = sum(s.bounds[2]-s.bounds[0] for s in self.slats_cam_raw_slats) + (gap * len(self.slats_cam_raw_slats))
        max_world_h = max(s.bounds[3]-s.bounds[1] for s in self.slats_cam_raw_slats)
        scale = min((w - 2*margin)/total_world_w, (h - 2*margin)/max_world_h)
        
        curr_x = margin
        n_xy = int(self.slats_cam_n_xy_var.get())
        
        # Double n_xy because we have both Left and Right sets
        n_xy_total = n_xy * 2
        for i, slat in enumerate(self.slats_cam_raw_slats):
            color = "#0088FF" if i < n_xy_total else "#FF8800"
            b = slat.bounds
            for poly in self._explode_polys(slat):
                pts = []
                for x, y in poly.exterior.coords:
                    # Local normalization for library view
                    pts.extend([curr_x + (x-b[0])*scale, (h/2) - (y-(b[1]+b[3])/2)*scale])
                canvas.create_polygon(pts, fill=color, outline="#444444", width=1, stipple="gray50")
            curr_x += (b[2]-b[0] + gap) * scale

    def _slats_cam_preview_xy(self) -> None:
        """Preview XY slats with spacing to prevent overlapping and show detailed shapes"""
        if not self.slats_cam_raw_slats:
            messagebox.showwarning("Warning", "Load STL first")
            return
        
        canvas = self.slats_cam_preview_canvas
        canvas.delete("all")
        canvas.update()
        
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1: w = 800
        if h <= 1: h = 150
        
        try:
            slats = self.slats_cam_raw_slats
            xy_slats = slats[:len(slats)//2] if len(slats) > 0 else []
            
            if not xy_slats:
                canvas.create_text(w/2, h/2, text="No XY slats", fill="#999999", font=("Arial", 11))
                return

            # 1. Calculate Total World Width for Scaling
            gap = 10.0  # mm spacing between slats
            total_world_w = 0.0
            max_world_h = 0.0
            
            valid_slats = []
            for s in xy_slats:
                if hasattr(s, 'bounds'):
                    b = s.bounds
                    total_world_w += (b[2] - b[0]) + gap
                    max_world_h = max(max_world_h, b[3] - b[1])
                    valid_slats.append(s)
            
            if total_world_w > 0: total_world_w -= gap # Remove final gap
            
            # 2. Determine Scale
            margin = 20
            scale = min((w - 2*margin) / (total_world_w or 100), (h - 2*margin) / (max_world_h or 100))
            
            # 3. Draw Slats with Horizontal Offset
            current_x_cursor = margin
            for slat in valid_slats:
                b = slat.bounds
                slat_w = b[2] - b[0]
                
                for poly in self._explode_polys(slat):
                    coords = list(poly.exterior.coords)
                    if len(coords) < 2: continue
                    
                    flat_pts = []
                    for x, y in coords:
                        # Place X relative to slat start, then add global cursor
                        cv_x = current_x_cursor + (x - b[0]) * scale
                        # Center Y vertically in canvas
                        cv_y = (h / 2) - ((y - (b[1] + b[3]) / 2) * scale)
                        flat_pts.extend([cv_x, cv_y])
                    
                    canvas.create_polygon(flat_pts, outline="#0088FF", fill="#0088FF", 
                                        stipple='gray50', width=1)
                
                # Advance cursor for next slat
                current_x_cursor += (slat_w + gap) * scale
                
            canvas.create_text(10, 10, text=f"XY Slats: {len(xy_slats)}", 
                            fill="#0088FF", font=("Arial", 10), anchor="nw")
            self._slats_cam_log("> XY preview displayed with spacing")
        except Exception as e:
            self._slats_cam_log(f"✗ Preview error: {e}")


    def _slats_cam_preview_xz(self) -> None:
        """Preview XZ slats in embedded canvas with spacing and detailed polygon geometry"""
        if not self.slats_cam_raw_slats:
            messagebox.showwarning("Warning", "Load STL first")
            return
        
        canvas = self.slats_cam_preview_canvas
        canvas.delete("all")
        canvas.update()
        
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1: w = 800
        if h <= 1: h = 150
        
        try:
            slats = self.slats_cam_raw_slats
            # XZ slats are the second half of the generated geometries
            xz_slats = slats[len(slats)//2:] if len(slats) > 0 else []
            
            if not xz_slats:
                canvas.create_text(w/2, h/2, text="No XZ slats", fill="#999999", font=("Arial", 11))
                return

            # 1. Calculate Total World Width for Scaling
            gap = 10.0  # mm spacing between slats in world units
            total_world_w = 0.0
            max_world_h = 0.0
            
            valid_slats = []
            for s in xz_slats:
                if hasattr(s, 'bounds'):
                    b = s.bounds
                    # Width is X (index 0 and 2), Height is Z (index 1 and 3)
                    total_world_w += (b[2] - b[0]) + gap
                    max_world_h = max(max_world_h, b[3] - b[1])
                    valid_slats.append(s)
            
            if total_world_w > 0: total_world_w -= gap # Remove final extra gap
            
            # 2. Determine Scale based on canvas size
            margin = 20
            scale = min((w - 2*margin) / (total_world_w or 100), (h - 2*margin) / (max_world_h or 100))
            
            # 3. Draw Slats with Horizontal Offset cursor
            current_x_cursor = margin
            for slat in valid_slats:
                b = slat.bounds
                slat_w = b[2] - b[0]
                
                # Use the helper to extract polygons for detailed rendering
                for poly in self._explode_polys(slat):
                    coords = list(poly.exterior.coords)
                    if len(coords) < 2: continue
                    
                    flat_pts = []
                    for x, z in coords:
                        # Place X relative to slat start, then add global cursor
                        cv_x = current_x_cursor + (x - b[0]) * scale
                        # Center Z vertically in canvas (note: z acts as the 'y' coordinate in this 2D view)
                        cv_y = (h / 2) - ((z - (b[1] + b[3]) / 2) * scale)
                        flat_pts.extend([cv_x, cv_y])
                    
                    # Render XZ slats in Orange to match the theme
                    canvas.create_polygon(flat_pts, outline="#FF8800", fill="#FF8800", 
                                        stipple='gray50', width=1)
                
                # Advance horizontal cursor for the next slat
                current_x_cursor += (slat_w + gap) * scale
                
            canvas.create_text(10, 10, text=f"XZ Slats: {len(xz_slats)}", 
                            fill="#FF8800", font=("Arial", 10), anchor="nw")
            self._slats_cam_log("> XZ preview displayed with spacing and profiles")
        except Exception as e:
            self._slats_cam_log(f"✗ Preview error: {e}")

    def _slats_cam_show_3d(self) -> None:
        """Show 3D slats preview"""
        if not self.slats_cam_raw_slats:
            messagebox.showwarning("Warning", "Load STL first")
            return

        self._slats_cam_log("> Opening 3D preview... (matplotlib window)")
        messagebox.showinfo("Preview", "3D slat preview\n\n(Visualization would open in separate window)")

    def _slats_cam_select_slat(self, event, canvas, slat_rects):
        """Select a slat for dragging"""
        for slat_id, rect_data in slat_rects.items():
            p1, p2 = rect_data['p1'], rect_data['p2']
            if min(p1[0], p2[0]) <= event.x <= max(p1[0], p2[0]) and \
               min(p1[1], p2[1]) <= event.y <= max(p1[1], p2[1]):
                canvas._selected_slat = {
                    'id': slat_id,
                    'start_x': event.x,
                    'start_y': event.y,
                    'start_offset': canvas._slat_offsets.get(slat_id, {'x': 0, 'y': 0}).copy()
                }
                canvas._last_select = slat_id
                self._slats_cam_log(f"> Selected slat {slat_id}")
                return

    def _slats_cam_drag_slat(self, event, canvas, slat_rects):
        """Drag selected slat"""
        if not canvas._selected_slat:
            return
        
        slat_id = canvas._selected_slat['id']
        dx = event.x - canvas._selected_slat['start_x']
        dy = event.y - canvas._selected_slat['start_y']
        
        new_offset = {
            'x': canvas._selected_slat['start_offset']['x'] + dx,
            'y': canvas._selected_slat['start_offset']['y'] + dy
        }
        
        canvas._slat_offsets[slat_id] = new_offset
        self._slats_cam_overlay_dxf()  # Redraw with new position

    def _slats_cam_release_slat(self, event, canvas):
        """Release selected slat"""
        if canvas._selected_slat:
            slat_id = canvas._selected_slat['id']
            offset = canvas._slat_offsets.get(slat_id, {'x': 0, 'y': 0})
            self._slats_cam_log(f"✓ Slat {slat_id} positioned at offset ({offset['x']:.1f}, {offset['y']:.1f})")
            canvas._selected_slat = None

    def _slats_cam_show_2d(self) -> None:
        """Show 2D slats layout preview"""
        if not self.slats_cam_raw_slats:
            messagebox.showwarning("Warning", "Load STL first")
            return

        self._slats_cam_log("> Opening 2D preview... (matplotlib window)")
        messagebox.showinfo("Preview", "2D slat patterns\n\n(Visualization would open in separate window)")

    def _slats_cam_generate_gcode(self) -> None:
        """Pack slats and generate G-code"""
        if not self.slats_cam_raw_slats:
            messagebox.showerror("Error", "Load STL first")
            return

        thread = threading.Thread(target=self._slats_cam_generate_gcode_worker, daemon=True)
        thread.start()

    def _slats_cam_generate_gcode_worker(self) -> None:
        """Background worker for G-code generation"""
        try:
            self._slats_cam_log("\n>>> Starting G-code generation pipeline...")
            self.slats_cam_status_var.set("Packing slats...")
            self.update()

            # Import pipeline
            try:
                from gantry.slat_layout_rollfeed import pack_slats_roll_feed, normalize_to_cnc_origin
                from slat_toolpaths import geometry_to_knife_segments, chain_segments
                from gantry.roll_feed_cam import RollFeedGantry, build_roll_feed_ops
                from gcode.grblHAL_post import GRBLHALPostProcessor, MachineConfig
                from gcode.machine_ops_types import CutPath
            except ImportError as e:
                self._slats_cam_log(f"✗ Import error: {e}")
                self.slats_cam_status_var.set(f"Error: Missing modules")
                messagebox.showerror("Error", f"Missing required modules: {e}")
                return

            # Get config
            gantry_config = {
                "feed_window_y": self.slats_cam_gantry_vars["feed_window_y"].get(),
                "gantry_width_x": self.slats_cam_gantry_vars["gantry_width_x"].get(),
                "feed_clearance_y": self.slats_cam_gantry_vars["feed_clearance_y"].get(),
            }

            machine_config = {
                "z_safe": self.slats_cam_machine_vars["z_safe"].get(),
                "z_knife": self.slats_cam_machine_vars["z_knife"].get(),
                "z_crease": self.slats_cam_machine_vars["z_knife"].get() / 2,
                "feed_xy": self.slats_cam_machine_vars["feed_xy"].get(),
                "feed_tool": self.slats_cam_machine_vars["feed_tool"].get(),
                "feed_roller": self.slats_cam_machine_vars["feed_roller"].get(),
                "knife_on_cmd": "M3 S12000",
                "knife_off_cmd": "M5",
            }

            # Pack slats
            self._slats_cam_log(f"> Packing {len(self.slats_cam_raw_slats)} slats...")
            self.slats_cam_laid_out_slats = pack_slats_roll_feed(
                self.slats_cam_raw_slats,
                gantry_width_x=gantry_config["gantry_width_x"],
                feed_window_y=gantry_config["feed_window_y"],
            )

            self.slats_cam_laid_out_slats = normalize_to_cnc_origin(
                self.slats_cam_laid_out_slats,
                margin_x=5.0,
                margin_y=0.0,
            )

            self._slats_cam_log(f"✓ Packed {len(self.slats_cam_laid_out_slats)} slats")

            # Generate toolpaths
            self.slats_cam_status_var.set("Generating toolpaths...")
            self._slats_cam_log("> Generating knife toolpaths...")

            knife_segments = []
            for geom in self.slats_cam_laid_out_slats:
                if geom and not geom.is_empty:
                    knife_segments.extend(geometry_to_knife_segments(geom))

            knife_paths = chain_segments(knife_segments)
            self.slats_cam_toolpaths = {
                "knife": knife_paths,
                "crease": [],
            }

            self._slats_cam_log(f"✓ Generated {len(knife_paths)} knife paths ({sum(len(p) for p in knife_paths)} points)")

            # Build operations
            self.slats_cam_status_var.set("Building roll-feed operations...")
            self._slats_cam_log("> Building roll-feed operations...")

            gantry = RollFeedGantry(
                feed_window_y=gantry_config["feed_window_y"],
                gantry_width_x=gantry_config["gantry_width_x"],
                feed_clearance_y=gantry_config["feed_clearance_y"],
            )

            ops, feed_positions = build_roll_feed_ops(self.slats_cam_toolpaths, gantry)
            cut_count = sum(1 for o in ops if isinstance(o, CutPath))

            self._slats_cam_log(f"✓ Built {len(ops)} operations ({cut_count} cut paths, {len(feed_positions)} feed positions)")

            # Emit G-code
            self.slats_cam_status_var.set("Emitting G-code...")
            self._slats_cam_log("> Emitting grblHAL G-code...")

            machine = MachineConfig(
                z_safe=machine_config["z_safe"],
                z_knife=machine_config["z_knife"],
                z_crease=machine_config["z_crease"],
                feed_xy=machine_config["feed_xy"],
                feed_tool=machine_config["feed_tool"],
                feed_roller=machine_config["feed_roller"],
                knife_on_cmd=machine_config["knife_on_cmd"],
                knife_off_cmd=machine_config["knife_off_cmd"],
            )

            post = GRBLHALPostProcessor(machine)
            gcode = post.emit(ops)

            # Save G-code
            output_dir = self.slats_cam_stl_file.parent / "slats_output"
            output_dir.mkdir(parents=True, exist_ok=True)

            gcode_path = output_dir / "slats_roll_feed.nc"
            gcode_path.write_text(gcode)

            lines = len(gcode.split('\n'))
            self._slats_cam_log(f"✓ G-code saved: {gcode_path} ({lines} lines)")

            self.slats_cam_gcode_path = gcode_path
            self.slats_cam_status_var.set(f"✓ Complete: {gcode_path.name}")
            self.slats_cam_stage = "gcode_ready"

            messagebox.showinfo("Success", f"G-code generated!\n\n{gcode_path}\n\n{lines} lines")
            self._slats_cam_log(f"\n>>> PIPELINE COMPLETE\n")

        except Exception as e:
            self._slats_cam_log(f"\n✗ ERROR: {e}\n")
            self.slats_cam_status_var.set(f"Error: {str(e)[:50]}")
            messagebox.showerror("Error", f"Pipeline failed:\n{str(e)}")

    def _slats_cam_open_output(self) -> None:
        """Open output directory"""
        if not self.slats_cam_gcode_path:
            if not self.slats_cam_stl_file:
                messagebox.showwarning("Warning", "No output yet")
                return
            output_dir = self.slats_cam_stl_file.parent / "slats_output"
        else:
            output_dir = self.slats_cam_gcode_path.parent

        if not output_dir.exists():
            messagebox.showwarning("Warning", f"Output directory not found: {output_dir}")
            return

        import subprocess
        import platform

        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(output_dir)])
            elif platform.system() == "Windows":
                subprocess.Popen(["explorer", str(output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(output_dir)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open: {e}")

    def _build_diagnostics_tab(self, parent) -> None:
        """Diagnostics"""
        default_font = ("Arial", 8, "bold")
        big_font = ("Arial", 9, "bold")
        mono_font = ("Courier", 12)

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        info_box = tk.LabelFrame(main, text="Controller Status", bg=PANEL_BG, fg=FG,
                                 font=default_font, padx=2, pady=1, bd=2, relief="solid")
        info_box.pack(fill="x", pady=(0, 8))

        tk.Label(info_box, textvariable=self.state_text, bg=PANEL_BG, fg=FG, font=default_font).pack(anchor="w", pady=2)
        tk.Label(info_box, textvariable=self.machine_pos_text, bg=PANEL_BG, fg=FG, font=default_font).pack(anchor="w", pady=2)
        tk.Label(info_box, textvariable=self.work_pos_text, bg=PANEL_BG, fg=FG, font=default_font).pack(anchor="w", pady=2)
        tk.Label(info_box, textvariable=self.last_status_text, bg=PANEL_BG, fg=FG, font=mono_font, justify="left", wraplength=1400).pack(anchor="w", pady=4)

        btns = tk.Frame(info_box, bg=PANEL_BG)
        btns.pack(anchor="w", pady=(6, 0))

        tk.Button(
            btns, text="Poll Status", command=lambda: self.ctrl.send_realtime(b"?") if self.ctrl.is_connected else None,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            btns, text="Soft Reset", command=self._reset,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            btns, text="Unlock", command=self._unlock,
            bg=BTN_YELLOW, fg=BTN_YELLOW_FG, activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left")

    # ===== HELPER METHODS =====
    def _style_3d_axes(self, ax) -> None:
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        try:
            ax.xaxis.label.set_color("white")
            ax.yaxis.label.set_color("white")
            ax.zaxis.label.set_color("white")
            ax.tick_params(colors="white")
        except Exception:
            pass
        try:
            ax.xaxis.pane.set_facecolor((0.07, 0.07, 0.07, 1.0))
            ax.yaxis.pane.set_facecolor((0.07, 0.07, 0.07, 1.0))
            ax.zaxis.pane.set_facecolor((0.07, 0.07, 0.07, 1.0))
        except Exception:
            pass

    def _set_axes_equal(self, ax, verts: np.ndarray) -> None:
        mins = verts.min(axis=0)
        maxs = verts.max(axis=0)
        center = (mins + maxs) / 2.0
        radius = max(maxs - mins) / 2.0
        if radius <= 0:
            radius = 1.0
        radius *= 1.15

        ax.set_xlim(center[0] - radius, center[0] + radius)
        ax.set_ylim(center[1] - radius, center[1] + radius)
        ax.set_zlim(center[2] - radius, center[2] + radius)

        try:
            ax.set_box_aspect((1, 1, 1))
        except Exception:
            pass

    def _append_console(self, text: str) -> None:
        if hasattr(self, "console") and self.console is not None:
            self.console.insert("end", text + "\n")
            self.console.see("end")

    def _clear_console(self) -> None:
        self.console.delete("1.0", "end")

    # ===== SERIAL / MACHINE =====
    def _refresh_ports(self) -> None:
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _connect(self) -> None:
        port = self.port_var.get().strip()
        baud = self.baud_var.get().strip()
        if not port:
            messagebox.showerror("Error", "Select a serial port.")
            return
        try:
            baud_int = int(baud)
        except ValueError:
            messagebox.showerror("Error", "Invalid baud rate.")
            return
        try:
            self.ctrl.connect(port, baud_int)
            self.polling = True
            self.in_alarm = False
            self.machine_state = "Unknown"
            self.status_text.set(f"Connected: {port} @ {baud_int}")
            self._append_console(f"> Connected to {port} @ {baud_int}")
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))

    def _disconnect(self) -> None:
        self._stop_all_motion_and_jobs()
        self._stop_roller_jog()
        self.polling = False
        self.ctrl.disconnect()
        self.machine_state = "Disconnected"
        self.status_text.set("Disconnected")
        self.state_text.set("State: --")
        self.machine_pos_text.set("MPos: --")
        self.work_pos_text.set("WPos: --")
        self.job_progress_text.set("Job: idle")
        self._append_console("> Disconnected")

    def _send_line(self, line: str) -> None:
        if not self.ctrl.is_connected:
            return
        self.ctrl.write_line(line)
        self._append_console(f">> {line}")

    def _send_mdi(self) -> None:
        line = self.mdi_var.get().strip()
        if not line:
            return
        if self.job_running:
            messagebox.showwarning("Busy", "Cannot send MDI while a job is running.")
            return
        self._send_line(line)
        self.mdi_var.set("")

    def _hold(self) -> None:
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"!")
            self._append_console(">> [HOLD] !")

    def _resume(self) -> None:
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"~")
            self._append_console(">> [RESUME] ~")

    def _reset(self) -> None:
        if self.ctrl.is_connected:
            self._stop_all_motion_and_jobs()
            self.ctrl.send_realtime(b"\x18")
            self._append_console(">> [RESET] Ctrl-X")

    def _force_stop(self) -> None:
        """Emergency stop - kills everything immediately"""
        self._append_console("\n!!! FORCE STOP !!!\n")
        
        # Immediately set flags to stop everything
        self.jogging = False
        self.job_running = False
        self.job_paused = False
        self.job_stopping = True
        self.waiting_for_ack = False
        
        # Cancel jog thread
        self._cancel_jog()
        
        # Send multiple reset signals for safety
        if self.ctrl.is_connected:
            # Send reset (Ctrl-X = 0x18)
            self.ctrl.send_realtime(b"\x18")
            time.sleep(0.05)
            self.ctrl.send_realtime(b"\x18")
            time.sleep(0.05)
            self.ctrl.send_realtime(b"\x18")
            
            # Also send hold signal (! = 0x21)
            self.ctrl.send_realtime(b"!")
            time.sleep(0.1)
            
            self._append_console(">> [FORCE STOP] Sent Ctrl-X (3x) + Hold")
        
        self._append_console(">> All motion stopped\n")
        messagebox.showwarning("FORCE STOP", "Machine emergency stopped!\n\nAll motion halted.\nCheck controller status.")

    def _home(self) -> None:
        if self.job_running:
            return
        self._send_line("$H")

    def _unlock(self) -> None:
        if self.job_running:
            return
        self.in_alarm = False  # Immediately clear alarm flag
        self._send_line("$X")
        # Force a status poll to update machine state
        time.sleep(0.1)
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"?")

    def _light_on(self) -> None:
        if self.job_running:
            return
        self._send_line(LIGHT_ON_CMD)

    def _light_off(self) -> None:
        if self.job_running:
            return
        self._send_line(LIGHT_OFF_CMD)

    def _spindle_on(self) -> None:
        if self.job_running:
            return
        try:
            speed = int(float(self.spindle_speed_var.get()))
            if speed <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Spindle Error", "Enter a spindle speed > 0.")
            return
        self._send_line(f"M3 S{speed}")

    def _spindle_off(self) -> None:
        if self.job_running:
            return
        self._send_line(SPINDLE_OFF_CMD)

    # ===== JOGGING =====
    def _safe_to_jog(self) -> bool:
        if not self.ctrl.is_connected:
            return False
        if self.job_running:
            return False
        if self.in_alarm:
            return False
        return self.machine_state in ("Idle", "Jog")

    def _get_validated_jog_settings(self, axis_moves: Dict[str, int]) -> Optional[JogSettings]:
        axes = set(axis_moves.keys())
        try:
            if axes == {"A"}:
                step = float(self.a_rot_step_var.get())
                feed = float(self.a_rot_feed_var.get())
            elif axes == {"B"}:
                step = float(self.b_rot_step_var.get())
                feed = float(self.b_rot_feed_var.get())
            elif axes == {"C"}:
                step = float(self.c_rot_step_var.get())
                feed = float(self.c_rot_feed_var.get())
            else:
                # XYZ axes
                raw_step = self.jog_step_var.get()
                raw_feed = self.jog_feed_var.get()
                step = float(raw_step)
                feed = float(raw_feed)

            # Ensure positive values
            step = abs(step) if step != 0 else 0.1
            feed = abs(feed) if feed != 0 else 100
            
            settings = JogSettings(step=step, feed=feed)
            return settings  # Always return valid settings
        except ValueError as e:
            # If parse fails, return safe defaults
            return JogSettings(step=1.0, feed=1000)

    def _on_jog_press(self, axis_moves: Dict[str, int], btn: tk.Button) -> None:
        btn.config(bg=BTN_PRESSED)

        # *** CRITICAL: A-AXIS GOES TO ROLLERS ONLY, NEVER TO TEENSY ***
        if set(axis_moves.keys()) == {"A"}:
            forward = axis_moves["A"] > 0
            self._append_console(f"[A-JOG] Button pressed - {('forward' if forward else 'reverse')}")
            self._start_roller_jog(forward=forward)
            return
        
        # All other axes (XYZ) go to Teensy
        self._start_continuous_jog(axis_moves)

    def _on_jog_release(self, btn: tk.Button) -> None:
        btn.config(bg=BTN_NEUTRAL)
        self._stop_roller_jog()
        self._cancel_jog()

    def _start_continuous_jog(self, axis_moves: Dict[str, int]) -> None:
        # SAFETY: Never allow A axis here
        if "A" in axis_moves:
            self._append_console(f"[ERROR] A axis tried to reach Teensy! Blocking...")
            return
        
        if not self._safe_to_jog() or self.jogging:
            return
        self.jogging = True

        def jog_loop() -> None:
            while self.jogging and self.ctrl.is_connected:
                if not self._safe_to_jog(): break

                # THE FIX: Fetch current values from UI entries every single iteration
                live_settings = self._get_validated_jog_settings(axis_moves)
                if not live_settings:
                    time.sleep(0.1)
                    continue

                parts = []
                for axis, direction in axis_moves.items():
                    parts.append(f"{axis}{live_settings.step * direction:.3f}")

                cmd = f"$J=G91 {' '.join(parts)} F{live_settings.feed:.1f}"
                self.ctrl.write_line(cmd)
                time.sleep(self.JOG_REPEAT_S)

        self.jog_thread = threading.Thread(target=jog_loop, daemon=True)
        self.jog_thread.start()

    def _start_roller_jog(self, forward: bool) -> None:
        if not self.rollers:
            self._append_console("[ERROR] RollerController not initialized!")
            return
        
        if self.roller_jogging:
            self._append_console("[ROLLER] Already jogging, ignoring...")
            return

        self.roller_jogging = True
        direction = 'forward' if forward else 'reverse'
        self._append_console(f"[ROLLER] ✓ Jog started - {direction}")
        print(f"[ROLLER] Jog started - {direction}")

        def roller_loop() -> None:
            try:
                start_time = time.time()
                
                while self.roller_jogging:
                    # Get current settings each iteration (user can change speed/step)
                    settings = self._get_validated_jog_settings({"A": 1})
                    
                    # Feed a small chunk per iteration for smooth continuous motion
                    distance_mm = settings.step  # mm per iteration
                    speed_mm_s = max(settings.feed / 60.0, 0.1)
                    
                    # Feed this chunk
                    try:
                        print(f"[ROLLER] Feeding {distance_mm}mm @ {speed_mm_s:.1f}mm/s")
                        self.rollers.feed_distance(
                            distance_mm=distance_mm,
                            speed_mm_s=speed_mm_s,
                            forward=forward,
                        )
                    except Exception as e:
                        self._append_console(f"[ROLLER FEED ERROR] {e}")
                        print(f"[ROLLER FEED ERROR] {e}")
                        self.roller_jogging = False
                        break
                    
                    # Small sleep to allow button release to be responsive
                    time.sleep(0.05)
                
                # Calculate total distance fed
                elapsed = time.time() - start_time
                total_mm = elapsed * (settings.feed / 60.0)  # speed * time
                self._append_console(f"[ROLLER] Jog stopped - fed ~{total_mm:.1f}mm")

            except Exception as exc:
                self._append_console(f"[ROLLER ERROR] {exc}")
            finally:
                try:
                    self.rollers.stop()
                except Exception:
                    pass
                self.roller_jogging = False

        self.roller_jog_thread = threading.Thread(target=roller_loop, daemon=True)
        self.roller_jog_thread.start()


    def _stop_roller_jog(self) -> None:
        self.roller_jogging = False
        try:
            self.rollers.stop()
        except Exception:
            pass

    def _apply_jog_values(self) -> None:
        """Force jog loop to re-read and apply new values"""
        # This is called when user clicks "Apply" button
        # Just validates and shows confirmation
        try:
            # Check XYZ
            step_xyz = float(self.jog_step_var.get())
            feed_xyz = float(self.jog_feed_var.get())
            
            # Check ABC
            step_a = float(self.a_rot_step_var.get())
            feed_a = float(self.a_rot_feed_var.get())
            step_b = float(self.b_rot_step_var.get())
            feed_b = float(self.b_rot_feed_var.get())
            step_c = float(self.c_rot_step_var.get())
            feed_c = float(self.c_rot_feed_var.get())
            
            # All valid
            self._append_console(f">> JOG VALUES UPDATED: XYZ({step_xyz}mm, {feed_xyz}mm/min) ABC(A:{step_a}°/{feed_a}, B:{step_b}°/{feed_b}, C:{step_c}°/{feed_c})")
            messagebox.showinfo("Jog Values", "Jog values applied!\n\nNew values will be used immediately when jogging.")
        except ValueError:
            messagebox.showerror("Input Error", "Invalid jog values. Please enter numbers only.")

    def _cancel_jog(self) -> None:
        if not self.jogging:
            return
        self.jogging = False
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"\x85")
            self._append_console(">> [JOG CANCEL] 0x85")

    # ===== G-CODE =====
    def _load_gcode_file(self) -> None:
        if self.job_running:
            return

        path = filedialog.askopenfilename(
            title="Open G-code File",
            filetypes=[
                ("G-code files", "*.nc *.gcode *.tap *.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()

            cleaned = []
            for line in raw_lines:
                s = line.strip()
                if not s:
                    continue
                if ";" in s:
                    s = s.split(";", 1)[0].strip()
                if s.startswith("(") and s.endswith(")"):
                    continue
                if s:
                    cleaned.append(s)

            self.gcode_lines = cleaned
            self.current_line_index = 0
            self.gcode_segments, self.gcode_bounds = GCodeParser.parse_lines(cleaned)
            
            # Calculate estimated time
            self._calculate_estimated_time()
            self._update_preview_time_display()
            
            self.file_text.set(os.path.basename(path))
            self.job_progress_text.set(f"Job: ready ({len(cleaned)} lines)")
            self._append_console(f"> Loaded G-code: {path}")
            self._append_console(f"> {len(cleaned)} lines | {len(self.gcode_segments)} segments")
            
            # Update preview displays
            self.preview_segment_var.set(f"Segments: 0/{len(self.gcode_segments)} (0%)")
            self.preview_scrubber_var.set(0.0)
            self.preview_scrub_index = 0.0
            
            self._update_gcode_viewer()
            self._draw_toolpath_preview()
            
        except Exception as exc:
            messagebox.showerror("File Error", str(exc))

    def _update_gcode_viewer(self) -> None:
        if not hasattr(self, "gcode_viewer"):
            return
        self.gcode_viewer.config(state="normal")
        self.gcode_viewer.delete("1.0", "end")
        for i, line in enumerate(self.gcode_lines, 1):
            self.gcode_viewer.insert("end", f"{i:5d}: {line}\n")
        self.gcode_viewer.config(state="disabled")

    def _clear_preview(self) -> None:
        canvas = getattr(self, 'preview_canvas_2d', None) or getattr(self, 'preview_canvas', None)
        if canvas is not None:
            canvas.delete("all")
        #self.preview_info_text.set("No preview loaded")

    def _draw_toolpath_preview(self) -> None:
        # Get correct canvas (works with both old and new unified tab)
        canvas = getattr(self, 'preview_canvas_2d', None) or getattr(self, 'preview_canvas', None)
        if canvas is None or not self.gcode_segments:
            return

        canvas.delete("all")

        segments = [((seg.start[0], seg.start[1]), (seg.end[0], seg.end[1]), seg.motion_type)
                   for seg in self.gcode_segments]

        if not segments:
            return

        xs = [p[0] for seg in segments for p in (seg[0], seg[1])]
        ys = [p[1] for seg in segments for p in (seg[0], seg[1])]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        canvas.update_idletasks()
        cw = max(canvas.winfo_width(), 200)
        ch = max(canvas.winfo_height(), 200)

        pad = 30
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        scale = min((cw - 2 * pad) / span_x, (ch - 2 * pad) / span_y)

        def tx(x: float) -> float:
            return pad + (x - min_x) * scale

        def ty(y: float) -> float:
            return ch - pad - (y - min_y) * scale

        canvas.create_rectangle(1, 1, cw - 2, ch - 2, outline="#666666")

        if min_x <= 0 <= max_x and min_y <= 0 <= max_y:
            ox, oy = tx(0.0), ty(0.0)
            canvas.create_line(ox - 8, oy, ox + 8, oy, fill="#FFD54A", width=2)
            canvas.create_line(ox, oy - 8, ox, oy + 8, fill="#FFD54A", width=2)

        count_g0, count_g1 = 0, 0
        for (x1, y1), (x2, y2), motion in segments:
            color = "#6FA8FF" if motion == "G0" else "#5FD16F"
            if motion == "G0":
                count_g0 += 1
            else:
                count_g1 += 1
            canvas.create_line(tx(x1), ty(y1), tx(x2), ty(y2), fill=color, width=2)

        self.preview_info_text.set(
            f"Segments: {len(segments)} | G0: {count_g0} | G1: {count_g1} | "
            f"X[{min_x:.2f}, {max_x:.2f}] Y[{min_y:.2f}, {max_y:.2f}]"
        )

    def _draw_gcode_3d_preview(self) -> None:
        if not self.gcode_segments:
            messagebox.showwarning("Preview", "Load a G-code file first.")
            return

        if self.preview_3d_ax is None:
            messagebox.showerror("Error", "3D preview not initialized. Try switching tabs and back.")
            return

        ax = self.preview_3d_ax
        ax.clear()
        self._style_3d_axes(ax)

        # --- FORCE FULL-FIGURE USAGE ---
        self.preview_3d_figure.subplots_adjust(left=0, right=1, bottom=0, top=1)

        # Make axes fill almost everything
        ax.set_position([-0.02, -0.05, 1.05, 1.1])

        # Soften the 3D box/grid a lot
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis._axinfo["grid"]["color"] = (1, 1, 1, 0.06)
            axis._axinfo["grid"]["linewidth"] = 0.8
            axis._axinfo["axisline"]["color"] = (1, 1, 1, 0.15)

        # Remove pane fill so the box is less obstructive
        ax.xaxis.pane.fill = False
        ax.yaxis.pane.fill = False
        ax.zaxis.pane.fill = False

        # iOSender-style colors
        colors = {
            "G0": "#4EA1FF",  # Rapid
            "G1": "#FF5A3D",  # Cut
            "G2": "#FFD54A",  # Arc CW
            "G3": "#5FD16F",  # Arc CCW
            "Z":  "#B36AE2",  # Z-only motion
        }

        motion_types_seen = set()
        segment_count = 0

        # Determine current segment index (either from job or from scrubber)
        if self.job_running or self.job_paused:
            current_idx = self.current_line_index
        else:
            # Use scrubber position for preview playback
            current_idx = int(self.preview_scrub_index * len(self.gcode_segments))
        
        # Track tool position at current segment
        tool_pos = [0.0, 0.0, 0.0]

        for idx, seg in enumerate(self.gcode_segments):
            is_z_only = (
                abs(seg.start[0] - seg.end[0]) < 0.01 and
                abs(seg.start[1] - seg.end[1]) < 0.01 and
                abs(seg.start[2] - seg.end[2]) > 0.01
            )

            motion_type = "Z" if is_z_only else seg.motion_type
            motion_types_seen.add(motion_type)
            color = colors.get(motion_type, "#FFFFFF")

            # Determine if segment is executed, current, or remaining
            if idx < current_idx:
                # Executed segment - dimmed
                alpha = 0.4
                linewidth = 1.8
            elif idx == current_idx:
                # Current segment - bright highlight
                alpha = 1.0
                linewidth = 3.5
                color = "#00FF00"  # Bright green for current
            else:
                # Remaining segment - normal
                alpha = 0.9
                linewidth = 2.2

            ax.plot(
                [seg.start[0], seg.end[0]],
                [seg.start[1], seg.end[1]],
                [seg.start[2], seg.end[2]],
                color=color,
                linewidth=linewidth,
                alpha=alpha,
            )
            segment_count += 1
            
            # Update tool position as we progress
            if idx <= current_idx:
                tool_pos = list(seg.end[:3])

        # Draw tool position marker (sphere at current position)
        if tool_pos != [0.0, 0.0, 0.0] or current_idx > 0:
            u = np.linspace(0, 2 * np.pi, 12)
            v = np.linspace(0, np.pi, 8)
            x = 3 * np.outer(np.cos(u), np.sin(v)) + tool_pos[0]
            y = 3 * np.outer(np.sin(u), np.sin(v)) + tool_pos[1]
            z = 3 * np.outer(np.ones(np.size(u)), np.cos(v)) + tool_pos[2]
            
            ax.plot_surface(x, y, z, color="#00FF00", alpha=0.7, edgecolor="none")
            
            # Store tool position for UI updates
            self.current_tool_pos = tool_pos

        if self.gcode_segments:
            all_pts = np.array([seg.start + seg.end for seg in self.gcode_segments])
            pts_3d = all_pts.reshape(-1, 6)[:, :3]
            if len(pts_3d) > 0:
                xmin = float(pts_3d[:, 0].min())
                xmax = float(pts_3d[:, 0].max())
                ymin = float(pts_3d[:, 1].min())
                ymax = float(pts_3d[:, 1].max())
                zmin = float(pts_3d[:, 2].min())
                zmax = float(pts_3d[:, 2].max())

                xspan = max(xmax - xmin, 1.0)
                yspan = max(ymax - ymin, 1.0)
                zspan = max(zmax - zmin, 1.0)

                xpad = 0.05 * xspan
                ypad = 0.05 * yspan
                zpad = 0.05 * zspan

                ax.set_xlim(xmin - xpad, xmax + xpad)
                ax.set_ylim(ymin - ypad, ymax + ypad)
                ax.set_zlim(zmin - zpad, zmax + zpad)

                # Z ticks every 5
                start = 5 * np.floor(zmin / 5)
                end   = 5 * np.ceil(zmax / 5)
                ax.set_zticks(np.arange(start, end + 5, 5))

                # preserve true distance proportions without inflating Z
                ax.set_box_aspect([xspan, yspan, zspan])

        # Better default angle: flatter / less towering
        ax.view_init(elev=22, azim=45)

        # Legend with progress info
        if motion_types_seen:
            from matplotlib.lines import Line2D

            legend_labels = {
                "G0": "Rapid (G0)",
                "G1": "Cut (G1)",
                "G2": "Arc CW (G2)",
                "G3": "Arc CCW (G3)",
                "Z": "Z Motion",
            }

            legend_elements = []
            for mtype in sorted(motion_types_seen):
                legend_elements.append(
                    Line2D(
                        [0], [0],
                        color=colors.get(mtype, "#FFFFFF"),
                        lw=2.8,
                        label=legend_labels.get(mtype, mtype),
                    )
                )
            
            # Add progress indicator to legend
            progress_pct = (current_idx / max(len(self.gcode_segments), 1)) * 100
            legend_elements.append(
                Line2D(
                    [0], [0],
                    color="#00FF00",
                    lw=3.0,
                    label=f"Tool Position ({progress_pct:.1f}%)",
                )
            )

            leg = ax.legend(
                handles=legend_elements,
                loc="upper left",
                bbox_to_anchor=(0.8, 0.8),   # push OUTSIDE
                borderaxespad=0.0,
                framealpha=0.9,
                facecolor="#1A1A1A",
                edgecolor=(1, 1, 1, 0.2),
                fontsize=10,
            )
            for text in leg.get_texts():
                text.set_color("white")

        self.preview_3d_canvas.draw()
        self._append_console(f"> 3D preview: {segment_count} segments, Tool at {tool_pos[0]:.2f},{tool_pos[1]:.2f},{tool_pos[2]:.2f}")

        if self.preview_mode.get() == "3d":
            self._animate_3d_view()

    def _clear_gcode_3d_preview(self) -> None:
        if self.preview_3d_ax is not None:
            self.preview_3d_ax.clear()
            self._style_3d_axes(self.preview_3d_ax)
            self.preview_3d_canvas.draw()
        # Cancel animation if running
        if self.preview_3d_animation_id is not None:
            self.after_cancel(self.preview_3d_animation_id)
            self.preview_3d_animation_id = None

    def _toggle_3d_rotation(self) -> None:
        """Toggle auto-rotation on/off"""
        self.preview_3d_rotation = not self.preview_3d_rotation
        if not self.preview_3d_rotation and self.preview_3d_animation_id is not None:
            self.after_cancel(self.preview_3d_animation_id)
            self.preview_3d_animation_id = None
            self.preview_3d_canvas.draw_idle()
        elif self.preview_3d_rotation and self.preview_3d_ax is not None:
            self._animate_3d_view()
    
    def _calculate_estimated_time(self) -> None:
        """Calculate estimated job time from segments and feed rates"""
        if not self.gcode_segments:
            self.preview_estimated_time = 0.0
            return
        
        total_time = 0.0
        try:
            feed_rate = float(self.jog_feed_var.get())
            if feed_rate <= 0:
                feed_rate = 1000.0  # Fallback
        except:
            feed_rate = 1000.0
        
        for seg in self.gcode_segments:
            # Calculate distance
            dx = seg.end[0] - seg.start[0]
            dy = seg.end[1] - seg.start[1]
            dz = seg.end[2] - seg.start[2]
            distance = (dx**2 + dy**2 + dz**2) ** 0.5
            
            # For G0 (rapid), assume 2x speed
            if seg.motion_type == "G0":
                time_for_seg = distance / (feed_rate * 2) * 60
            else:
                time_for_seg = distance / feed_rate * 60
            
            total_time += time_for_seg
        
        self.preview_estimated_time = total_time

    def _update_preview_time_display(self) -> None:
        """Update the time display in the preview"""
        minutes = int(self.preview_estimated_time // 60)
        seconds = int(self.preview_estimated_time % 60)
        self.preview_time_var.set(f"Time: {minutes:02d}:{seconds:02d}")

    def _preview_play(self) -> None:
        """Start playback of the preview"""
        if not self.gcode_segments:
            messagebox.showwarning("Preview", "Load a G-code file first")
            return
        
        self.preview_is_playing = True
        self.preview_play_btn.config(state="disabled")
        self.preview_pause_btn.config(state="normal")
        self._animate_preview_playback()

    def _preview_pause(self) -> None:
        """Pause playback"""
        self.preview_is_playing = False
        self.preview_play_btn.config(state="normal")
        self.preview_pause_btn.config(state="disabled")
        if self.preview_animation_id is not None:
            self.after_cancel(self.preview_animation_id)
            self.preview_animation_id = None

    def _preview_stop(self) -> None:
        """Stop and reset playback"""
        self.preview_is_playing = False
        self.preview_scrubber_var.set(0.0)
        self.preview_scrub_index = 0.0
        self.preview_play_btn.config(state="normal")
        self.preview_pause_btn.config(state="disabled")
        if self.preview_animation_id is not None:
            self.after_cancel(self.preview_animation_id)
            self.preview_animation_id = None
        self._preview_scrubber_moved("0")

    def _preview_step_frame(self) -> None:
        """Step forward one segment"""
        if not self.gcode_segments:
            return
        
        segments_count = len(self.gcode_segments)
        current_idx = int(self.preview_scrub_index * segments_count)
        current_idx = min(current_idx + 1, segments_count)
        self.preview_scrub_index = current_idx / max(segments_count, 1)
        self.preview_scrubber_var.set(self.preview_scrub_index * 100)
        self._preview_scrubber_moved(str(self.preview_scrub_index * 100))

    def _update_preview_speed(self) -> None:
        """Update playback speed from dropdown"""
        speed_str = self.preview_speed_var.get().replace("x", "")
        try:
            self.preview_playback_speed = float(speed_str)
        except:
            self.preview_playback_speed = 1.0

    def _animate_preview_playback(self) -> None:
        """Animate the preview playback"""
        if not self.preview_is_playing or not self.gcode_segments:
            return
        
        # Advance the scrubber by a small amount based on speed
        segments_count = len(self.gcode_segments)
        increment = (self.preview_playback_speed / segments_count) * 0.05  # 50ms steps
        new_pos = self.preview_scrub_index + increment
        
        if new_pos >= 1.0:
            # Playback complete
            new_pos = 1.0
            self.preview_is_playing = False
            self.preview_play_btn.config(state="normal")
            self.preview_pause_btn.config(state="disabled")
        
        self.preview_scrub_index = new_pos
        self.preview_scrubber_var.set(self.preview_scrub_index * 100)
        self._preview_scrubber_moved(str(self.preview_scrub_index * 100))
        
        if self.preview_is_playing:
            # Schedule next frame (50ms)
            self.preview_animation_id = self.after(50, self._animate_preview_playback)

    def _preview_scrubber_moved(self, val) -> None:
        """Handle scrubber position change"""
        try:
            scrub_val = float(val)
            self.preview_scrub_index = scrub_val / 100.0
        except:
            return
        
        # Update current line index for preview rendering
        if self.gcode_segments:
            self.current_line_index = int(self.preview_scrub_index * len(self.gcode_segments))
            
            # Update segment display
            current_seg = self.current_line_index
            total_segs = len(self.gcode_segments)
            pct = int((self.preview_scrub_index) * 100)
            self.preview_segment_var.set(f"Segments: {current_seg}/{total_segs} ({pct}%)")
        
        # Refresh preview
        try:
            if self.preview_mode.get() == "3d":
                self._draw_gcode_3d_preview()
            else:
                self._draw_toolpath_preview()
        except:
            pass
    
    def _animate_3d_view(self) -> None:
        """Auto-rotate 3D view - called repeatedly"""
        if not self.preview_3d_rotation or self.preview_3d_ax is None:
            return
        
        # Increment azimuth by 1 degree each frame
        self.preview_3d_azim = (self.preview_3d_azim + 1) % 360
        
        # Update view
        self.preview_3d_ax.view_init(elev=self.preview_3d_ax.elev, azim=self.preview_3d_azim)
        self.preview_3d_canvas.draw_idle()
        
        # Schedule next frame (50ms = 20fps)
        self.preview_3d_animation_id = self.after(50, self._animate_3d_view)
    
    
    def _adjust_3d_view(self, azim_delta: float, elev_delta: float) -> None:
        """Manually adjust 3D view angle"""
        if self.preview_3d_ax is None:
            return
        
        # Stop auto-rotation when manually adjusting
        if self.preview_3d_animation_id is not None:
            self.after_cancel(self.preview_3d_animation_id)
            self.preview_3d_animation_id = None
            self.preview_3d_rotation = False
        
        # Get current angles
        elev = self.preview_3d_ax.elev + elev_delta
        azim = (self.preview_3d_azim + azim_delta) % 360
        
        # Clamp elevation
        elev = max(0, min(90, elev))
        
        self.preview_3d_azim = azim
        self.preview_3d_ax.view_init(elev=elev, azim=azim)
        self.preview_3d_canvas.draw_idle()
    
    def _adjust_3d_zoom(self, factor: float) -> None:
        """Zoom 3D view in/out"""
        if self.preview_3d_ax is None:
            return
        
        # Get current limits
        xlim = self.preview_3d_ax.get_xlim()
        ylim = self.preview_3d_ax.get_ylim()
        zlim = self.preview_3d_ax.get_zlim()
        
        # Calculate center
        x_center = (xlim[0] + xlim[1]) / 2
        y_center = (ylim[0] + ylim[1]) / 2
        z_center = (zlim[0] + zlim[1]) / 2
        
        # Calculate new half-widths
        x_half = (xlim[1] - xlim[0]) / (2 * factor)
        y_half = (ylim[1] - ylim[0]) / (2 * factor)
        z_half = (zlim[1] - zlim[0]) / (2 * factor)
        
        # Set new limits
        self.preview_3d_ax.set_xlim(x_center - x_half, x_center + x_half)
        self.preview_3d_ax.set_ylim(y_center - y_half, y_center + y_half)
        self.preview_3d_ax.set_zlim(z_center - z_half, z_center + z_half)
        self.preview_3d_canvas.draw_idle()

    def _adjust_mesh_view(self, azim_delta: float, elev_delta: float) -> None:
        """Manually adjust mesh 3D view angle"""
        if self.mesh_ax is None:
            return
        
        # Update angles
        self.mesh_elev = max(0, min(90, self.mesh_elev + elev_delta))
        self.mesh_azim = (self.mesh_azim + azim_delta) % 360
        
        self.mesh_ax.view_init(elev=self.mesh_elev, azim=self.mesh_azim)
        self.mesh_canvas.draw_idle()
    
    def _adjust_mesh_zoom(self, factor: float) -> None:
        """Zoom mesh view in/out"""
        if self.mesh_ax is None:
            return
        
        # Get current limits
        xlim = self.mesh_ax.get_xlim()
        ylim = self.mesh_ax.get_ylim()
        zlim = self.mesh_ax.get_zlim()
        
        # Calculate center
        x_center = (xlim[0] + xlim[1]) / 2
        y_center = (ylim[0] + ylim[1]) / 2
        z_center = (zlim[0] + zlim[1]) / 2
        
        # Calculate new half-widths
        x_half = (xlim[1] - xlim[0]) / (2 * factor)
        y_half = (ylim[1] - ylim[0]) / (2 * factor)
        z_half = (zlim[1] - zlim[0]) / (2 * factor)
        
        # Set new limits
        self.mesh_ax.set_xlim(x_center - x_half, x_center + x_half)
        self.mesh_ax.set_ylim(y_center - y_half, y_center + y_half)
        self.mesh_ax.set_zlim(z_center - z_half, z_center + z_half)
        self.mesh_canvas.draw_idle()

    def _set_mesh_view(self, elev: float, azim: float) -> None:
        """Set mesh view to a preset angle"""
        if self.mesh_ax is None:
            return
        self.mesh_elev = elev
        self.mesh_azim = azim
        self.mesh_ax.view_init(elev=self.mesh_elev, azim=self.mesh_azim)
        self.mesh_canvas.draw_idle()

    def _reset_mesh_view(self) -> None:
        """Reset mesh view to default isometric"""
        self._set_mesh_view(20, 35)

    def _zoom_slats_2d(self, factor: float) -> None:
        """Zoom all 4 slats 2D subplots"""
        if self.slats_2d_figure is None:
            return
        
        self.slats_2d_zoom_level *= factor
        
        # Get all 4 axes from the figure
        axes = self.slats_2d_figure.get_axes()
        if len(axes) < 4:
            return
        
        for ax in axes:
            # Get current limits
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            
            # Calculate center
            x_center = (xlim[0] + xlim[1]) / 2
            y_center = (ylim[0] + ylim[1]) / 2
            
            # Calculate new half-widths
            x_half = (xlim[1] - xlim[0]) / (2 * factor)
            y_half = (ylim[1] - ylim[0]) / (2 * factor)
            
            # Set new limits
            ax.set_xlim(x_center - x_half, x_center + x_half)
            ax.set_ylim(y_center - y_half, y_center + y_half)
        
        self.slats_2d_canvas.draw_idle()
    
    def _reset_slats_2d_zoom(self) -> None:
        """Reset 2D slats zoom to default"""
        self.slats_2d_zoom_level = 1.0
        # Redraw to reset zoom
        if self.slats_data:
            self._draw_slats_2d_layouts()

    def _load_vision_images(self) -> None:
        files = filedialog.askopenfilenames(
            title="Load Vision Images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")],
        )
        if not files:
            return
        self.vision_images = list(files)
        self.vision_info_text.set(f"Loaded {len(self.vision_images)} image(s)")
        self._append_console(f"> Loaded {len(self.vision_images)} vision images")

    def _stitch_vision_images(self) -> None:
        if not self.vision_images:
            messagebox.showwarning("Vision", "Load images first.")
            return
        self._append_console(f"> [TODO] Stitching {len(self.vision_images)} images...")
        self.vision_info_text.set(f"Stitching {len(self.vision_images)} images...")
        messagebox.showinfo("Vision", "Image stitching not yet implemented.\n\nTODO: Use OpenCV for stitching.")

    def _clear_vision_images(self) -> None:
        self.vision_images = []
        self.vision_info_text.set("No vision images loaded")
        self._append_console("> Cleared vision images")

    # ===== DXF =====
    def _load_dxf_file(self) -> None:
        """Load DXF die-line file"""
        if not HAS_DXF_HANDLER:
            messagebox.showerror("Error", "DXF handler module not available.")
            return

        path = filedialog.askopenfilename(
            title="Open DXF File",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            self.dxf_dieline = DXFDieline(Path(path))
            self.dxf_file_path = path  # Store the path
            info = self.dxf_dieline.get_info()
            self.dxf_info_text.set(
                f"{Path(path).name} | Entities: {info['entity_count']} | "
                f"Width: {info['bounds_width']:.2f}mm X Height: {info['bounds_height']:.2f}mm"
            )
            self._append_console(f"> Loaded DXF: {path}")
            self._append_console(f"> Entities: {info['entity_count']} | Bounds: {info['bounds']}")
            self._reset_dxf_transform()
            self._draw_dxf_on_canvas()  # Draw it!
        except Exception as exc:
            messagebox.showerror("DXF Error", str(exc))

    def _auto_register_dxf(self) -> None:
        """Attempt auto-registration of DXF to vision"""
        if not self.dxf_dieline:
            messagebox.showwarning("DXF", "Load a DXF file first.")
            return
        if not self.vision_images:
            messagebox.showwarning("Vision", "Load vision images first.")
            return

        result = VisionDXFAligner.auto_register(Path(self.vision_images[0]), self.dxf_dieline)
        msg = VisionDXFAligner.manual_placement_ui_hints() if result['confidence'] == 0.0 else str(result)
        messagebox.showinfo("Auto-Register", msg)
        self._append_console(f"> Auto-register result: {result}")

    def _apply_dxf_transform(self) -> None:
        """Apply transformations to DXF"""
        if not self.dxf_dieline:
            messagebox.showwarning("DXF", "Load a DXF file first.")
            return

        try:
            tx = float(self.dxf_tx_var.get())
            ty = float(self.dxf_ty_var.get())
            rot = float(self.dxf_rot_var.get())
            scale_val = float(self.dxf_scale_var.get())

            self.dxf_dieline.translate(tx, ty)
            self.dxf_dieline.rotate(rot)
            if scale_val != 1.0:
                self.dxf_dieline.scale_geom(scale_val, scale_val)

            self._append_console(f"> DXF Transform: TX={tx} TY={ty} ROT={rot} SCALE={scale_val}")
            self._draw_dxf_on_canvas()  # Redraw with new transform
        except ValueError:
            messagebox.showerror("Transform Error", "Invalid transform values")

    def _reset_dxf_transform(self) -> None:
        """Reset DXF transformations"""
        if not self.dxf_dieline:
            return
        self.dxf_dieline.reset_transform()
        self.dxf_tx_var.set("0.0")
        self.dxf_ty_var.set("0.0")
        self.dxf_rot_var.set("0.0")
        self.dxf_scale_var.set("1.0")
        self._append_console("> DXF transform reset")

    def _dxf_fit_view(self) -> None:
        """Auto-fit DXF to view"""
        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0
        self.dxf_canvas_pan_y = 0
        self._append_console("> DXF view reset")
        self._draw_dxf_on_canvas()

    def _zoom_dxf(self, direction: int) -> None:
        """Zoom DXF: direction > 0 = zoom in, < 0 = zoom out"""
        if not self.dxf_dieline:
            return
        
        zoom_factor = 1.2 if direction > 0 else 0.8
        new_zoom = self.dxf_canvas_zoom * zoom_factor
        
        if 0.1 < new_zoom < 10.0:
            self.dxf_canvas_zoom = new_zoom
            self._draw_dxf_on_canvas()
            self._append_console(f"> Zoom: {self.dxf_canvas_zoom:.2f}x")

    def _dxf_canvas_zoom(self, event) -> None:
        """Handle mouse wheel zoom on BOTH canvases simultaneously."""
        zoom_factor = 1.1 if (event.num == 4 or event.delta > 0) else 0.9
        self.dxf_canvas_zoom = max(0.1, min(10.0, self.dxf_canvas_zoom * zoom_factor))
        
        self._draw_dxf_on_canvas()        # Redraw Vision Tab
        self._slats_cam_render_workspace() # Redraw Slats Tab

    def _dxf_canvas_pan_move(self, event) -> None:
        """Pan BOTH canvases while dragging (Supports Touch & Mouse)."""
        if not hasattr(self.vision_dxf_canvas, '_pan_x'): return
        dx = event.x - self.vision_dxf_canvas._pan_x
        dy = event.y - self.vision_dxf_canvas._pan_y
        
        self.dxf_canvas_pan_x += dx
        self.dxf_canvas_pan_y += dy
        self.vision_dxf_canvas._pan_x = event.x
        self.vision_dxf_canvas._pan_y = event.y
        
        self._draw_dxf_on_canvas()
        self._slats_cam_render_workspace()

    def _dxf_canvas_pan_start(self, event) -> None:
        """Start pan"""
        self.vision_dxf_canvas._pan_x = event.x
        self.vision_dxf_canvas._pan_y = event.y

    def _dxf_canvas_pan_move(self, event) -> None:
        """Pan canvas while dragging"""
        if not hasattr(self.vision_dxf_canvas, '_pan_x'):
            return
        
        dx = event.x - self.vision_dxf_canvas._pan_x
        dy = event.y - self.vision_dxf_canvas._pan_y
        
        self.dxf_canvas_pan_x += dx
        self.dxf_canvas_pan_y += dy
        
        self.vision_dxf_canvas._pan_x = event.x
        self.vision_dxf_canvas._pan_y = event.y
        
        self._draw_dxf_on_canvas()

    def _dxf_canvas_pan_end(self, event) -> None:
        """End pan"""
        if hasattr(self.vision_dxf_canvas, '_pan_x'):
            delattr(self.vision_dxf_canvas, '_pan_x')
            delattr(self.vision_dxf_canvas, '_pan_y')

    def _draw_dxf_on_canvas(self) -> None:
        """Draw loaded DXF on canvas with current transforms"""
        if not self.dxf_dieline:
            return
        
        canvas = self.vision_dxf_canvas
        canvas.delete("all")
        
        # Force canvas to render and get actual dimensions
        canvas.update()
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width, canvas_height = 800, 600
        
        try:
            # Get DXF info and bounds
            info = self.dxf_dieline.get_info()
            bounds = info['bounds']  # (min_x, min_y, max_x, max_y)
            dxf_width = bounds[2] - bounds[0]
            dxf_height = bounds[3] - bounds[1]
            
            if dxf_width <= 0 or dxf_height <= 0:
                canvas.create_text(canvas_width/2, canvas_height/2, 
                                 text="Invalid DXF bounds", fill="#FF0000", font=("Arial", 14))
                return
            
            # Calculate fit scale
            margin = 40
            scale_x = (canvas_width - 2 * margin) / dxf_width if dxf_width > 0 else 1.0
            scale_y = (canvas_height - 2 * margin) / dxf_height if dxf_height > 0 else 1.0
            fit_scale = min(scale_x, scale_y) * self.dxf_canvas_zoom
            
            # Center offset with pan
            cx = canvas_width / 2 + self.dxf_canvas_pan_x
            cy = canvas_height / 2 + self.dxf_canvas_pan_y
            
            # Draw grid
            for x in range(0, canvas_width, 50):
                canvas.create_line(x, 0, x, canvas_height, fill="#222222", width=1)
            for y in range(0, canvas_height, 50):
                canvas.create_line(0, y, canvas_width, y, fill="#222222", width=1)
            
            # Draw center crosshair
            canvas.create_line(cx - 20, cy, cx + 20, cy, fill="#555555", width=1)
            canvas.create_line(cx, cy - 20, cx, cy + 20, fill="#555555", width=1)
            
            # Get transform values
            try:
                tx = float(self.dxf_tx_var.get()) if self.dxf_tx_var.get() else 0.0
                ty = float(self.dxf_ty_var.get()) if self.dxf_ty_var.get() else 0.0
                rot = float(self.dxf_rot_var.get()) if self.dxf_rot_var.get() else 0.0
                scale = float(self.dxf_scale_var.get()) if self.dxf_scale_var.get() else 1.0
            except ValueError:
                tx = ty = rot = 0.0
                scale = 1.0
            
            # Try to draw using ezdxf if available
            try:
                import ezdxf
                doc = ezdxf.readfile(str(self.dxf_file_path))
                msp = doc.modelspace()
                
                entity_count = 0
                for entity in msp:
                    try:
                        import math
                        rad = math.radians(rot)
                        cos_r, sin_r = math.cos(rad), math.sin(rad)
                        
                        def transform_point(p):
                            # Normalize to bounds, apply scale/rotation/translation
                            x = (p[0] - bounds[0]) * scale * fit_scale
                            y = (p[1] - bounds[1]) * scale * fit_scale
                            # Apply rotation around center
                            x2 = x * cos_r - y * sin_r + tx * fit_scale
                            y2 = x * sin_r + y * cos_r + ty * fit_scale
                            return cx + x2, cy + y2
                        
                        if entity.dxftype() == 'LINE':
                            p1 = entity.dxf.start
                            p2 = entity.dxf.end
                            pt1 = transform_point(p1)
                            pt2 = transform_point(p2)
                            canvas.create_line(pt1[0], pt1[1], pt2[0], pt2[1], fill="#00FF00", width=2)
                            entity_count += 1
                        
                        elif entity.dxftype() == 'LWPOLYLINE':
                            points = list(entity.get_points())
                            if len(points) > 1:
                                transformed = [transform_point(p) for p in points]
                                for i in range(len(transformed) - 1):
                                    canvas.create_line(transformed[i][0], transformed[i][1], 
                                                     transformed[i+1][0], transformed[i+1][1], 
                                                     fill="#00FF00", width=2)
                                entity_count += 1
                        
                        elif entity.dxftype() == 'POLYLINE':
                            points = [v.dxf.location for v in entity.vertices]
                            if len(points) > 1:
                                transformed = [transform_point(p) for p in points]
                                for i in range(len(transformed) - 1):
                                    canvas.create_line(transformed[i][0], transformed[i][1], 
                                                     transformed[i+1][0], transformed[i+1][1], 
                                                     fill="#00FF00", width=2)
                                entity_count += 1
                    
                    except Exception as e:
                        pass  # Skip entities we can't draw
                
                if entity_count > 0:
                    self._append_console(f"✓ Drew {entity_count} DXF entities on canvas")
                else:
                    canvas.create_text(cx, cy, text="No drawable entities found", 
                                     fill="#FFFF00", font=("Arial", 12))
                    
            except ImportError:
                canvas.create_text(cx, cy, text="Install ezdxf to view DXF:\npip install ezdxf", 
                                 fill="#FFFF00", font=("Arial", 11))
                self._append_console("! ezdxf not installed - cannot draw DXF")
                
        except Exception as exc:
            self._append_console(f"! DXF draw error: {exc}")
            canvas.create_text(canvas_width/2, canvas_height/2, 
                             text=f"Error: {str(exc)[:50]}", fill="#FF0000", font=("Arial", 10))

    # ===== MESH & SLATS =====
    def _load_scan_mesh_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Scan Mesh",
            filetypes=[("Mesh files", "*.stl *.obj"), ("STL", "*.stl"), ("OBJ", "*.obj"), ("All", "*.*")],
        )
        if not path:
            return

        try:
            mesh = trimesh.load_mesh(path, process=False)
            self.scan_mesh_path = path
            self.raw_mesh = mesh
            self.slats_data = None

            bounds = mesh.bounds
            size = bounds[1] - bounds[0]
            self.mesh_info_text.set(
                f"{Path(path).name} | Faces: {len(mesh.faces)} | "
                f"X:{size[0]:.1f}mm Y:{size[1]:.1f}mm Z:{size[2]:.1f}mm"
            )
            self._append_console(f"> Loaded mesh: {path}")
            self._draw_mesh_preview()
        except Exception as exc:
            messagebox.showerror("Mesh Error", str(exc))

    def _draw_mesh_preview(self) -> None:
        if self.mesh_ax is None or self.mesh_canvas is None:
            return

        ax = self.mesh_ax
        ax.clear()
        self._style_3d_axes(ax)
        ax.set_title("Raw Scan Mesh", color="white")

        if self.raw_mesh is None:
            self.mesh_canvas.draw()
            return

        mesh = self.raw_mesh
        faces = mesh.faces
        if len(faces) > self.MAX_PLOT_FACES:
            faces = faces[::max(1, len(faces) // self.MAX_PLOT_FACES)]

        vertices = mesh.vertices

        mesh_poly = Poly3DCollection(vertices[faces], alpha=0.85)
        mesh_poly.set_facecolor([0.2, 0.6, 1.0])
        mesh_poly.set_edgecolor([0.1, 0.1, 0.1, 0.05])
        mesh_poly.set_linewidth(0.2)
        ax.add_collection3d(mesh_poly)

        self._set_axes_equal(ax, vertices)
        zmin, zmax = ax.get_zlim()

        ax.view_init(elev=20, azim=35)

        self.mesh_elev = 20
        self.mesh_azim = 35

        self.mesh_canvas.draw()

    def _sync_mesh_to_slats(self) -> None:
        if not self.scan_mesh_path:
            messagebox.showerror("Slats Error", "Load a mesh first.")
            return
        self.slats_info_text.set(f"Ready: {Path(self.scan_mesh_path).name}")

    def _clear_slats_preview(self) -> None:
        self.slats_data = None
        self.slats_info_text.set("No slat grid generated")
        if self.slats_3d_ax is not None:
            self.slats_3d_ax.clear()
            self._style_3d_axes(self.slats_3d_ax)
            self.slats_3d_canvas.draw()
        if self.slats_2d_figure is not None:
            self.slats_2d_figure.clear()
            self.slats_2d_canvas.draw()

    def _compute_slats_preview(self) -> None:
        if not HAS_SLATS:
            messagebox.showerror("Error", "Slats module not available.")
            return

        if not self.scan_mesh_path:
            messagebox.showerror("Slats Error", "Load a mesh first.")
            return

        try:
            n_xy = int(self.n_xy_var.get())
            n_xz = int(self.n_xz_var.get())
        except ValueError:
            messagebox.showerror("Slats Error", "Invalid slat counts.")
            return

        try:
            data = compute_worldgrid_from_stl(Path(self.scan_mesh_path), n_xy=n_xy, n_xz=n_xz)
            self.slats_data = data

            xy_count = len(data.get("worldXY_right", [])) + len(data.get("worldXY_left", []))
            xz_count = len(data.get("worldXZ_right", [])) + len(data.get("worldXZ_left", []))

            self.slats_info_text.set(
                f"XY: {xy_count} | XZ: {xz_count} | nXY: {n_xy} | nXZ: {n_xz}"
            )
            self._append_console("> Slat grid computed")
            self._draw_slats_3d_preview()
            self._draw_slats_2d_layouts()
        except Exception as exc:
            messagebox.showerror("Slats Error", str(exc))


    def _draw_slats_3d_preview(self) -> None:
        """Draw 3D slats preview with clearer mesh/slat readability."""
        if self.slats_3d_ax is None or not self.slats_data:
            return

        ax = self.slats_3d_ax
        ax.clear()
        self._style_3d_axes(ax)

        mesh = self.slats_data.get("mesh")
        zLevels = self.slats_data.get("zLevels", [])
        yLevels = self.slats_data.get("yLevels", [])
        worldXY_right = self.slats_data.get("worldXY_right", [])
        worldXY_left = self.slats_data.get("worldXY_left", [])
        worldXZ_right = self.slats_data.get("worldXZ_right", [])
        worldXZ_left = self.slats_data.get("worldXZ_left", [])

        # Collect all vertices for better framing
        fit_points = []

        # Mesh: lighter / more transparent so slats read on top
        if mesh is not None:
            faces = mesh.faces
            if len(faces) > self.MAX_PLOT_FACES:
                faces = faces[::max(1, len(faces) // self.MAX_PLOT_FACES)]

            mesh_poly = Poly3DCollection(mesh.vertices[faces], alpha=0.85)
            mesh_poly.set_facecolor([0.25, 0.55, 0.95])
            mesh_poly.set_edgecolor([0.05, 0.05, 0.05, 0.15])
            mesh_poly.set_linewidth(0.15)
            ax.add_collection3d(mesh_poly)

            fit_points.append(np.asarray(mesh.vertices, dtype=float))

        def _plot_slice_geoms(geoms, fixed_values, mode, color, lw=2.8):
            """
            mode='xy' -> geom coords are (x, y), fixed axis is z
            mode='xz' -> geom coords are (x, z), fixed axis is y
            """
            for fixed, geom in zip(fixed_values, geoms):
                if geom is None or geom.is_empty:
                    continue

                for poly in self._explode_polys(geom):
                    coords = np.asarray(poly.exterior.coords, dtype=float)
                    if len(coords) < 2:
                        continue

                    if mode == "xy":
                        xs = coords[:, 0]
                        ys = coords[:, 1]
                        zs = np.full(len(xs), float(fixed))
                        ax.plot(xs, ys, zs, color=color, lw=lw, alpha=0.95)
                        fit_points.append(np.column_stack([xs, ys, zs]))
                    else:  # xz
                        xs = coords[:, 0]
                        zs = coords[:, 1]
                        ys = np.full(len(xs), float(fixed))
                        ax.plot(xs, ys, zs, color=color, lw=lw, alpha=0.95)
                        fit_points.append(np.column_stack([xs, ys, zs]))

        # XY slats in red
        _plot_slice_geoms(worldXY_right, zLevels, mode="xy", color=(1.0, 0.15, 0.15, 0.95), lw=2.8)
        _plot_slice_geoms(worldXY_left,  zLevels, mode="xy", color=(1.0, 0.15, 0.15, 0.95), lw=2.8)

        # XZ slats in blue
        _plot_slice_geoms(worldXZ_right, yLevels, mode="xz", color=(0.15, 0.35, 1.0, 0.95), lw=2.8)
        _plot_slice_geoms(worldXZ_left,  yLevels, mode="xz", color=(0.15, 0.35, 1.0, 0.95), lw=2.8)

        # Fit view to BOTH mesh and slats, not mesh only
        if fit_points:
            all_pts = np.vstack(fit_points)
            self._set_axes_equal(ax, all_pts)

        ax.set_title("3D Slat Grid", color="white", pad=12)
        ax.view_init(elev=20, azim=35)
        self.slats_3d_canvas.draw_idle()

    def _explode_polys(self, g):
        """Extract individual Polygon objects from geometry"""
        if g is None or g.is_empty:
            return []
        geom_type = g.geom_type
        if geom_type == "Polygon":
            return [g]
        if geom_type == "MultiPolygon":
            return list(g.geoms)
        if geom_type == "GeometryCollection":
            polys = []
            for geom in g.geoms:
                polys.extend(self._explode_polys(geom))
            return polys
        return []

    def _draw_slats_2d_layouts(self) -> None:
        """Draw 2D slat outlines with world-consistent scale - no cuts, just profiles"""
        if self.slats_2d_canvas is None or not self.slats_data:
            return
        
        # DESTROY the old figure and canvas completely
        if self.slats_2d_canvas is not None:
            try:
                self.slats_2d_canvas.get_tk_widget().destroy()
            except:
                pass
        
        # Create brand new figure and canvas
        self.slats_2d_figure = Figure(figsize=(18, 14), dpi=100)
        self.slats_2d_figure.patch.set_facecolor("#111111")
        self.slats_2d_canvas = FigureCanvasTkAgg(self.slats_2d_figure, master=self.slats_2d_container)
        self.slats_2d_canvas.get_tk_widget().pack(fill="both", expand=True)
        
        zLevels = self.slats_data.get("zLevels", [])
        yLevels = self.slats_data.get("yLevels", [])
        worldXY_right = self.slats_data.get("worldXY_right", [])
        worldXY_left = self.slats_data.get("worldXY_left", [])
        worldXZ_right = self.slats_data.get("worldXZ_right", [])
        worldXZ_left = self.slats_data.get("worldXZ_left", [])
        mesh = self.slats_data.get("mesh")
        
        # Get mesh bounds for world-consistent scale
        if mesh is not None:
            V = mesh.vertices
            mesh_x_min = float(V[:, 0].min())
            mesh_x_max = float(V[:, 0].max())
            mesh_y_min = float(V[:, 1].min())
            mesh_y_max = float(V[:, 1].max())
            mesh_z_min = float(V[:, 2].min())
            mesh_z_max = float(V[:, 2].max())
            mesh_y_span = mesh_y_max - mesh_y_min
            mesh_z_span = mesh_z_max - mesh_z_min
        else:
            mesh_y_span = mesh_z_span = 100.0
            mesh_y_min = mesh_z_min = 0.0
            mesh_y_max = mesh_z_max = 100.0
        
        # Create brand new 2x2 subplots
        axs = self.slats_2d_figure.subplots(2, 2)
        
        gap = 20.0  # gap between slats in mm
        
        def draw_slat_set(ax, geom_list, levels, is_xz=False):
            """Helper to draw a set of slats with consistent spacing - centered in subplot
            Returns: (total_width, min_y, max_y) for proper axis limits"""
            
            # First pass: calculate total width needed
            total_width = 0
            for geom in geom_list:
                if geom and not geom.is_empty:
                    bounds = geom.bounds
                    board_width = bounds[2] - bounds[0]
                    total_width += board_width + gap
            
            # Remove last gap (we added one too many)
            if total_width > 0:
                total_width -= gap
            
            # Calculate centering offset 
            # Center in the middle of the 0-250 range
            center_offset = (250 - total_width) / 2
            
            min_y = float('inf')
            max_y = float('-inf')
            x_offset = center_offset
            
            # Second pass: draw with centering
            for i, (level_val, geom) in enumerate(zip(levels, geom_list)):
                if geom and not geom.is_empty:
                    bounds = geom.bounds
                    board_width = bounds[2] - bounds[0]
                    
                    # Draw ONLY the outline (exterior ring) - no internal cuts
                    for p in self._explode_polys(geom):
                        if is_xz:
                            # For XZ: x is X, y is Z
                            x, z = p.exterior.xy
                            x_shifted = [xi + x_offset for xi in x]
                            ax.plot(x_shifted, z, color='white', linewidth=2.5, alpha=0.95)
                            # Track actual Z bounds
                            z_list = list(z)
                            min_y = min(min_y, min(z_list))
                            max_y = max(max_y, max(z_list))
                        else:
                            # For XY: x is X, y is Y
                            x, y = p.exterior.xy
                            x_shifted = [xi + x_offset for xi in x]
                            ax.plot(x_shifted, y, color='white', linewidth=2.5, alpha=0.95)
                            # Track actual Y bounds
                            y_list = list(y)
                            min_y = min(min_y, min(y_list))
                            max_y = max(max_y, max(y_list))
                    
                    x_offset += board_width + gap
            
            # Handle case where no geometry was drawn
            if min_y == float('inf'):
                min_y = 0
            if max_y == float('-inf'):
                max_y = 100
            
            return total_width, min_y, max_y
        
        # ===== XY Left (TOP LEFT) =====
        ax = axs[0, 0]
        ax.set_title("XY Slats - Left", fontweight='bold', fontsize=12, color='white', pad=2)
        ax.set_aspect('equal', adjustable='box')
        ax.set_facecolor("#0D0D0D")
        ax.grid(False)
        ax.axis("off")
        
        total_w_xy_l, min_y_xy_l, max_y_xy_l = draw_slat_set(ax, worldXY_left, zLevels, is_xz=False)
        margin = max(50.0, (max_y_xy_l - min_y_xy_l) * 0.1)
        ax.set_xlim(-50, 300)  # Fixed X range for centered display
        ax.set_ylim(min_y_xy_l - margin, max_y_xy_l + margin)
        ax.grid(True, alpha=0.2, color='white')
        ax.tick_params(labelsize=9, colors='white')
        ax.set_facecolor('#0D0D0D')
        for spine in ax.spines.values():
            spine.set_color('white')
        
        # ===== XY Right (TOP RIGHT) =====
        ax = axs[0, 1]
        ax.set_title("XY Slats - Right", fontweight='bold', fontsize=12, color='white', pad=2)
        ax.set_aspect('equal', adjustable='box')
        ax.set_facecolor("#0D0D0D")
        ax.grid(False)
        ax.axis("off")
        
        total_w_xy_r, min_y_xy_r, max_y_xy_r = draw_slat_set(ax, worldXY_right, zLevels, is_xz=False)
        margin = max(50.0, (max_y_xy_r - min_y_xy_r) * 0.1)
        ax.set_xlim(-50, 300)  # Fixed X range for centered display
        ax.set_ylim(min_y_xy_r - margin, max_y_xy_r + margin)
        ax.grid(True, alpha=0.2, color='white')
        ax.tick_params(labelsize=9, colors='white')
        ax.set_facecolor('#0D0D0D')
        for spine in ax.spines.values():
            spine.set_color('white')
        
        # ===== XZ Left (BOTTOM LEFT) =====
        ax = axs[1, 0]
        ax.set_title("XZ Slats - Left", fontweight='bold', fontsize=12, color='white', pad=2)
        ax.set_aspect('equal', adjustable='box')
        ax.set_facecolor("#0D0D0D")
        ax.grid(False)
        ax.axis("off")
        
        total_w_xz_l, min_z_xz_l, max_z_xz_l = draw_slat_set(ax, worldXZ_left, yLevels, is_xz=True)
        margin = max(50.0, (max_z_xz_l - min_z_xz_l) * 0.1)
        ax.set_xlim(-50, 300)  # Fixed X range for centered display
        ax.set_ylim(min_z_xz_l - margin, max_z_xz_l + margin)
        ax.grid(True, alpha=0.2, color='white')
        ax.tick_params(labelsize=9, colors='white')
        ax.set_facecolor('#0D0D0D')
        for spine in ax.spines.values():
            spine.set_color('white')
        
        # ===== XZ Right (BOTTOM RIGHT) =====
        ax = axs[1, 1]
        ax.set_title("XZ Slats - Right", fontweight='bold', fontsize=12, color='white', pad=2)
        ax.set_aspect('equal', adjustable='box')
        ax.set_facecolor("#0D0D0D")
        ax.grid(False)
        ax.axis("off")
        
        total_w_xz_r, min_z_xz_r, max_z_xz_r = draw_slat_set(ax, worldXZ_right, yLevels, is_xz=True)
        margin = max(50.0, (max_z_xz_r - min_z_xz_r) * 0.1)
        ax.set_xlim(-50, 300)  # Fixed X range for centered display
        ax.set_ylim(min_z_xz_r - margin, max_z_xz_r + margin)
        ax.grid(True, alpha=0.2, color='white')
        ax.tick_params(labelsize=9, colors='white')
        ax.set_facecolor('#0D0D0D')
        for spine in ax.spines.values():
            spine.set_color('white')
        
        self.slats_2d_figure.tight_layout(pad=2.0, w_pad=1.0, h_pad=1.5)
        self.slats_2d_canvas.draw()

        self.slats_2d_figure.subplots_adjust(
            left=0.02, right=0.98, top=0.95, bottom=0.03,
            wspace=0.06, hspace=0.08
        )

    # ===== STATUS & RX =====
    def _status_poll_loop(self) -> None:
        if self.polling and self.ctrl.is_connected:
            try:
                self.ctrl.send_realtime(b"?")
            except Exception:
                pass
        self.after(self.POLL_MS, self._status_poll_loop)

    def _process_rx(self) -> None:
        for line in self.ctrl.get_rx_lines():
            self._append_console(line)

            if line == "ok":
                self.last_controller_reply = "ok"
                self.waiting_for_ack = False
            elif line.startswith("error:"):
                self.last_controller_reply = line
                self.waiting_for_ack = False
            elif line.startswith("ALARM:"):
                self.last_controller_reply = line
                self.waiting_for_ack = False
                self.in_alarm = True
                self.machine_state = "Alarm"
                self.status_text.set("!!! ALARM !!!")
                self.state_text.set(f"State: {line}")
                self.job_progress_text.set("Job: alarm")
            elif line.startswith("<") and line.endswith(">"):
                self._parse_status(line)

        self.after(self.RX_PROCESS_MS, self._process_rx)

    def _parse_status(self, line: str) -> None:
        self.last_status_text.set(f"Last status: {line}")

        inner = line[1:-1]
        parts = inner.split("|")
        if not parts:
            return

        state = parts[0]
        self.machine_state = state
        self.state_text.set(f"State: {state}")

        # Update alarm flag based on state
        if state.startswith("Alarm"):
            self.in_alarm = True
            self.status_text.set("!!! ALARM !!!")
        else:
            # Clear alarm if state is NOT an alarm
            self.in_alarm = False
            if self.ctrl.is_connected:
                self.status_text.set("Connected")

        for part in parts[1:]:
            if ":" not in part:
                continue
            key, val = part.split(":", 1)
            if key == "MPos":
                self.machine_pos_text.set(f"MPos: {val}")
                # Parse individual axis values (format: X,Y,Z,A,B,C)
                try:
                    coords = val.strip().split(",")
                    if len(coords) >= 1:
                        self.machine_pos_x_text.set(f"{float(coords[0]):.2f}")
                    if len(coords) >= 2:
                        self.machine_pos_y_text.set(f"{float(coords[1]):.2f}")
                    if len(coords) >= 3:
                        self.machine_pos_z_text.set(f"{float(coords[2]):.2f}")
                    if len(coords) >= 4:
                        self.machine_pos_a_text.set(f"{float(coords[3]):.2f}")
                    if len(coords) >= 5:
                        self.machine_pos_b_text.set(f"{float(coords[4]):.2f}")
                    if len(coords) >= 6:
                        self.machine_pos_c_text.set(f"{float(coords[5]):.2f}")
                except (ValueError, IndexError):
                    pass
            elif key == "WPos":
                self.work_pos_text.set(f"WPos: {val}")

    # ===== JOB EXECUTION =====
    def _can_run_job(self) -> bool:
        if not self.ctrl.is_connected:
            return False
        if self.job_running or self.jogging:
            return False
        if self.in_alarm:
            return False
        return self.machine_state == "Idle"

    def _start_gcode_job(self) -> None:
        if not self._can_run_job():
            messagebox.showerror("Run Error", "Machine must be connected, idle, and not in alarm.")
            return
        if not self.gcode_lines:
            messagebox.showerror("Run Error", "No G-code loaded.")
            return

        self.job_running = True
        self.job_paused = False
        self.job_stopping = False
        self.waiting_for_ack = False
        self.last_controller_reply = None

        self.job_thread = threading.Thread(target=self._gcode_job_loop, daemon=True)
        self.job_thread.start()
        self._append_console("> Starting G-code job")

    def _pause_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_paused = True
        self.ctrl.send_realtime(b"!")
        self._append_console(">> [JOB HOLD] !")

    def _resume_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_paused = False
        self.ctrl.send_realtime(b"~")
        self._append_console(">> [JOB RESUME] ~")

    def _stop_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_stopping = True
        self.job_paused = False
        self.ctrl.send_realtime(b"\x18")
        self._append_console(">> [JOB STOP] Ctrl-X")

    def _gcode_job_loop(self) -> None:
        try:
            total = len(self.gcode_lines)

            while self.current_line_index < total:
                if self.job_stopping:
                    self.job_progress_text.set("Job: stopped")
                    break

                if self.job_paused:
                    self.job_progress_text.set(f"Job: paused at {self.current_line_index + 1}/{total}")
                    time.sleep(0.05)
                    continue

                line = self.gcode_lines[self.current_line_index].strip()
                if not line:
                    self.current_line_index += 1
                    continue
                
                # SKIP LINES WITH A-AXIS (roller control disabled for now)
                if 'A' in line.upper():
                    self._append_console(f">> [{self.current_line_index + 1}/{total}] {line} [SKIPPED - A-axis disabled]")
                    self.current_line_index += 1
                    continue

                pct = int(((self.current_line_index + 1) / total) * 100)
                self.job_progress_text.set(f"Job: line {self.current_line_index + 1}/{total} ({pct}%)")
                self.last_controller_reply = None
                self.waiting_for_ack = True

                self.ctrl.write_line(line)
                self._append_console(f">> [{self.current_line_index + 1}/{total}] {line}")

                start = time.time()
                while self.waiting_for_ack:
                    if self.job_stopping:
                        break
                    if time.time() - start > self.GCODE_ACK_TIMEOUT_S:
                        self._append_console("[ERROR] Timeout waiting for controller")
                        self.job_stopping = True
                        break
                    time.sleep(0.01)

                if self.job_stopping:
                    break

                if self.last_controller_reply == "ok":
                    self.current_line_index += 1
                    # Update 3D preview during job execution if in preview tab
                    if self.preview_mode.get() == "3d":
                        try:
                            self._draw_gcode_3d_preview()
                        except:
                            pass  # Don't interrupt job if preview update fails
                elif isinstance(self.last_controller_reply, str):
                    if "error:" in self.last_controller_reply.lower():
                        self._append_console(f"[JOB ABORTED] {self.last_controller_reply}")
                        break

            if self.current_line_index >= total and not self.job_stopping:
                self.job_progress_text.set("Job: complete")
                self._append_console("> Job complete")

        finally:
            self.job_running = False
            self.job_paused = False
            self.job_stopping = False
            self.waiting_for_ack = False

    def _stop_all_motion_and_jobs(self) -> None:
        self._cancel_jog()
        self.job_stopping = True
        self.job_paused = False

    def on_close(self) -> None:
        self._disconnect()
        self.destroy()

    # ===== SLATS CAM PACKING METHODS =====
    
    def _slats_cam_load_dxf_for_packing(self) -> None:
        """Load DXF file specifically for packing workspace"""
        if not HAS_DXF_HANDLER:
            messagebox.showerror("Error", "DXF handler not available")
            return
        
        path = filedialog.askopenfilename(
            title="Load Cardboard DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if not path:
            return
        
        try:
            self.slats_cam_dxf_packing = DXFDieline(Path(path))
            info = self.slats_cam_dxf_packing.get_info()
            
            self.slats_cam_packing_dxf_bounds = info['bounds']
            self._slats_cam_log(f"✓ Loaded DXF: {Path(path).name}")
            self._slats_cam_log(f"  Bounds: {info['bounds']}")
            self._slats_cam_log(f"  Size: {info['bounds_width']:.1f}mm × {info['bounds_height']:.1f}mm")
            
            self.slats_cam_status_var.set("DXF loaded - Ready to pack")
            self._slats_cam_render_workspace()
        except Exception as e:
            self._slats_cam_log(f"✗ DXF load error: {e}")
            messagebox.showerror("DXF Error", str(e))

    def _slats_cam_auto_pack(self) -> None:
        """Auto-pack generated slats onto cardboard"""
        if not self.slats_cam_raw_slats:
            messagebox.showwarning("Error", "Generate slats first")
            return
        
        if not self.slats_cam_dxf_packing:
            messagebox.showwarning("Error", "Load cardboard DXF first")
            return
        
        try:
            self._slats_cam_log("\n>>> Starting auto-pack...")
            self.slats_cam_status_var.set("Packing...")
            self.update()
            
            bounds = self.slats_cam_packing_dxf_bounds
            dxf_width = bounds[2] - bounds[0]
            dxf_height = bounds[3] - bounds[1]
            
            self._slats_cam_log(f"Cardboard: {dxf_width:.1f}mm × {dxf_height:.1f}mm")
            
            packed = self._shelf_pack_slats(
                self.slats_cam_raw_slats,
                dxf_width,
                dxf_height
            )
            
            self.slats_cam_packed_slats = packed
            self.slat_workspace_offsets = {i: {'x': 0, 'y': 0} for i in range(len(packed))}
            self.selected_slat_idx = None
            
            slat_area = sum(
                (g.bounds[2] - g.bounds[0]) * (g.bounds[3] - g.bounds[1])
                for g, x, y, typ in packed
            )
            cardboard_area = dxf_width * dxf_height
            efficiency = (slat_area / cardboard_area * 100) if cardboard_area > 0 else 0
            
            self._slats_cam_log(f"✓ Packed {len(packed)} slats")
            self._slats_cam_log(f"  Efficiency: {efficiency:.1f}%")
            
            self.slats_cam_status_var.set(f"Packed {len(packed)} slats ({efficiency:.0f}%)")
            
            self.dxf_canvas_zoom = 1.0
            self.dxf_canvas_pan_x = 0
            self.dxf_canvas_pan_y = 0
            
            self._slats_cam_render_workspace()
            
        except Exception as e:
            self._slats_cam_log(f"✗ Packing error: {e}")
            self.slats_cam_status_var.set(f"Error: {str(e)[:40]}")

    def _shelf_pack_slats(self, slats, dxf_width, dxf_height, margin=10):
        """Shelf-packing algorithm for slats"""
        n_xy = int(self.slats_cam_n_xy_var.get())
        
        n_xy_total = n_xy * 2
        slat_types = ['XY'] * n_xy_total + ['XZ'] * (len(slats) - n_xy_total)
        
        indexed = list(enumerate(zip(slats, slat_types)))
        indexed.sort(key=lambda item: item[1][0].bounds[3] - item[1][0].bounds[1], reverse=True)
        
        shelves = []
        current_shelf = []
        current_shelf_height = 0
        current_y = margin
        
        for idx, (geom, slat_type) in indexed:
            if geom is None or geom.is_empty:
                continue
            
            bounds = geom.bounds
            slat_width = bounds[2] - bounds[0]
            slat_height = bounds[3] - bounds[1]
            
            current_shelf_width = sum(
                g.bounds[2] - g.bounds[0] for g, _, _, _ in current_shelf
            )
            
            if (current_shelf_width + slat_width + margin * 2 <= dxf_width and
                len(current_shelf) < 10):
                
                x = margin + current_shelf_width
                current_shelf.append((geom, x, current_y, slat_type))
                current_shelf_height = max(current_shelf_height, slat_height)
            else:
                if current_shelf:
                    shelves.extend(current_shelf)
                
                current_shelf = [(geom, margin, current_y + current_shelf_height + margin, slat_type)]
                current_y += current_shelf_height + margin
                current_shelf_height = slat_height
            
            if current_y + current_shelf_height + margin > dxf_height:
                self._slats_cam_log(f"⚠ Warning: Slat {idx} exceeds cardboard height")
        
        if current_shelf:
            shelves.extend(current_shelf)
        
        return shelves

    def _slats_cam_render_workspace(self) -> None:
        """Unified Render: Draws Grid + Green DXF + Slats using global Pan/Zoom."""
        canvas = self.slats_cam_dxf_canvas
        canvas.delete("all")
        
        dxf = self.slats_cam_dxf_packing or self.dxf_dieline
        if not dxf: return

        info = dxf.get_info()
        bounds = info['bounds']
        canvas.update()
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw <= 1: cw, ch = 1200, 800

        # Calculate fit scale then apply global user zoom
        margin = 40
        base_scale = min((cw - 2*margin) / max(bounds[2]-bounds[0], 1), 
                        (ch - 2*margin) / max(bounds[3]-bounds[1], 1))
        fit_scale = base_scale * self.dxf_canvas_zoom

        def to_canvas(x, y):
            # Centering Math + Global Pan + User Zoom
            canvas_x = (cw/2) + self.dxf_canvas_pan_x + (x - (bounds[0] + bounds[2])/2) * fit_scale
            canvas_y = (ch/2) + self.dxf_canvas_pan_y - (y - (bounds[1] + bounds[3])/2) * fit_scale
            return canvas_x, canvas_y

        # 1. Draw Grid (Matches Vision Tab)
        grid_step = 50 * self.dxf_canvas_zoom
        if grid_step > 5:
            for x_l in np.arange(self.dxf_canvas_pan_x % grid_step, cw, grid_step):
                canvas.create_line(x_l, 0, x_l, ch, fill="#1A1A1A")
            for y_l in np.arange(self.dxf_canvas_pan_y % grid_step, ch, grid_step):
                canvas.create_line(0, y_l, cw, y_l, fill="#1A1A1A")

        # 2. Draw DXF (Green Outline)
        try:
            for geom in dxf.get_geometries(): 
                for poly in self._explode_polys(geom):
                    pts = []
                    for x, y in poly.exterior.coords: pts.extend(to_canvas(x, y))
                    canvas.create_line(pts, fill="#00FF00", width=2)
        except: pass

        # 3. Draw Slats (Drag logic remains pixel-relative for stability)
        if self.slats_cam_packed_slats:
            for i, (geom, base_x, base_y, slat_type) in enumerate(self.slats_cam_packed_slats):
                off = self.slat_workspace_offsets.get(i, {'x': 0, 'y': 0})
                is_selected = (self.selected_slat_idx == i)
                color = "white" if is_selected else ("#0088FF" if slat_type == "XY" else "#FF8800")
                for poly in self._explode_polys(geom):
                    pts = []
                    for x, y in poly.exterior.coords:
                        bx, by = to_canvas(x + base_x, y + base_y)
                        pts.extend([bx + off['x'], by + off['y']])
                    canvas.create_polygon(pts, fill=color, outline="white", tags=("slat_obj", f"slat_{i}"), alpha=0.7)

        self._bind_slat_workspace_controls()

    def _draw_dxf_bounds_box(self, canvas, bounds, to_canvas) -> None:
        """Draw DXF bounds as a simple box"""
        corners = [
            (bounds[0], bounds[1]), (bounds[2], bounds[1]),
            (bounds[2], bounds[3]), (bounds[0], bounds[3]), (bounds[0], bounds[1])
        ]
        pts = []
        for x, y in corners:
            cx_pt, cy_pt = to_canvas(x, y)
            pts.extend([cx_pt, cy_pt])
        canvas.create_line(pts, fill="#00FF00", width=3)

    def _bind_slat_workspace_controls(self) -> None:
        """Bind mouse controls for slat dragging and panning"""
        canvas = self.slats_cam_dxf_canvas
        
        canvas.bind("<Button-1>", self._on_slat_workspace_click)
        canvas.bind("<B1-Motion>", self._on_slat_workspace_drag)
        canvas.bind("<ButtonRelease-1>", self._on_slat_workspace_release)
        
        canvas.bind("<Button-3>", self._dxf_canvas_pan_start)
        canvas.bind("<B3-Motion>", self._dxf_canvas_pan_move)
        canvas.bind("<ButtonRelease-3>", self._dxf_canvas_pan_end)
        
        canvas.bind("<MouseWheel>", self._dxf_canvas_zoom)
        canvas.bind("<Button-4>", self._dxf_canvas_zoom)
        canvas.bind("<Button-5>", self._dxf_canvas_zoom)

    def _on_slat_workspace_click(self, event) -> None:
        """Handle slat selection in workspace"""
        canvas = self.slats_cam_dxf_canvas
        
        if not self.slats_cam_packed_slats:
            return
        
        bounds = self.slats_cam_packing_dxf_bounds
        dxf_w = bounds[2] - bounds[0]
        dxf_h = bounds[3] - bounds[1]
        
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        
        margin = 40
        scale_w = (cw - 2*margin) / dxf_w if dxf_w > 0 else 1
        scale_h = (ch - 2*margin) / dxf_h if dxf_h > 0 else 1
        fit_scale = min(scale_w, scale_h) * self.dxf_canvas_zoom
        
        cx = cw / 2 + self.dxf_canvas_pan_x
        cy = ch / 2 + self.dxf_canvas_pan_y
        
        world_x = (event.x - cx) / fit_scale + (bounds[0] + bounds[2])/2
        world_y = -(event.y - cy) / fit_scale + (bounds[1] + bounds[3])/2
        
        closest_idx = None
        closest_dist = float('inf')
        
        for i, (geom, base_x, base_y, _) in enumerate(self.slats_cam_packed_slats):
            offset = self.slat_workspace_offsets.get(i, {'x': 0, 'y': 0})
            center_x = base_x + offset['x'] + (geom.bounds[0] + geom.bounds[2])/2
            center_y = base_y + offset['y'] + (geom.bounds[1] + geom.bounds[3])/2
            
            dist = ((world_x - center_x)**2 + (world_y - center_y)**2)**0.5
            if dist < closest_dist:
                closest_dist = dist
                closest_idx = i
        
        if closest_dist < 100:
            self.selected_slat_idx = closest_idx
            self._drag_start_pos = (event.x, event.y)
            self._slats_cam_render_workspace()

    def _on_slat_workspace_drag(self, event) -> None:
        """Handle slat dragging"""
        if self.selected_slat_idx is None:
            return
        
        dx = event.x - self._drag_start_pos[0]
        dy = event.y - self._drag_start_pos[1]
        
        idx = self.selected_slat_idx
        off = self.slat_workspace_offsets.get(idx, {'x': 0, 'y': 0})
        self.slat_workspace_offsets[idx] = {'x': off['x'] + dx, 'y': off['y'] + dy}
        
        self._drag_start_pos = (event.x, event.y)
        self._slats_cam_render_workspace()

    def _on_slat_workspace_release(self, event) -> None:
        """Handle slat release"""
        if self.selected_slat_idx is not None:
            idx = self.selected_slat_idx
            off = self.slat_workspace_offsets[idx]
            self._slats_cam_log(f"Slat {idx} repositioned: offset ({off['x']:.0f}, {off['y']:.0f})px")
        
        self.selected_slat_idx = None
        self._slats_cam_render_workspace()

    def _slats_cam_fit_view(self) -> None:
        """Auto-fit workspace to show all content"""
        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0
        self.dxf_canvas_pan_y = 0
        self._slats_cam_render_workspace()
        self._slats_cam_log("Workspace view reset")


if __name__ == "__main__":
    app = TouchUI()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()