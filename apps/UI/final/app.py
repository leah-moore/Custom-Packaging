import os
import sys
from pathlib import Path
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import inspect



# add /apps to path (you already have something like this)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if __name__ == "__main__" and __package__ is None:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
    __package__ = "apps.UI.final"

import math
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box, Point
from shapely.affinity import translate, rotate as shp_rotate

from apps.gcode.machine_ops_planner import build_machine_ops
from apps.gantry.pi_teensy_coordination.job_runner import JobRunner
from apps.gantry.pi_teensy_coordination.roller_controller import RollerController
from apps.UI.tablet.dxf_handler import DXFDieline
#from apps.Vision.runner import VisionRunner

from .components.preview_actions_builder import build_preview_actions
from .components.unified_gcode_controller import UnifiedGCodeController
from .components.slats_cam_logic import *
from .theme import BG, apply_theme, FG, PANEL_BG, BTN_NEUTRAL
from .components.header import build_header
from .gcode_parser import GCodeParser
from .tabs.manual_setup_tab import build_manual_setup_tab
from .tabs.run_tab import build_run_tab
from .tabs.preview_tab import build_preview_tab
from .tabs.gcode_viewer_tab import build_gcode_viewer_tab
from .tabs.vision_dxf_tab import build_vision_dxf_tab
from .tabs.slats_tab import build_slats_tab
from .tabs.slats_cam_tab import build_slats_cam_tab
from .tabs.diagnostics_tab import build_diagnostics_tab
from .tabs.photogrammetry_tab import build_photogrammetry_tab


LIGHT_ON_CMD = "M8"
LIGHT_OFF_CMD = "M9"
SPINDLE_OFF_CMD = "M5"


class TouchUI(tk.Tk):
    POLL_MS = 200
    RX_PROCESS_MS = 50
    JOG_REPEAT_S = 0.25
    JOG_HOLD_THRESHOLD_MS = 200

    def __init__(self):
        super().__init__()
        apply_theme(self)

        self.title("Precision Packaging Solutions")
        self.geometry("1024x600")
        self.minsize(1024, 600)
        self.configure(bg=BG)

        self.ctrl = UnifiedGCodeController()

        # Pi-side roller controller
        try:
            self.rollers = RollerController() if RollerController is not None else None
        except Exception:
            self.rollers = None

        # machine state
        self.machine_state = "Disconnected"
        self.polling = False
        self.homed = False
        self.in_alarm = False
        self.waiting_for_ack = False
        self.last_controller_reply = None

        self.job_lock = threading.Lock()
        self.job_running = False
        self.job_paused = False
        self.job_stopping = False

        # jogging / jobs
        self.jogging = False
        self.jog_thread = None
        self.roller_jogging = False
        self.roller_jog_thread = None
        self.job_thread = None
        self.jog_mode_var = tk.StringVar(value="step")

        # tap-vs-hold jog state
        self._jog_hold_after_id = None
        self._jog_hold_started = False
        self._pending_jog_axis_moves = None
        self._pending_jog_button = None

        self._jog_watchdog_after_id = None
        self.active_jog_button = None

        # gcode / preview
        self.gcode_lines = []
        self.gcode_segments = []

        self.preview_actions = []
        self.gcode_bounds = {}
        self.current_line_index = 0
        self.current_tool_pos = [0.0, 0.0, 0.0]
        self.preview_is_playing = False
        self.preview_playback_speed = 1.0
        self.preview_estimated_time = 0.0
        self.preview_animation_id = None
        self.preview_scrub_index = 0.0
        self.preview_elapsed_s = 0.0
        self.preview_last_tick_s = None
        self.preview_total_time_s = 0.0

        self.preview_blade_axis = "B"   # change to "A" if your knife uses A instead
        self._last_knife_angle = 0.0
        self.preview_blade_offset_deg = 0.0

        self.preview_live_follow_var = tk.BooleanVar(value=True)

        # photogrammetry
        self.photogrammetry_status_var = tk.StringVar(value="Idle")
        self.photogrammetry_info_text = tk.StringVar(value="No photogrammetry session yet")
        self.photogrammetry_camera_info_var = tk.StringVar(value="Camera idle")
        self.photogrammetry_mesh_info_var = tk.StringVar(value="No reconstructed mesh loaded")

        self.photogrammetry_mesh_path = None
        self.photogrammetry_raw_mesh = None

        # camera/view orientation
        self.photogrammetry_azim = 35
        self.photogrammetry_elev = 20

        # actual mesh orientation for packaging
        self.photogrammetry_rot_x = 0.0
        self.photogrammetry_rot_y = 0.0
        self.photogrammetry_rot_z = 0.0

        self.photogrammetry_camera_canvas = None
        self.photogrammetry_figure = None
        self.photogrammetry_ax = None
        self.photogrammetry_canvas = None

        # vision / dxf / mesh / slats
        self.vision_images = []
        # vision runtime
        self.vision_runner = None
        self.vision_scan_running = False

        # vision display state
        self.vision_status_var = tk.StringVar(value="Idle")
        self.vision_process_var = tk.StringVar(value="No scan yet")
        self.stitched_info_var = tk.StringVar(value="No stitched image")
        self.generated_dxf_var = tk.StringVar(value="No generated DXF")

        self.stitched_preview_canvas = None
        self.process_status_canvas = None

        self._stitched_image = None
        self._stitched_tk = None
        self._camera_tk = None

        # live USB camera state
        self.camera_running = False
        self.camera_thread = None
        self.camera_capture = None
        self._camera_frame = None

        # DXF viewer state
        self.dxf_dieline = None
        self.dxf_file_path = None
        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0.0
        self.dxf_canvas_pan_y = 0.0
        self._draw_dxf_preview()

        # DXF transform / alignment state
        self.dxf_tx_var = tk.StringVar(value="0.0")
        self.dxf_ty_var = tk.StringVar(value="0.0")
        self.dxf_rot_var = tk.StringVar(value="0.0")
        self.dxf_scale_var = tk.StringVar(value="1.0")

        # vision + DXF tab state
        self.vision_dxf_view_mode = tk.StringVar(value="split")
        self.vision_dxf_status_var = tk.StringVar(value="Idle")
        self.vision_result_var = tk.StringVar(value="No run yet")
        self.camera_info_var = tk.StringVar(value="Camera idle")
        self.dxf_info_text = tk.StringVar(value="No DXF loaded")
        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0.0
        self.dxf_canvas_pan_y = 0.0
        self._dxf_pan_last_x = None
        self._dxf_pan_last_y = None

        # camera / DXF widgets
        self.camera_preview_canvas = None
        self.dxf_preview_canvas = None
        self.vision_dxf_content = None
        self.vision_camera_panel = None
        self.vision_dxf_panel = None
        self._vision_dxf_view_buttons = {}

        # mesh / slats state
        self.scan_mesh_path = None
        self.raw_mesh = None
        self.slats_data = None
        self.library_tile_map = {}
        self.mesh_elev = 20
        self.mesh_azim = 35

        # =========================
        # STATUS / DISPLAY VARS
        # =========================
        self.status_text = tk.StringVar(value="Disconnected")
        self.state_text = tk.StringVar(value="State: --")
        self.machine_pos_text = tk.StringVar(value="MPos: --")
        self.work_pos_text = tk.StringVar(value="WPos: --")
        self.job_progress_text = tk.StringVar(value="Job: idle")
        self.file_text = tk.StringVar(value="No file loaded")
        self.last_status_text = tk.StringVar(value="Last status: --")
        self.limit_switch_text = tk.StringVar(value="Limits: --")

        self.machine_pos_x_text = tk.StringVar(value="--")
        self.machine_pos_y_text = tk.StringVar(value="--")
        self.machine_pos_z_text = tk.StringVar(value="--")
        self.machine_pos_a_text = tk.StringVar(value="--")
        self.machine_pos_b_text = tk.StringVar(value="--")
        self.machine_pos_c_text = tk.StringVar(value="--")

        self.work_pos_x_text = tk.StringVar(value="--")
        self.work_pos_y_text = tk.StringVar(value="--")
        self.work_pos_z_text = tk.StringVar(value="--")
        self.work_pos_a_text = tk.StringVar(value="--")
        self.work_pos_b_text = tk.StringVar(value="--")
        self.work_pos_c_text = tk.StringVar(value="--")

        # =========================
        # CONNECTION VARS
        # =========================
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.raw_cmd_var = tk.StringVar()

        # =========================
        # JOG VARS
        # =========================
        self.jog_step_var = tk.StringVar(value="1")
        self.jog_feed_var = tk.StringVar(value="1000")

        self.roller_step_var = tk.StringVar(value="5")
        self.roller_feed_var = tk.StringVar(value="300")

        self.a_rot_step_var = tk.StringVar(value="5")
        self.a_rot_feed_var = tk.StringVar(value="300")

        self.b_rot_step_var = tk.StringVar(value="5")
        self.b_rot_feed_var = tk.StringVar(value="300")

        self.c_rot_step_var = tk.StringVar(value="5")
        self.c_rot_feed_var = tk.StringVar(value="300")

        # =========================
        # RUN / CONSOLE VARS
        # =========================
        self.mdi_var = tk.StringVar()
        self.spindle_speed_var = tk.StringVar(value="4000")
        self.spindle_oscillation_rpm_var = tk.StringVar(value="2000")
        self.spindle_status_var = tk.StringVar(value="Spindle: OFF")

        # =========================
        # PREVIEW VARS
        # =========================
        self.preview_mode = tk.StringVar(value="2d")
        self.preview_speed_var = tk.StringVar(value="1.0x")
        self.preview_time_var = tk.StringVar(value="Time: --:--")
        self.preview_segment_var = tk.StringVar(value="Segments: 0/0")
        self.preview_scrubber_var = tk.DoubleVar(value=0.0)

        # =========================
        # MESH / SLATS VARS
        # =========================
        self.mesh_info_text = tk.StringVar(value="No mesh loaded")
        self.slats_info_text = tk.StringVar(value="No slat grid generated")
        self.n_xy_var = tk.StringVar(value="5")
        self.n_xz_var = tk.StringVar(value="5")
        self.show_mesh_in_slats_var = tk.BooleanVar(value=True)

        self.slat_spacing_var = tk.StringVar(value="10.0")
        self.slat_thickness_var = tk.StringVar(value="3.0")
        self.slat_height_var = tk.StringVar(value="20.0")
        self.show_mesh_overlay_var = tk.BooleanVar(value=True)
        self.slat_info_text = tk.StringVar(value="No slats generated")

        self.drag_item_id = None
        self.drag_boundary_index = None
        self.drag_last_xy = None
        self.drag_original_pose = None

        # =========================
        # SLATS CAM VARS
        # =========================
        self.slats_cam_run_dir = None

        self.slats_cam_stl_path_var = tk.StringVar(value="(no file selected)")
        self.slats_cam_status_var = tk.StringVar(value="Ready")
        self.slats_cam_slats_info_var = tk.StringVar(value="No slats loaded")
        self.slats_cam_n_xy_var = tk.StringVar(value="5")
        self.slats_cam_n_xz_var = tk.StringVar(value="5")

        self.dxf_tx_var = tk.StringVar(value="0.0")
        self.dxf_ty_var = tk.StringVar(value="0.0")
        self.dxf_rot_var = tk.StringVar(value="0.0")
        self.dxf_scale_var = tk.StringVar(value="1.0")

        # widgets populated by tabs
        self.console = None
        self.gcode_viewer = None
        self.preview_canvas = None
        self.preview_canvas_2d = None
        self.preview_container = None
        self.preview_3d_canvas = None
        self.preview_3d_figure = None
        self.preview_3d_ax = None
        self.preview_play_btn = None
        self.preview_pause_btn = None
        self.preview_scrubber = None

        self.mesh_figure = None
        self.mesh_ax = None
        self.mesh_canvas = None

        self.slats_figure = None
        self.slats_ax = None
        self.slats_canvas = None

        # build header
        build_header(self, self)

        self._browse_stl = self._browse_mesh

        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Notebook background (bar behind tabs)
        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0,
        )

        # Base tab style
        style.configure(
            "TNotebook.Tab",
            background="#2A2A2A",   # inactive tabs
            foreground="#BBBBBB",
            padding=(10, 4),
            font=("Arial", 8, "bold"),
            borderwidth=0,
        )

        # Selected + hover behavior
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", PANEL_BG),   # <-- MATCHES YOUR PANELS (key change)
                ("active", "#353535"),
            ],
            foreground=[
                ("selected", "#FFFFFF"),
                ("active", "#FFFFFF"),
            ],
        )

        # notebook
        notebook_container = tk.Frame(self, bg=BG)
        notebook_container.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(notebook_container)
        self.notebook.pack(fill="both", expand=True)

        tabs = {
            "Manual + Setup": build_manual_setup_tab,
            "Vision + DXF": build_vision_dxf_tab,
            "Photogrammetry": build_photogrammetry_tab,
            "Run": build_run_tab,
            "Preview": build_preview_tab,
            "G-code Viewer": build_gcode_viewer_tab,
            "Slats": build_slats_tab,
            "Slats CAM": build_slats_cam_tab,
            "Diagnostics": build_diagnostics_tab,
        }

        for name, builder in tabs.items():
            frame = tk.Frame(self.notebook, bg=BG)
            self.notebook.add(frame, text=name)
            builder(self, frame)

        self._refresh_ports()

        self.after(self.RX_PROCESS_MS, self._process_rx)
        self.after(self.POLL_MS, self._status_poll_loop)

    # =========================
    # CONSOLE
    # =========================
    def _append_console(self, text: str) -> None:
        if self.console is not None:
            self.console.insert("end", text + "\n")
            self.console.see("end")
        if hasattr(self, "diagnostics_log") and self.diagnostics_log is not None:
            self.diagnostics_log.insert("end", text + "\n")
            self.diagnostics_log.see("end")

    def _clear_console(self) -> None:
        if self.console is not None:
            self.console.delete("1.0", "end")

    # =========================
    # SERIAL / MACHINE
    # =========================
    
    def _start_live_camera(self):
        if self.camera_running:
            return

        import cv2

        try:
            # Try USB camera (index 0)
            cap = cv2.VideoCapture(0)

            if not cap.isOpened():
                raise RuntimeError("Could not open camera (/dev/video0)")

            self.camera_capture = cap
            self.camera_running = True

            if hasattr(self, "camera_info_var"):
                self.camera_info_var.set("Camera running")

            self._append_console("> Camera started")

            def loop():
                import time

                while self.camera_running:
                    ret, frame = cap.read()
                    if not ret:
                        continue

                    self._camera_frame = frame

                    # push update to UI thread
                    self.after(0, self._update_camera_canvas)

                    time.sleep(0.03)  # ~30 FPS

            import threading
            self.camera_thread = threading.Thread(target=loop, daemon=True)
            self.camera_thread.start()

        except Exception as exc:
            if hasattr(self, "camera_info_var"):
                self.camera_info_var.set("Camera error")

            self._append_console(f"[CAM ERROR] {exc}")
    
    def _stop_live_camera(self):
        self.camera_running = False

        if self.camera_capture is not None:
            try:
                self.camera_capture.release()
            except Exception:
                pass

        self.camera_capture = None

        if hasattr(self, "camera_info_var"):
            self.camera_info_var.set("Camera stopped")

        self._append_console("> Camera stopped")


    def _update_camera_canvas(self):
        if self._camera_frame is None:
            return

        if not hasattr(self, "camera_preview_canvas") or self.camera_preview_canvas is None:
            return

        import cv2
        from PIL import Image, ImageTk

        frame = self._camera_frame

        # BGR → RGB
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        img = Image.fromarray(frame)

        # resize to canvas
        w = self.camera_preview_canvas.winfo_width()
        h = self.camera_preview_canvas.winfo_height()

        if w > 0 and h > 0:
            img = img.resize((w, h))

        tk_img = ImageTk.PhotoImage(img)

        self.camera_preview_canvas.delete("all")
        self.camera_preview_canvas.create_image(0, 0, anchor="nw", image=tk_img)

        # KEEP REFERENCE (critical)
        self.camera_preview_canvas.image = tk_img

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
            self.ctrl.port = port
            self.ctrl.baudrate = baud_int
            self.ctrl.connect()

            self.polling = True
            self.in_alarm = False
            self.machine_state = "Unknown"
            self.status_text.set(f"Connected: {port} @ {baud_int}")

            if hasattr(self, "connection_status_var"):
                self.connection_status_var.set("Connected")

            self._append_console(f"> Connected to {port} @ {baud_int}")

        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))
    
    def _disconnect(self) -> None:
        self._stop_all_motion_and_jobs()
        self._stop_roller_jog()
        self._clear_pending_jog()
        self.polling = False
        self.ctrl.disconnect()
        self.machine_state = "Disconnected"
        self.status_text.set("Disconnected")
        self.state_text.set("State: --")
        self.machine_pos_text.set("MPos: --")
        self.work_pos_text.set("WPos: --")
        self.after(0, lambda: self.job_progress_text.set("Job: idle"))
        self.limit_switch_text.set("Limits: --")
        if hasattr(self, "connection_status_var"):
            self.connection_status_var.set("Disconnected")
        self._append_console("> Disconnected")

    def _refresh_ports(self):
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_var.set(ports[0])

    def _send_line(self, line: str) -> None:
        if not self.ctrl.is_connected:
            return
        try:
            self.ctrl.send_line(line)
            self._append_console(f">> {line}")
        except Exception as e:
            self._append_console(f"[SEND ERROR] {e}")

    def _send_mdi(self) -> None:
        line = self.mdi_var.get().strip()
        if not line:
            return
        if self.is_job_running():
            messagebox.showwarning("Busy", "Cannot send MDI while a job is running.")
            return
        self._send_line(line)
        self.mdi_var.set("")

    def _send_raw_command(self) -> None:
        cmd = self.raw_cmd_var.get().strip()
        if not cmd:
            return
        if cmd == "?":
            self.ctrl.send_realtime(b"?")
            self._append_console(">> [STATUS] ?")
        else:
            self._send_line(cmd)

    def _request_status(self) -> None:
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"?")
            self._append_console(">> [STATUS] ?")

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
            self._clear_pending_jog()
            self.ctrl.send_realtime(b"\x18")
            self._append_console(">> [RESET] Ctrl-X")

    def _home(self) -> None:
        if self.is_job_running():
            return
        self._send_line("$H")

    def _unlock(self) -> None:
        if self.is_job_running():
            return
        self.in_alarm = False
        self._send_line("$X")
        time.sleep(0.1)
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"?")

    def _force_stop(self) -> None:
        self._append_console("\n!!! FORCE STOP !!!\n")
        self.jogging = False
        self.set_job_running(False)
        self.set_job_paused(False)
        self.set_job_stopping(True)
        self.waiting_for_ack = False
        self._cancel_jog()
        self._stop_roller_jog()
        self._clear_pending_jog()
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"\x18")
            time.sleep(0.05)
            self.ctrl.send_realtime(b"\x18")
            time.sleep(0.05)
            self.ctrl.send_realtime(b"\x18")
            self.ctrl.send_realtime(b"!")
            self._append_console(">> [FORCE STOP] Sent Ctrl-X (3x) + Hold")
        self._append_console(">> All motion stopped\n")
        if hasattr(self, "jog_status_var"):
            self.jog_status_var.set("JOG: IDLE")

    def set_job_running(self, value: bool) -> None:
        with self.job_lock:
            self.job_running = value

    def is_job_running(self) -> bool:
        with self.job_lock:
            return self.job_running

    def set_job_paused(self, value: bool) -> None:
        with self.job_lock:
            self.job_paused = value

    def is_job_paused(self) -> bool:
        with self.job_lock:
            return self.job_paused

    def set_job_stopping(self, value: bool) -> None:
        with self.job_lock:
            self.job_stopping = value

    def is_job_stopping(self) -> bool:
        with self.job_lock:
            return self.job_stopping

    # =========================
    # OUTPUTS
    # =========================
    def _light_on(self) -> None:
        if not self.is_job_running():
            self._send_line(LIGHT_ON_CMD)

    def _light_off(self) -> None:
        if not self.is_job_running():
            self._send_line(LIGHT_OFF_CMD)

    def _spindle_on(self) -> None:
        if self.is_job_running():
            return
        try:
            raw = self.spindle_speed_var.get().strip()
            speed = int(float(raw or "4000"))
            if speed <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Spindle Error", "Enter a spindle speed > 0.")
            return

        self._send_line(f"M3 S{speed}")

        if hasattr(self, "spindle_status_var"):
            self.spindle_status_var.set(f"Spindle: ON ({speed} RPM)")

    def _spindle_off(self) -> None:
        if not self.is_job_running():
            self._send_line(SPINDLE_OFF_CMD)

        if hasattr(self, "spindle_status_var"):
            self.spindle_status_var.set("Spindle: OFF")

    

    # =========================
    # JOGGING
    # =========================
    def _safe_to_jog(self) -> bool:
        if not self.ctrl.is_connected:
            return False
        if self.is_job_running():
            return False
        if self.in_alarm:
            return False
        return self.machine_state in ("Idle", "Jog", "Unknown")

    def _clear_pending_jog(self) -> None:
        if self._jog_hold_after_id is not None:
            try:
                self.after_cancel(self._jog_hold_after_id)
            except Exception:
                pass
            self._jog_hold_after_id = None

        self._jog_hold_started = False
        self._pending_jog_axis_moves = None
        self._pending_jog_button = None

    def _get_jog_params_for_axis(self, axis: str):
        try:
            axis = axis.upper()

            if axis in ("X", "Y", "Z"):
                return float(self.jog_step_var.get()), float(self.jog_feed_var.get())

            if axis == "ROLLER":
                return float(self.roller_step_var.get()), float(self.roller_feed_var.get())

            if axis == "A":
                return float(self.a_rot_step_var.get()), float(self.a_rot_feed_var.get())

            if axis == "B":
                return float(self.b_rot_step_var.get()), float(self.b_rot_feed_var.get())

            if axis == "C":
                return float(self.c_rot_step_var.get()), float(self.c_rot_feed_var.get())
        except Exception:
            pass

        return 1.0, 1000.0

    def _build_jog_command(self, axis_moves: dict):
        if not axis_moves:
            return None

        parts = []
        feed = None

        for axis, direction in axis_moves.items():
            axis = axis.upper()
            if axis == "ROLLER":
                continue

            step, axis_feed = self._get_jog_params_for_axis(axis)
            if feed is None:
                feed = axis_feed
            parts.append(f"{axis}{direction * abs(step):.2f}")

        if not parts or feed is None:
            return None

        return "$J=G91 " + " ".join(parts) + f" F{abs(feed):.1f}"

    def _single_step_jog(self, axis_moves: dict) -> None:
        if set(axis_moves.keys()) == {"ROLLER"}:
            forward = axis_moves["ROLLER"] > 0
            self._roller_step_once(forward=forward)
            return

        if not self._safe_to_jog():
            return

        cmd = self._build_jog_command(axis_moves)
        if cmd:
            self._send_line(cmd)

    def _on_jog_press(self, axis_moves: dict, btn: tk.Button) -> None:
        btn.config(bg="#666666")

        self._clear_pending_jog()
        self._pending_jog_axis_moves = axis_moves
        self._pending_jog_button = btn
        self._jog_hold_started = False

        mode = (self.jog_mode_var.get() or "step").strip().lower()

        if mode == "continuous":
            if self.jogging or self.roller_jogging:
                self._cancel_jog()
                self._stop_roller_jog()
                return

            self.active_jog_button = btn
            btn.config(bg="#FFBE6B")
            self._begin_continuous_jog(axis_moves)

    def _begin_continuous_jog(self, axis_moves: dict) -> None:
        self._jog_hold_after_id = None

        if set(axis_moves.keys()) == {"ROLLER"}:
            forward = axis_moves["ROLLER"] > 0
            self._jog_hold_started = True
            self._start_roller_jog(forward=forward)
            return

        if not self._safe_to_jog():
            return

        self._jog_hold_started = True
        self._start_continuous_jog(axis_moves)

    def _on_jog_release(self, btn: tk.Button) -> None:
        mode = (self.jog_mode_var.get() or "step").strip().lower()

        if mode != "continuous" or btn is not self.active_jog_button:
            btn.config(bg="#D9D9D9")

        if self._jog_hold_after_id is not None:
            try:
                self.after_cancel(self._jog_hold_after_id)
            except Exception:
                pass
            self._jog_hold_after_id = None

        axis_moves = self._pending_jog_axis_moves

        if mode == "step" and axis_moves:
            self._single_step_jog(axis_moves)

        self._jog_hold_started = False
        self._pending_jog_axis_moves = None
        self._pending_jog_button = None

    def _start_continuous_jog(self, axis_moves: dict) -> None:
        if "ROLLER" in axis_moves:
            return
        if not self._safe_to_jog() or self.jogging:
            return

        self.jogging = True

        axis_name = ", ".join(axis_moves.keys())
        if hasattr(self, "jog_status_var"):
            self.jog_status_var.set(f"JOGGING: {axis_name}")

        def jog_loop() -> None:
            while self.jogging and self.ctrl.is_connected:
                if not self._safe_to_jog():
                    break

                try:
                    cmd = self._build_jog_command(axis_moves)
                    if cmd:
                        self.ctrl.write_raw(cmd + "\n")
                except Exception:
                    break

                time.sleep(0.05)

            self.jogging = False
            self.after(0, self._cancel_jog)

        self.jog_thread = threading.Thread(target=jog_loop, daemon=True)
        self.jog_thread.start()

    def _cancel_jog(self, send_hold: bool = True) -> None:
        self.jogging = False
        self._stop_roller_jog()
        self._clear_jog_watchdog()

        if self.active_jog_button is not None:
            try:
                self.active_jog_button.config(bg="#D9D9D9")
            except Exception:
                pass
            self.active_jog_button = None

        if hasattr(self, "jog_status_var"):
            self.jog_status_var.set("JOG: IDLE")

        if self.ctrl.is_connected:
            try:
                self.ctrl.send_realtime(b"\x85")  # jog cancel
                if send_hold:
                    self.ctrl.send_realtime(b"!")  # optional feed hold
            except Exception:
                pass

    def _arm_jog_watchdog(self) -> None:
        if self._jog_watchdog_after_id is not None:
            try:
                self.after_cancel(self._jog_watchdog_after_id)
            except Exception:
                pass

        self._jog_watchdog_after_id = self.after(700, self._watchdog_stop_jog)

    def _clear_jog_watchdog(self) -> None:
        if self._jog_watchdog_after_id is not None:
            try:
                self.after_cancel(self._jog_watchdog_after_id)
            except Exception:
                pass
            self._jog_watchdog_after_id = None

    def _watchdog_stop_jog(self) -> None:
        self._jog_watchdog_after_id = None
        self._append_console("[JOG] watchdog stop")
        self._cancel_jog()


    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"

        # Jog buttons
        for btn in getattr(self, "jog_buttons", []):
            btn.config(state=state)

        # Machine control buttons
        for btn in getattr(self, "machine_buttons", []):
            btn.config(state=state)

        # Output buttons (optional if you track them)
        for btn in getattr(self, "output_buttons", []):
            btn.config(state=state)



    # =========================
    # ROLLER (PI-CONTROLLED)
    # =========================
    def _roller_step_once(self, forward: bool) -> None:
        if self.rollers is None:
            self._append_console("[ROLLER] controller unavailable")
            return

        try:
            distance_mm = float(self.roller_step_var.get())
            speed_mm_min = float(self.roller_feed_var.get())
            speed_mm_s = speed_mm_min / 60.0
            if distance_mm <= 0 or speed_mm_s <= 0:
                raise ValueError
        except Exception:
            self._append_console("[ROLLER] invalid step/feed settings")
            return

        def worker():
            try:
                self.rollers.feed_distance(
                    distance_mm=distance_mm,
                    speed_mm_s=speed_mm_s,
                    forward=forward,
                )
            except Exception as exc:
                self._append_console(f"[ROLLER STEP ERROR] {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _start_roller_jog(self, forward: bool) -> None:
        if self.roller_jogging or self.rollers is None:
            return

        try:
            speed_mm_min = float(self.roller_feed_var.get())
            speed_mm_s = speed_mm_min / 60.0
            if speed_mm_s <= 0:
                raise ValueError
        except Exception:
            self._append_console("[ROLLER] invalid feed setting")
            return

        self.roller_jogging = True

        try:
            self.rollers.start_continuous(
                speed_mm_s=speed_mm_s,
                forward=forward,
            )
        except Exception as exc:
            self.roller_jogging = False
            self._append_console(f"[ROLLER JOG ERROR] {exc}")

    def _stop_roller_jog(self) -> None:
        self.roller_jogging = False
        if self.rollers is None:
            return
        try:
            self.rollers.stop()
        except Exception as exc:
            self._append_console(f"[ROLLER STOP ERROR] {exc}")

    def _stop_all_motion_and_jobs(self) -> None:
        self.jogging = False
        self.roller_jogging = False
        self.set_job_running(False)
        self.set_job_paused(False)
        self.set_job_stopping(True)

    # =========================
    # PHOTOGRAMMETRY
    # =========================
    def _gpio_pulse_high(self, pin_num: int, duration_s: float) -> None:
        """
        Output a high signal to the specified GPIO pin for a given duration.
        Runs in a separate thread to avoid blocking the UI.
        
        Args:
            pin_num: GPIO pin number
            duration_s: Duration to keep the pin high (in seconds)
        """
        def gpio_worker():
            try:
                try:
                    import gpiozero
                    pin = gpiozero.OutputDevice(pin_num, active_high=True)
                    pin.on()
                    self._append_console(f"[GPIO] Pin {pin_num} set HIGH")
                    time.sleep(duration_s)
                    pin.off()
                    self._append_console(f"[GPIO] Pin {pin_num} set LOW (after {duration_s}s)")
                    pin.close()
                except ImportError:
                    try:
                        import RPi.GPIO as GPIO
                        GPIO.setmode(GPIO.BCM)
                        GPIO.setup(pin_num, GPIO.OUT)
                        GPIO.output(pin_num, GPIO.HIGH)
                        self._append_console(f"[GPIO] Pin {pin_num} set HIGH")
                        time.sleep(duration_s)
                        GPIO.output(pin_num, GPIO.LOW)
                        self._append_console(f"[GPIO] Pin {pin_num} set LOW (after {duration_s}s)")
                        GPIO.cleanup(pin_num)
                    except ImportError:
                        self._append_console(f"[GPIO] WARNING: No GPIO library available (gpiozero or RPi.GPIO)")
                    except Exception as e:
                        self._append_console(f"[GPIO] ERROR with RPi.GPIO: {e}")
            except Exception as e:
                self._append_console(f"[GPIO] Unexpected error: {e}")
        
        # Run in a separate thread to avoid blocking the UI
        threading.Thread(target=gpio_worker, daemon=True).start()

    def _start_photogrammetry_camera(self) -> None:
        self.photogrammetry_status_var.set("Camera running")
        self.photogrammetry_camera_info_var.set("Live camera running (stub)")

    def _stop_photogrammetry_camera(self) -> None:
        self.photogrammetry_status_var.set("Idle")
        self.photogrammetry_camera_info_var.set("Camera stopped")

    def _start_photogrammetry_process(self) -> None:
        self.photogrammetry_status_var.set("Processing...")
        self.photogrammetry_info_text.set("Photogrammetry process started")
        self._append_console("> Start photogrammetry process")
        
        # Output 2-second high signal to GPIO pin 4
        self._gpio_pulse_high(pin_num=4, duration_s=2.0)


    def _load_photogrammetry_mesh(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Photogrammetry Mesh",
            filetypes=[("Mesh files", "*.stl *.obj *.ply"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            import trimesh

            self.photogrammetry_mesh_path = path
            self.photogrammetry_raw_mesh = trimesh.load(path, force="mesh")

            # Handle scene -> mesh if needed
            if isinstance(self.photogrammetry_raw_mesh, trimesh.Scene):
                if not self.photogrammetry_raw_mesh.geometry:
                    raise ValueError("Scene contains no geometry.")
                self.photogrammetry_raw_mesh = trimesh.util.concatenate(
                    tuple(self.photogrammetry_raw_mesh.geometry.values())
                )

            # reset packaging orientation when a new mesh is loaded
            self.photogrammetry_rot_x = 0.0
            self.photogrammetry_rot_y = 0.0
            self.photogrammetry_rot_z = 0.0

            self.photogrammetry_mesh_info_var.set(
                f"Loaded mesh: {os.path.basename(path)} | "
                f"{len(self.photogrammetry_raw_mesh.vertices)} verts | "
                f"{len(self.photogrammetry_raw_mesh.faces)} faces"
            )
            extents = self.photogrammetry_raw_mesh.extents
            height_z = extents[2]

            self.photogrammetry_info_text.set(
                f"{os.path.basename(path)} | "
                f"{len(self.photogrammetry_raw_mesh.vertices)} verts | "
                f"{len(self.photogrammetry_raw_mesh.faces)} faces | "
                f"H={height_z:.1f}"
            )
            self.photogrammetry_status_var.set("Mesh loaded")

            self._draw_photogrammetry_mesh_preview()

        except Exception as exc:
            messagebox.showerror("Mesh Load Error", str(exc))

    def _clear_photogrammetry_session(self) -> None:
        self.photogrammetry_mesh_path = None
        self.photogrammetry_raw_mesh = None
        self.photogrammetry_rot_x = 0.0
        self.photogrammetry_rot_y = 0.0
        self.photogrammetry_rot_z = 0.0
        self.photogrammetry_status_var.set("Idle")
        self.photogrammetry_info_text.set("No photogrammetry session yet")
        self.photogrammetry_camera_info_var.set("Camera idle")
        self.photogrammetry_mesh_info_var.set("No reconstructed mesh loaded")
        self._draw_photogrammetry_mesh_preview()

    def _set_photogrammetry_mesh_view(self, view_name) -> None:
        if self.photogrammetry_ax is None:
            return

        mapping = {
            "iso": (20, 35),
            "front": (0, -90),
            "side": (0, 0),
            "top": (90, -90),
        }
        elev, azim = mapping.get(view_name, (20, 35))
        self.photogrammetry_elev = elev
        self.photogrammetry_azim = azim

        if self.photogrammetry_ax is not None:
            self.photogrammetry_ax.view_init(elev=elev, azim=azim)
        if self.photogrammetry_canvas is not None:
            self.photogrammetry_canvas.draw_idle()

    def _reset_photogrammetry_mesh_view(self) -> None:
        self._set_photogrammetry_mesh_view("iso")

    def _rotate_photogrammetry_mesh(self, axis: str, delta_deg: float) -> None:
        axis = axis.lower()

        if axis == "x":
            self.photogrammetry_rot_x += delta_deg
        elif axis == "y":
            self.photogrammetry_rot_y += delta_deg
        elif axis == "z":
            self.photogrammetry_rot_z += delta_deg
        else:
            return

        self._draw_photogrammetry_mesh_preview()

    def _use_photogrammetry_orientation(self) -> None:
        if self.photogrammetry_raw_mesh is None:
            return

        try:
            import numpy as np
            import trimesh
            import os

            mesh = self.photogrammetry_raw_mesh.copy()
            vertices = np.asarray(mesh.vertices, dtype=float)

            # center mesh
            center = vertices.mean(axis=0)
            v = vertices - center

            # rotation matrices
            def rot_x(deg):
                r = np.radians(deg)
                c, s = np.cos(r), np.sin(r)
                return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])

            def rot_y(deg):
                r = np.radians(deg)
                c, s = np.cos(r), np.sin(r)
                return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

            def rot_z(deg):
                r = np.radians(deg)
                c, s = np.cos(r), np.sin(r)
                return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

            rotation = (
                rot_z(self.photogrammetry_rot_z)
                @ rot_y(self.photogrammetry_rot_y)
                @ rot_x(self.photogrammetry_rot_x)
            )

            rotated = (v @ rotation.T) + center

            mesh.vertices = rotated

            # ---- save new STL ----
            import os

            base_name = os.path.splitext(os.path.basename(self.photogrammetry_mesh_path))[0]

            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            out_dir = os.path.join(project_root, "data", "stl", "prepared")

            os.makedirs(out_dir, exist_ok=True)

            out_path = os.path.join(out_dir, base_name + "_oriented.stl")

            mesh.export(out_path)

            # update state
            self.photogrammetry_mesh_path = out_path
            self.photogrammetry_raw_mesh = mesh

            self.photogrammetry_info_text.set(
                f"Saved oriented mesh: {os.path.basename(out_path)}"
            )

            self._append_console(f"> Saved oriented STL: {out_path}")

        except Exception as exc:
            messagebox.showerror("Orientation Save Error", str(exc))

    def _draw_photogrammetry_mesh_preview(self) -> None:
        if self.photogrammetry_ax is None or self.photogrammetry_canvas is None:
            return

        ax = self.photogrammetry_ax
        fig = self.photogrammetry_figure

        ax.clear()
        ax.set_facecolor("#111111")
        fig.patch.set_facecolor("#111111")
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        ax.set_title("Mesh Preview", color="white")

        if self.photogrammetry_raw_mesh is None:
            ax.text2D(
                0.5, 0.5,
                "No reconstructed mesh loaded",
                transform=ax.transAxes,
                color="#CCCCCC",
                ha="center",
                va="center",
            )
            self.photogrammetry_canvas.draw_idle()
            return

        try:
            import numpy as np

            mesh = self.photogrammetry_raw_mesh
            vertices = np.asarray(mesh.vertices, dtype=float)

            # rotate about mesh center (actual model orientation)
            center = vertices.mean(axis=0)
            v = vertices - center

            def rot_x(deg: float):
                r = np.radians(deg)
                c, s = np.cos(r), np.sin(r)
                return np.array([
                    [1, 0, 0],
                    [0, c, -s],
                    [0, s, c],
                ])

            def rot_y(deg: float):
                r = np.radians(deg)
                c, s = np.cos(r), np.sin(r)
                return np.array([
                    [c, 0, s],
                    [0, 1, 0],
                    [-s, 0, c],
                ])

            def rot_z(deg: float):
                r = np.radians(deg)
                c, s = np.cos(r), np.sin(r)
                return np.array([
                    [c, -s, 0],
                    [s, c, 0],
                    [0, 0, 1],
                ])

            rotation = rot_z(self.photogrammetry_rot_z) @ rot_y(self.photogrammetry_rot_y) @ rot_x(self.photogrammetry_rot_x)
            rotated_vertices = (v @ rotation.T) + center

            # fast preview: downsampled point cloud
            max_points = 4000
            if len(rotated_vertices) > max_points:
                idx = np.random.choice(len(rotated_vertices), max_points, replace=False)
                preview_vertices = rotated_vertices[idx]
            else:
                preview_vertices = rotated_vertices

            ax.scatter(
                preview_vertices[:, 0],
                preview_vertices[:, 1],
                preview_vertices[:, 2],
                s=1,
                c="#BBBBBB",
                depthshade=False,
            )

            min_corner = rotated_vertices.min(axis=0)
            max_corner = rotated_vertices.max(axis=0)
            plot_center = (min_corner + max_corner) / 2.0
            extent = (max_corner - min_corner).max() / 2.0

            if extent <= 0:
                extent = 1.0

            extent *= 1.1

            ax.set_xlim(plot_center[0] - extent, plot_center[0] + extent)
            ax.set_ylim(plot_center[1] - extent, plot_center[1] + extent)
            ax.set_zlim(plot_center[2] - extent, plot_center[2] + extent)
            ax.set_box_aspect([1, 1, 1])
            ax.margins(0)

            ax.view_init(
                elev=self.photogrammetry_elev,
                azim=self.photogrammetry_azim,
            )

            ax.grid(False)
            ax.xaxis.pane.fill = False
            ax.yaxis.pane.fill = False
            ax.zaxis.pane.fill = False

            try:
                ax.set_axis_off()
            except Exception:
                pass

            ax.text2D(
                0.03,
                0.95,
                os.path.basename(self.photogrammetry_mesh_path),
                transform=ax.transAxes,
                color="white",
            )
            ax.text2D(
                0.03,
                0.90,
                f"Rx {self.photogrammetry_rot_x:.0f}°   "
                f"Ry {self.photogrammetry_rot_y:.0f}°   "
                f"Rz {self.photogrammetry_rot_z:.0f}°",
                transform=ax.transAxes,
                color="#BBBBBB",
            )

        except Exception as exc:
            ax.text2D(
                0.5, 0.5,
                f"Mesh preview error:\n{exc}",
                transform=ax.transAxes,
                color="#FF8888",
                ha="center",
                va="center",
            )
        # --- simple XYZ indicator (super lightweight) ---
        ax.text2D(0.90, 0.92, "X →", transform=ax.transAxes, color="#FF5555", fontsize=8)
        ax.text2D(0.90, 0.88, "Y →", transform=ax.transAxes, color="#55FF55", fontsize=8)
        ax.text2D(0.90, 0.84, "Z ↑", transform=ax.transAxes, color="#5599FF", fontsize=8)

        self.photogrammetry_canvas.draw_idle()

    def _lay_flat_photogrammetry_mesh(self):
        self.photogrammetry_rot_x = 90.0
        self.photogrammetry_rot_y = 0.0
        self.photogrammetry_rot_z = 0.0
        self._draw_photogrammetry_mesh_preview()

    # =========================
    # GCODE / RUN
    # =========================

    def _populate_gcode_table(self):
        if not hasattr(self, "gcode_table_rows_frame") or self.gcode_table_rows_frame is None:
            return

        for child in self.gcode_table_rows_frame.winfo_children():
            child.destroy()

        self.gcode_row_frames = []
        self.gcode_row_status_labels = []
        self.gcode_row_code_labels = []

        for line in self.gcode_lines:
            row = tk.Frame(self.gcode_table_rows_frame, bg="#1e1e1e")
            row.pack(fill="x", expand=True)

            status_lbl = tk.Label(
                row,
                text="",
                bg="#1e1e1e",
                fg="#dcdcdc",
                font=("Arial", 8, "bold"),
                bd=1,
                relief="solid",
                width=8,
                anchor="center",
            )
            status_lbl.pack(side="left", fill="y")

            code_lbl = tk.Label(
                row,
                text=line,
                bg="#1e1e1e",
                fg="#dcdcdc",
                font=("Courier New", 11),
                bd=1,
                relief="solid",
                anchor="w",
                justify="left",
                padx=6,
            )
            code_lbl.pack(side="left", fill="x", expand=True)

            self.gcode_row_frames.append(row)
            self.gcode_row_status_labels.append(status_lbl)
            self.gcode_row_code_labels.append(code_lbl)

        if hasattr(self, "gcode_table_canvas") and self.gcode_table_canvas is not None:
            self.gcode_table_canvas.update_idletasks()
            self.gcode_table_canvas.configure(scrollregion=self.gcode_table_canvas.bbox("all"))


    def _load_gcode_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load G-code File",
            filetypes=[("G-code files", "*.nc *.gcode *.tap *.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                self.gcode_lines = f.read().splitlines()

            self.file_text.set(os.path.basename(path))

            # --- existing text viewer ---
            if self.gcode_viewer is not None:
                self.gcode_viewer.delete("1.0", "end")
                self.gcode_viewer.insert("1.0", "\n".join(self.gcode_lines))

            # --- NEW: populate 2-column G-code table ---
            if hasattr(self, "_populate_gcode_table"):
                self._populate_gcode_table()

            # --- existing preview parsing ---
            self.gcode_segments, self.gcode_bounds = GCodeParser.parse_lines(self.gcode_lines)
            self.preview_total_time_s = float(self.gcode_bounds.get("total_time_s", 0.0))
            self.preview_estimated_time = self.preview_total_time_s
            self.preview_elapsed_s = 0.0
            self.preview_last_tick_s = None
            self.preview_scrub_index = 0.0
            self.preview_scrubber_var.set(0.0)

            total_s = int(self.preview_total_time_s)
            self.preview_time_var.set(
                f"Time: 00:00/{total_s // 60:02d}:{total_s % 60:02d}"
            )
            self.preview_segment_var.set(f"Segments: 0/{len(self.gcode_segments)}")
            self.job_progress_text.set(f"Job: loaded ({len(self.gcode_lines)} lines)")
            self._append_console(f"> Loaded G-code file: {path}")

            try:
                self._refresh_preview_unified()
            except Exception:
                pass

        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _load_gcode_from_string(self, gcode: str, display_name: str = "Generated G-code") -> None:
        try:
            self.gcode_lines = gcode.splitlines()
            self.file_text.set(display_name)

            # same viewer update path as file load
            if self.gcode_viewer is not None:
                self.gcode_viewer.delete("1.0", "end")
                self.gcode_viewer.insert("1.0", "\n".join(self.gcode_lines))

            # same table refresh path as file load
            if hasattr(self, "_populate_gcode_table"):
                self._populate_gcode_table()

            # same preview parsing path as file load
            self.gcode_segments, self.gcode_bounds = GCodeParser.parse_lines(self.gcode_lines)
            self.preview_total_time_s = float(self.gcode_bounds.get("total_time_s", 0.0))
            self.preview_estimated_time = self.preview_total_time_s
            self.preview_elapsed_s = 0.0
            self.preview_last_tick_s = None
            self.preview_scrub_index = 0.0
            self.preview_scrubber_var.set(0.0)

            total_s = int(self.preview_total_time_s)
            self.preview_time_var.set(
                f"Time: 00:00/{total_s // 60:02d}:{total_s % 60:02d}"
            )
            self.preview_segment_var.set(f"Segments: 0/{len(self.gcode_segments)}")
            self.job_progress_text.set(f"Job: loaded ({len(self.gcode_lines)} lines)")
            self._append_console(f"> Loaded G-code into Run tab: {display_name}")

            try:
                self._refresh_preview_unified()
            except Exception:
                pass

        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _load_current_window_gcode(self) -> None:
        try:
            self._generate_current_window_gcode()
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))
            self._append_console(f"[LOAD CURRENT WINDOW ERROR] {exc}")

    def _start_slats_job(self):
        if self.is_job_running():
            return

        if not self.ctrl.is_connected:
            messagebox.showerror("Run Error", "Not connected to controller.")
            return

        try:
            ops = getattr(self, "slats_cam_continuous_ops", None)

            if not ops:
                messagebox.showerror(
                    "Run Error",
                    "No continuous job prepared. Click 'Prepare Continuous Job' first.",
                )
                return

            roller_speed_mm_s = float(self.roller_feed_var.get()) / 60.0

        except Exception as exc:
            messagebox.showerror("Run Error", f"Failed to build job: {exc}")
            return

        self._cancel_jog()
        self._stop_roller_jog()
        self._clear_pending_jog()

        self.set_job_running(True)
        self.set_job_stopping(False)
        self.set_job_paused(False)
        self._set_controls_enabled(False)
        self.job_progress_text.set("Job: running")
        self._append_console("> Running slats job")

        runner = JobRunner(
            controller=self.ctrl,
            rollers=self.rollers,
            roller_speed_mm_s=roller_speed_mm_s,
            log_fn=self._append_console,
        )

        self._job_runner = runner

        def worker():
            try:
                if self.is_job_stopping():
                    self._append_console("> Slats job stopped before start")
                    return

                while self.is_job_paused() and not self.is_job_stopping():
                    time.sleep(0.05)

                if self.is_job_stopping():
                    self._append_console("> Slats job stopped")
                    return

                runner.run(
                    ops,
                    should_stop=self.is_job_stopping,
                    should_pause=self.is_job_paused,
                    job_timeout_s=2 * 60 * 60,
                )

                if self.is_job_stopping():
                    self._append_console("> Slats job stopped")
                else:
                    self.after(0, lambda: self._append_console("> Job complete"))

            except Exception as exc:
                self._append_console(f"[JOB ERROR] {exc}")

            finally:
                self.set_job_running(False)
                self.set_job_paused(False)
                self.set_job_stopping(False)
                self.after(0, lambda: self._set_controls_enabled(True))
                self.after(0, lambda: self.job_progress_text.set("Job: idle"))

        self.job_thread = threading.Thread(target=worker, daemon=True)
        self.job_thread.start()
        

    def _pick_packed_slat(self, x, y):
        _, to_world, _ = self._overview_view_transform()
        wx, wy = to_world(x, y)
        p = Point(wx, wy)

        best_sid = None
        best_area = None
        for sid, item in self.packed_items.items():
            geom = item["geom"]
            try:
                if geom.contains(p) or geom.buffer(1.5).contains(p):
                    area = geom.area
                    if best_area is None or area < best_area:
                        best_area = area
                        best_sid = sid
            except Exception:
                pass
        return best_sid


    def _pick_feed_boundary(self, canvas_x, canvas_y, tol_px=12):
        if len(self.feed_windows) < 2:
            return None

        to_canvas, _, _ = self._overview_view_transform()
        miny, maxy = self._sheet_y_bounds()

        best_idx = None
        best_dist = None
        for j in range(len(self.feed_windows) - 1):
            _idx, _x0, x1 = self.feed_windows[j]
            hx, hy0 = to_canvas(x1, miny)
            _hx, hy1 = to_canvas(x1, maxy)
            hy_mid = 0.5 * (hy0 + hy1)

            if canvas_y < min(hy0, hy1) - 20 or canvas_y > max(hy0, hy1) + 20:
                continue

            dist = min(
                abs(canvas_x - hx),
                ((canvas_x - hx) ** 2 + (canvas_y - hy_mid) ** 2) ** 0.5,
            )
            if dist <= tol_px and (best_dist is None or dist < best_dist):
                best_dist = dist
                best_idx = j

        return best_idx


    def _move_feed_boundary(self, boundary_index, new_x, min_window_width=20.0):
        if boundary_index is None:
            return
        if not (0 <= boundary_index < len(self.feed_windows) - 1):
            return
        if self.sheet_mm is None or self.sheet_mm.is_empty:
            return

        max_window_len = float(self.slats_cam_feed_window_mm.get() or "200.0")
        _left_idx, left_x0, _left_x1 = self.feed_windows[boundary_index]
        _sheet_minx, _sheet_miny, sheet_maxx, _sheet_maxy = self.sheet_mm.bounds

        lo = left_x0 + min_window_width
        hi = min(left_x0 + max_window_len, sheet_maxx)
        clamped_x = max(lo, min(hi, new_x))

        new_windows = []
        for j in range(boundary_index):
            _idx, x0, x1 = self.feed_windows[j]
            new_windows.append((j, x0, x1))

        new_windows.append((boundary_index, left_x0, clamped_x))

        x0 = clamped_x
        idx = boundary_index + 1
        while x0 < sheet_maxx - 1e-9:
            x1 = min(x0 + max_window_len, sheet_maxx)
            if x1 - x0 < 1e-6:
                break
            new_windows.append((idx, x0, x1))
            x0 = x1
            idx += 1

        self.feed_windows = new_windows
        self.active_window_index = min(self.active_window_index, len(self.feed_windows) - 1)
        self._update_window_info()

    def _start_gcode_job(self) -> None:
        if self.is_job_running():
            return

        if not self.ctrl.is_connected:
            messagebox.showerror("Run Error", "Not connected to controller.")
            return

        if not self.gcode_lines:
            messagebox.showerror("Run Error", "No G-code loaded.")
            return

        self._cancel_jog()
        self._stop_roller_jog()
        self._clear_pending_jog()

        self.set_job_stopping(False)
        self.set_job_paused(False)
        self.set_job_running(True)
        self._set_controls_enabled(False)
        self.current_line_index = 0
        self.job_progress_text.set("Job: running")
        self._append_console("> Running raw G-code")

        job_start_time = time.time()
        max_job_duration_seconds = 3600 * 2  # 2 hours max

        def worker():
            try:
                for i, raw_line in enumerate(self.gcode_lines, start=1):
                    if self.is_job_stopping():
                        break

                    if not self.ctrl.is_connected:
                        self.after(0, lambda: self._append_console("[JOB ERROR] Lost connection to controller"))
                        self.after(0, lambda: self._append_console("[RECOVERY] Attempting reconnect in 2 seconds..."))
                        time.sleep(2)
                        try:
                            self.ctrl.disconnect()
                            time.sleep(0.2)
                            self.ctrl.connect()
                            self.after(0, lambda: self._append_console("[RECOVERY] Reconnected! Resuming job..."))
                        except Exception as e:
                            self.after(0, lambda e=e: self._append_console(f"[JOB ERROR] Reconnect failed: {e}"))
                            break

                    while self.is_job_paused() and not self.is_job_stopping():
                        time.sleep(0.05)

                    if self.is_job_stopping():
                        break

                    line = raw_line.strip()

                    if not line:
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "SKIP"))
                        continue

                    self.current_line_index = i
                    self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "RUN"))
                    self.after(0, lambda l=line: self._append_console(f">> {l}"))

                    elapsed = time.time() - job_start_time
                    if elapsed > max_job_duration_seconds:
                        self.after(
                            0,
                            lambda e=elapsed: self._append_console(
                                f"[JOB ERROR] Job timeout after {e:.0f}s "
                                f"({int(e / 60)}m {int(e % 60)}s)"
                            ),
                        )
                        if self.ctrl.is_connected:
                            self.ctrl.send_realtime(b"\x18")
                            time.sleep(0.2)
                        break

                    try:
                        if "m3" in line.lower() or "m4" in line.lower():
                            self.after(
                                0,
                                lambda l=line: self._append_console(f">> [SPINDLE] Starting spindle: {l.strip()}"),
                            )

                        reply = self.ctrl.send_line(line, timeout=10.0)

                        if "m3" in line.lower() or "m4" in line.lower():
                            self.after(0, lambda: self._append_console("[SPINDLE] Waiting for spindle to reach speed..."))
                            time.sleep(1.0)

                    except TimeoutError:
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "TIMEOUT"))
                        self.after(0, lambda: self._append_console("[JOB ERROR] Timeout waiting for OK"))
                        if self.ctrl.is_connected:
                            self.ctrl.send_realtime(b"\x18")
                            time.sleep(0.2)
                        break

                    except Exception as exc:
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "ERR"))
                        self.after(0, lambda exc=exc: self._append_console(f"[JOB ERROR] {exc}"))
                        if self.ctrl.is_connected:
                            self.ctrl.send_realtime(b"\x18")
                            time.sleep(0.2)
                        break

                    low = reply.strip().lower()

                    if low == "ok":
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "OK"))
                    elif low.startswith("alarm"):
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "ERR"))
                        self.after(0, lambda r=reply: self._append_console(f"[ALARM] {r}"))
                        break
                    elif low.startswith("error"):
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "ERR"))
                        self.after(0, lambda r=reply: self._append_console(f"[JOB ERROR] {r}"))
                        break
                    else:
                        self.after(0, lambda idx=i: self._set_gcode_line_status(idx, "ERR"))
                        self.after(0, lambda r=reply: self._append_console(f"[JOB ERROR] Unexpected reply: {r}"))
                        break

                if self.is_job_stopping():
                    self.after(0, lambda: self._append_console("> Job stopped"))
                else:
                    self.after(0, lambda: self._append_console("> Job complete"))

            except Exception as exc:
                self.after(0, lambda exc=exc: self._append_console(f"[JOB ERROR] {exc}"))

            finally:
                self.set_job_running(False)
                self.set_job_paused(False)
                self.set_job_stopping(False)
                self.after(0, lambda: self._set_controls_enabled(True))
                self.after(0, lambda: self.job_progress_text.set("Job: idle"))

        self.job_thread = threading.Thread(target=worker, daemon=True)
        self.job_thread.start()

    def _pause_gcode_job(self) -> None:
        should_hold = False

        with self.job_lock:
            if self.job_running and not self.job_paused:
                self.job_paused = True
                should_hold = True
            elif self.job_paused:
                self._append_console("[WARN] Job already paused")
                return
            else:
                return

        if should_hold:
            self.ctrl.send_realtime(b"!")
            self._append_console(">> [JOB HOLD] !")

    def _set_gcode_line_status(self, index: int, status: str):
        if not hasattr(self, "gcode_row_status_labels"):
            return
        if index < 0 or index >= len(self.gcode_row_status_labels):
            return

        status_lbl = self.gcode_row_status_labels[index]
        code_lbl = self.gcode_row_code_labels[index]

        bg = "#1e1e1e"
        fg = "#dcdcdc"

        if status == "OK":
            bg = "#1f3a1f"
            fg = "#d8ffd8"
        elif status == "RUN":
            bg = "#1f2f4a"
            fg = "#e6f0ff"
        elif status == "ERR":
            bg = "#4a1f1f"
            fg = "#ffdede"
        elif status == "TIMEOUT":
            bg = "#4a331f"
            fg = "#ffe7cc"
        elif status == "SKIP":
            bg = "#1e1e1e"
            fg = "#888888"

        status_lbl.config(text=status, bg=bg, fg=fg)
        code_lbl.config(bg=bg)

        if hasattr(self, "gcode_table_canvas") and self.gcode_table_canvas is not None:
            row = self.gcode_row_frames[index]
            self.gcode_table_canvas.update_idletasks()
            self.gcode_table_canvas.yview_moveto(
                max(
                    0.0,
                    row.winfo_y() / max(1, self.gcode_table_rows_frame.winfo_height())
                )
            )

    def _resume_gcode_job(self) -> None:
        should_resume = False

        with self.job_lock:
            if self.job_running and self.job_paused:
                self.job_paused = False
                should_resume = True
            elif not self.job_paused:
                self._append_console("[WARN] Job not paused")
                return
            else:
                return

        if should_resume:
            self.ctrl.send_realtime(b"~")
            self._append_console(">> [JOB RESUME] ~")

    def _stop_gcode_job(self) -> None:
        if self.is_job_running():
            self.set_job_stopping(True)
            self.set_job_paused(False)
            self.ctrl.send_realtime(b"!")
            self.ctrl.send_realtime(b"\x18")
            self._append_console(">> [JOB STOP] Hold + Reset")
                
    # =========================
    # PREVIEW
    # =========================
    def _switch_preview_mode(self) -> None:
        if self.preview_container is None:
            return

        for widget in self.preview_container.winfo_children():
            widget.pack_forget()

        if self.preview_mode.get() == "2d":
            self._draw_toolpath_preview()
            if self.preview_canvas_2d is not None:
                self.preview_canvas_2d.pack(fill="both", expand=True)
        else:
            self._draw_gcode_3d_preview()
            if self.preview_3d_canvas is not None:
                self.preview_3d_canvas.get_tk_widget().pack(fill="both", expand=True)

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

    def _set_preview_dro_xyz(self, x, y, z, dx=0.0, dy=0.0):
        if self.is_job_running():
            return

        # XYZ
        self.work_pos_x_text.set(f"{x:.2f}")
        self.work_pos_y_text.set(f"{y:.2f}")
        self.work_pos_z_text.set(f"{z:.2f}")

        # Blade (A or B)
        angle = self._compute_blade_angle(dx, dy)

        if self.preview_blade_axis == "A":
            self.work_pos_a_text.set(f"{angle:.2f}")
        elif self.preview_blade_axis == "B":
            self.work_pos_b_text.set(f"{angle:.2f}")

    def _draw_toolpath_preview(self) -> None:
        canvas = getattr(self, "preview_canvas_2d", None) or getattr(self, "preview_canvas", None)
        if canvas is None:
            return

        canvas.delete("all")

        if not self.gcode_segments:
            cw = max(canvas.winfo_width(), 600)
            ch = max(canvas.winfo_height(), 400)
            canvas.create_text(cw / 2, ch / 2, text="No G-code loaded", fill="#999999")
            if hasattr(self, "preview_segment_var"):
                self.preview_segment_var.set("Segments: 0/0")
            return

        segments = [
            ((seg.start[0], seg.start[1]), (seg.end[0], seg.end[1]), seg)
            for seg in self.gcode_segments
        ]
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

        current_idx, frac = self._get_active_segment_progress()

        for i, ((x1, y1), (x2, y2), seg) in enumerate(segments):
            motion = getattr(seg, "motion_type", "G1")
            base_color = "#6FA8FF" if motion == "G0" else "#5FD16F"

            if i < current_idx:
                canvas.create_line(
                    tx(x1), ty(y1), tx(x2), ty(y2),
                    fill=base_color, width=2
                )
            elif i == current_idx and current_idx < len(segments):
                px = x1 + (x2 - x1) * frac
                py = y1 + (y2 - y1) * frac

                canvas.create_line(
                    tx(x1), ty(y1), tx(px), ty(py),
                    fill="#00FF00", width=3
                )
                canvas.create_line(
                    tx(px), ty(py), tx(x2), ty(y2),
                    fill="#444444", width=1
                )

                cx, cy = tx(px), ty(py)

                blade_angle = self._get_blade_angle_from_segment(seg, frac)
                self._draw_knife_blade_2d(canvas, cx, cy, blade_angle)

                self.current_tool_pos = [px, py, float(seg.start[2] + (seg.end[2] - seg.start[2]) * frac)]
            else:
                canvas.create_line(
                    tx(x1), ty(y1), tx(x2), ty(y2),
                    fill="#444444", width=1
                )

    def _draw_gcode_3d_preview(self) -> None:
        if not self.gcode_segments:
            if self.preview_3d_ax is not None:
                self.preview_3d_ax.clear()
                self.preview_3d_ax.set_facecolor("#111111")
                self.preview_3d_figure.patch.set_facecolor("#111111")
                self.preview_3d_figure.subplots_adjust(left=0.00, right=1.00, bottom=0.00, top=1.00)
                self.preview_3d_ax.set_title("No G-code loaded", color="white")
                self.preview_3d_canvas.draw_idle()
            return

        if self.preview_3d_ax is None or self.preview_3d_canvas is None:
            return

        ax = self.preview_3d_ax
        ax.clear()
        ax.set_facecolor("#111111")
        self.preview_3d_figure.patch.set_facecolor("#111111")

        current_idx, frac = self._get_active_segment_progress()

        colors = {
            "G0": "#4EA1FF",
            "G1": "#FF5A3D",
            "G2": "#FFD54A",
            "G3": "#5FD16F",
            "Z": "#B36AE2",
        }

        tool_pos = [0.0, 0.0, 0.0]

        for i, seg in enumerate(self.gcode_segments):
            is_z_only = (
                abs(seg.start[0] - seg.end[0]) < 0.01 and
                abs(seg.start[1] - seg.end[1]) < 0.01 and
                abs(seg.start[2] - seg.end[2]) > 0.01
            )
            motion_type = "Z" if is_z_only else getattr(seg, "motion_type", "G1")
            color = colors.get(motion_type, "#FFFFFF")

            if i < current_idx:
                ax.plot(
                    [seg.start[0], seg.end[0]],
                    [seg.start[1], seg.end[1]],
                    [seg.start[2], seg.end[2]],
                    color=color,
                    linewidth=2.0,
                    alpha=0.9,
                )
                tool_pos = list(seg.end[:3])

            elif i == current_idx and current_idx < len(self.gcode_segments):
                px = seg.start[0] + (seg.end[0] - seg.start[0]) * frac
                py = seg.start[1] + (seg.end[1] - seg.start[1]) * frac
                pz = seg.start[2] + (seg.end[2] - seg.start[2]) * frac

                ax.plot(
                    [seg.start[0], px],
                    [seg.start[1], py],
                    [seg.start[2], pz],
                    color="#00FF00",
                    linewidth=3.0,
                    alpha=1.0,
                )
                ax.plot(
                    [px, seg.end[0]],
                    [py, seg.end[1]],
                    [pz, seg.end[2]],
                    color="#444444",
                    linewidth=1.0,
                    alpha=0.7,
                )

                blade_angle = self._get_blade_angle_from_segment(seg, frac)
                blade_len = max(
                    2.0,
                    0.03 * max(
                        abs(seg.end[0] - seg.start[0]) + 1.0,
                        abs(seg.end[1] - seg.start[1]) + 1.0
                    )
                )
                dx = math.cos(blade_angle) * blade_len
                dy = math.sin(blade_angle) * blade_len

                ax.plot(
                    [px - dx, px + dx],
                    [py - dy, py + dy],
                    [pz, pz],
                    color="#FF4D4D",
                    linewidth=3.0,
                    alpha=1.0,
                )

                tool_pos = [px, py, pz]
            else:
                ax.plot(
                    [seg.start[0], seg.end[0]],
                    [seg.start[1], seg.end[1]],
                    [seg.start[2], seg.end[2]],
                    color="#333333",
                    linewidth=1.0,
                    alpha=0.5,
                )

        ax.scatter([tool_pos[0]], [tool_pos[1]], [tool_pos[2]], color="#00FF00", s=80, edgecolors="white", linewidths=1)

        try:
            import numpy as np
            pts = []
            for seg in self.gcode_segments:
                pts.append(seg.start[:3])
                pts.append(seg.end[:3])
            pts = np.array(pts)

            xmin, ymin, zmin = pts.min(axis=0)
            xmax, ymax, zmax = pts.max(axis=0)

            xspan = max(xmax - xmin, 1.0)
            yspan = max(ymax - ymin, 1.0)
            zspan = max(zmax - zmin, 1.0)

            margin = 0.02
            # --- center + normalize scale ---
            cx = (xmin + xmax) / 2
            cy = (ymin + ymax) / 2
            cz = (zmin + zmax) / 2

            max_span = max(xspan, yspan, zspan)

            ax.set_xlim(cx - max_span/2, cx + max_span/2)
            ax.set_ylim(cy - max_span/2, cy + max_span/2)
            ax.set_zlim(cz - max_span/2, cz + max_span/2)

            # flatten Z slightly (looks WAY better for CNC paths)
            ax.set_box_aspect([1, 1, 0.6])

            # remove all margins
            ax.margins(0)

            # zoom in hard
            try:
                ax.dist = 5
            except Exception:
                pass
        except Exception:
            pass

        ax.view_init(elev=20, azim=-65)
        ax.grid(False)

        try:
            ax.xaxis.pane.fill = False
            ax.yaxis.pane.fill = False
            ax.zaxis.pane.fill = False
        except Exception:
            pass
        self.preview_3d_canvas.draw_idle()

    def _update_preview_from_machine_pos(self) -> None:
        if not self.gcode_segments:
            return
        if not hasattr(self, "preview_live_follow_var"):
            return
        if not self.preview_live_follow_var.get():
            return

        try:
            mx = float(self.machine_pos_x_text.get())
            my = float(self.machine_pos_y_text.get())
            mz = float(self.machine_pos_z_text.get())
        except Exception:
            return

        best_idx = 0
        best_frac = 0.0
        best_dist2 = float("inf")

        for i, seg in enumerate(self.gcode_segments):
            x1, y1, z1 = float(seg.start[0]), float(seg.start[1]), float(seg.start[2])
            x2, y2, z2 = float(seg.end[0]), float(seg.end[1]), float(seg.end[2])

            dx = x2 - x1
            dy = y2 - y1
            dz = z2 - z1
            seg_len2 = dx*dx + dy*dy + dz*dz

            if seg_len2 <= 1e-12:
                frac = 0.0
                px, py, pz = x1, y1, z1
            else:
                frac = ((mx - x1)*dx + (my - y1)*dy + (mz - z1)*dz) / seg_len2
                frac = max(0.0, min(1.0, frac))
                px = x1 + frac * dx
                py = y1 + frac * dy
                pz = z1 + frac * dz

            dist2 = (mx - px)**2 + (my - py)**2 + (mz - pz)**2

            if dist2 < best_dist2:
                best_dist2 = dist2
                best_idx = i
                best_frac = frac

        self.current_line_index = best_idx

        seg = self.gcode_segments[best_idx]
        seg_start = float(getattr(seg, "start_time_s", 0.0))
        seg_dur = float(getattr(seg, "duration_s", 0.0))
        self.preview_elapsed_s = seg_start + best_frac * seg_dur

        if self.preview_total_time_s > 0:
            self.preview_scrub_index = self.preview_elapsed_s / self.preview_total_time_s
        else:
            self.preview_scrub_index = best_idx / max(len(self.gcode_segments), 1)

        if hasattr(self, "preview_scrubber_var"):
            self.preview_scrubber_var.set(self.preview_scrub_index * 100.0)

        self.preview_time_var.set(
            f"Time: {self._format_mmss(self.preview_elapsed_s)}/{self._format_mmss(self.preview_total_time_s)}"
        )
        self.preview_segment_var.set(
            f"Segments: {best_idx + 1}/{len(self.gcode_segments)}"
        )

        self._refresh_preview_unified()


    def _format_mmss(self, seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _get_active_segment_progress(self):
        if not self.gcode_segments:
            return 0, 0.0

        t = self.preview_elapsed_s

        for i, seg in enumerate(self.gcode_segments):
            seg_start = getattr(seg, "start_time_s", 0.0)
            seg_end = getattr(seg, "end_time_s", 0.0)
            seg_dur = max(getattr(seg, "duration_s", 0.0), 1e-9)
            is_dwell = getattr(seg, "is_dwell", False)

            if is_dwell:
                if t <= seg_end:
                    return i, 1.0
                continue

            if t <= seg_end:
                frac = (t - seg_start) / seg_dur if seg_dur > 0 else 1.0
                frac = max(0.0, min(frac, 1.0))
                return i, frac

        return len(self.gcode_segments), 1.0

    def _get_blade_angle_from_segment(self, seg, frac: float = 1.0) -> float:
        axis_index = 4  # B axis = blade

        try:
            start_rot = float(seg.start[axis_index])
            end_rot = float(seg.end[axis_index])

            angle_deg = start_rot + (end_rot - start_rot) * frac
            angle_deg += getattr(self, "preview_blade_offset_deg", 0.0)

            angle_rad = math.radians(angle_deg)
            self._last_knife_angle = angle_rad
            return angle_rad

        except Exception:
            return self._last_knife_angle

    def _draw_knife_blade_2d(self, canvas, x, y, angle_rad, blade_len=18, handle_len=8):
        tip_x = x + math.cos(angle_rad) * blade_len
        tip_y = y - math.sin(angle_rad) * blade_len

        tail_x = x - math.cos(angle_rad) * handle_len
        tail_y = y + math.sin(angle_rad) * handle_len

        canvas.create_line(
            tail_x, tail_y, tip_x, tip_y,
            fill="#FF4D4D",
            width=3
        )

        r = 3
        canvas.create_oval(
            x - r, y - r, x + r, y + r,
            fill="#FFD54A", outline=""
        )

    def _refresh_preview_unified(self) -> None:
        if self.preview_mode.get() == "2d":
            self._draw_toolpath_preview()
        else:
            self._draw_gcode_3d_preview()

    def _preview_play(self) -> None:
        if not self.gcode_segments:
            messagebox.showwarning("Preview", "Load a G-code file first")
            return

        self.preview_is_playing = True
        self.preview_last_tick_s = time.perf_counter()

        if self.preview_play_btn is not None:
            self.preview_play_btn.config(state="disabled")
        if self.preview_pause_btn is not None:
            self.preview_pause_btn.config(state="normal")

        self._animate_preview_playback()

    def _preview_pause(self) -> None:
        self.preview_is_playing = False
        self.preview_last_tick_s = None

        if self.preview_play_btn is not None:
            self.preview_play_btn.config(state="normal")
        if self.preview_pause_btn is not None:
            self.preview_pause_btn.config(state="disabled")

        if self.preview_animation_id is not None:
            self.after_cancel(self.preview_animation_id)
            self.preview_animation_id = None

    def _preview_stop(self) -> None:
        self.preview_is_playing = False
        self.preview_elapsed_s = 0.0
        self.preview_last_tick_s = None
        self.preview_scrub_index = 0.0
        self.preview_scrubber_var.set(0.0)

        if self.preview_play_btn is not None:
            self.preview_play_btn.config(state="normal")
        if self.preview_pause_btn is not None:
            self.preview_pause_btn.config(state="disabled")

        if self.preview_animation_id is not None:
            self.after_cancel(self.preview_animation_id)
            self.preview_animation_id = None

        self._preview_scrubber_moved("0")
        self.current_tool_pos = [0.0, 0.0, 0.0]
        self._set_preview_dro_xyz(0.0, 0.0, 0.0)

    def _compute_blade_angle(self, dx, dy):
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return self._last_knife_angle

        angle = math.degrees(math.atan2(dy, dx))
        angle += self.preview_blade_offset_deg

        self._last_knife_angle = angle
        return angle

    def _preview_step_frame(self) -> None:
        if not self.gcode_segments:
            return

        current_idx = self.current_line_index
        next_idx = min(current_idx + 1, len(self.gcode_segments))

        if next_idx <= 0:
            self.preview_elapsed_s = 0.0
        elif next_idx >= len(self.gcode_segments):
            self.preview_elapsed_s = self.preview_total_time_s
        else:
            self.preview_elapsed_s = float(getattr(self.gcode_segments[next_idx], "start_time_s", 0.0))

        if self.preview_total_time_s > 0:
            self.preview_scrub_index = self.preview_elapsed_s / self.preview_total_time_s
        else:
            self.preview_scrub_index = next_idx / max(len(self.gcode_segments), 1)

        self.preview_scrubber_var.set(self.preview_scrub_index * 100.0)
        self._preview_scrubber_moved(str(self.preview_scrub_index * 100.0))

    def _update_preview_speed(self) -> None:
        speed_str = self.preview_speed_var.get().replace("x", "")
        try:
            self.preview_playback_speed = float(speed_str)
        except Exception:
            self.preview_playback_speed = 1.0

    def _animate_preview_playback(self) -> None:
        if not self.preview_is_playing or not self.gcode_segments:
            return

        now = time.perf_counter()
        if self.preview_last_tick_s is None:
            self.preview_last_tick_s = now

        dt = now - self.preview_last_tick_s
        self.preview_last_tick_s = now

        seg_idx = min(self.current_line_index, len(self.gcode_segments) - 1)
        seg = self.gcode_segments[seg_idx]

        feed_scale = getattr(seg, "feed_rate", 1000.0) / 1000.0
        feed_scale = max(feed_scale, 0.001)

        self.preview_elapsed_s += dt * self.preview_playback_speed * feed_scale

        if self.preview_total_time_s <= 0:
            self.preview_elapsed_s = 0.0
            self.preview_scrub_index = 1.0
            self.preview_is_playing = False
        else:
            if self.preview_elapsed_s >= self.preview_total_time_s:
                self.preview_elapsed_s = self.preview_total_time_s
                self.preview_is_playing = False

            self.preview_scrub_index = self.preview_elapsed_s / self.preview_total_time_s

        self.preview_scrubber_var.set(self.preview_scrub_index * 100.0)
        self._preview_scrubber_moved(str(self.preview_scrub_index * 100.0))

        if not self.preview_is_playing:
            if self.preview_play_btn is not None:
                self.preview_play_btn.config(state="normal")
            if self.preview_pause_btn is not None:
                self.preview_pause_btn.config(state="disabled")
            self.preview_animation_id = None
            return

        self.preview_animation_id = self.after(16, self._animate_preview_playback)

    def _preview_scrubber_moved(self, val) -> None:
        try:
            scrub_val = float(val)
            self.preview_scrub_index = max(0.0, min(scrub_val / 100.0, 1.0))
        except Exception:
            return

        if not self.gcode_segments:
            self.current_line_index = 0
            self.preview_segment_var.set("Segments: 0/0")
            self.preview_time_var.set("Time: --:--")
            self._refresh_preview_unified()
            return

        self.preview_elapsed_s = self.preview_scrub_index * max(self.preview_total_time_s, 0.0)

        idx = len(self.gcode_segments)
        for i, seg in enumerate(self.gcode_segments):
            seg_end = float(getattr(seg, "end_time_s", 0.0))
            if self.preview_elapsed_s <= seg_end:
                idx = i
                break

        self.current_line_index = min(idx, len(self.gcode_segments))
        seg_idx = min(self.current_line_index, len(self.gcode_segments) - 1)
        if seg_idx >= 0:
            seg = self.gcode_segments[seg_idx]

            ex, ey, ez = seg.end[0], seg.end[1], seg.end[2]

            # compute direction
            dx = ex - seg.start[0]
            dy = ey - seg.start[1]

            self.current_tool_pos = [ex, ey, ez]

            self._set_preview_dro_xyz(ex, ey, ez, dx, dy)

        self.preview_time_var.set(
            f"Time: {self._format_mmss(self.preview_elapsed_s)}/{self._format_mmss(self.preview_total_time_s)}"
        )
        self.preview_segment_var.set(
            f"Segments: {min(self.current_line_index, len(self.gcode_segments))}/{len(self.gcode_segments)}"
        )

        self._refresh_preview_unified()

    # =========================
    # VISION / DXF
    # =========================
    def _ensure_vision_runner(self):
        if getattr(self, "vision_runner", None) is None:
            try:
                from .components.vision_dxf_logic import VisionRunner
            except Exception as exc:
                raise RuntimeError(
                    "Could not import apps.Vision.runner.VisionRunner"
                ) from exc

            self.vision_runner = VisionRunner()

        return self.vision_runner

    def _start_live_camera(self) -> None:
        try:
            runner = self._ensure_vision_runner()
            runner.start_camera()

            self.camera_running = True

            if hasattr(self, "camera_info_var"):
                self.camera_info_var.set("Camera running")
            if hasattr(self, "vision_dxf_status_var"):
                self.vision_dxf_status_var.set("Camera running")
            if hasattr(self, "vision_status_var"):
                self.vision_status_var.set("Camera running")
            if hasattr(self, "vision_process_var"):
                self.vision_process_var.set("Camera stream active")

            self._append_console("> Vision camera started")
            self.after(50, self._poll_vision_outputs)

        except Exception as exc:
            self.camera_running = False

            if hasattr(self, "camera_info_var"):
                self.camera_info_var.set("Camera error")
            if hasattr(self, "vision_dxf_status_var"):
                self.vision_dxf_status_var.set("Camera error")
            if hasattr(self, "vision_status_var"):
                self.vision_status_var.set(f"Camera error: {exc}")
            if hasattr(self, "vision_process_var"):
                self.vision_process_var.set(str(exc))

            self._append_console(f"[VISION CAMERA ERROR] {exc}")

    def _stop_live_camera(self) -> None:
        try:
            if getattr(self, "vision_runner", None) is not None:
                self.vision_runner.stop_camera()
        except Exception as exc:
            self._append_console(f"[VISION CAMERA STOP ERROR] {exc}")

        self.camera_running = False

        if hasattr(self, "camera_info_var"):
            self.camera_info_var.set("Camera stopped")
        if hasattr(self, "vision_dxf_status_var"):
            self.vision_dxf_status_var.set("Idle")
        if hasattr(self, "vision_status_var"):
            self.vision_status_var.set("Camera stopped")
        if hasattr(self, "vision_process_var"):
            self.vision_process_var.set("Camera stopped")

        self._append_console("> Vision camera stopped")

    def _start_vision_scan(self) -> None:
        try:
            runner = self._ensure_vision_runner()

            dxf_path = None
            if getattr(self, "dxf_file_path", None):
                dxf_path = str(self.dxf_file_path)

            runner.start_scan(dxf_path=dxf_path)
            self.vision_scan_running = True

            if hasattr(self, "vision_dxf_status_var"):
                self.vision_dxf_status_var.set("Processing...")
            if hasattr(self, "vision_status_var"):
                self.vision_status_var.set("Processing...")
            if hasattr(self, "vision_process_var"):
                self.vision_process_var.set("Scan started")
            if hasattr(self, "vision_result_var"):
                self.vision_result_var.set("Vision scan running")

            self._append_console("> Vision scan started")
            self.after(50, self._poll_vision_outputs)

        except Exception as exc:
            self.vision_scan_running = False

            if hasattr(self, "vision_dxf_status_var"):
                self.vision_dxf_status_var.set("Scan error")
            if hasattr(self, "vision_status_var"):
                self.vision_status_var.set(f"Scan error: {exc}")
            if hasattr(self, "vision_process_var"):
                self.vision_process_var.set(str(exc))
            if hasattr(self, "vision_result_var"):
                self.vision_result_var.set(str(exc))

            self._append_console(f"[VISION SCAN ERROR] {exc}")

    def _stop_vision_scan(self) -> None:
        try:
            if getattr(self, "vision_runner", None) is not None:
                self.vision_runner.stop_scan()
        except Exception as exc:
            self._append_console(f"[VISION STOP ERROR] {exc}")

        self.vision_scan_running = False

        if hasattr(self, "vision_dxf_status_var"):
            self.vision_dxf_status_var.set("Idle")
        if hasattr(self, "vision_status_var"):
            self.vision_status_var.set("Scan stopped")
        if hasattr(self, "vision_process_var"):
            self.vision_process_var.set("Scan stopped")
        if hasattr(self, "vision_result_var"):
            self.vision_result_var.set("Vision scan stopped")

        self._append_console("> Vision scan stopped")

    def _run_dxf_vision_pipeline(self) -> None:
        # backward-compatible alias for any existing button bindings
        self._start_vision_scan()

    def _poll_vision_outputs(self) -> None:
        runner = getattr(self, "vision_runner", None)
        if runner is None:
            return

        try:
            status = runner.get_status() or {}

            phase = status.get("phase", "Idle")
            detail = status.get("detail", "")
            generated_dxf_path = status.get("generated_dxf_path")
            stitched_image = runner.get_latest_stitched_image()

            if hasattr(self, "vision_dxf_status_var"):
                self.vision_dxf_status_var.set(phase)
            if hasattr(self, "vision_status_var"):
                self.vision_status_var.set(phase)
            if hasattr(self, "vision_process_var"):
                self.vision_process_var.set(detail or phase)

            if generated_dxf_path:
                if hasattr(self, "generated_dxf_var"):
                    self.generated_dxf_var.set(f"Generated DXF: {generated_dxf_path}")
                if hasattr(self, "vision_result_var"):
                    self.vision_result_var.set(f"DXF generated: {generated_dxf_path}")

            if stitched_image is not None:
                self._stitched_image = stitched_image
                if hasattr(self, "stitched_info_var"):
                    self.stitched_info_var.set("Stitched image ready")
                self._update_stitched_canvas()

            scan_active = bool(status.get("scan_running", False))
            self.vision_scan_running = scan_active

        except Exception as exc:
            self._append_console(f"[VISION POLL ERROR] {exc}")
            if hasattr(self, "vision_status_var"):
                self.vision_status_var.set(f"Poll error: {exc}")

        if self.vision_scan_running:
            self.after(100, self._poll_vision_outputs)

    def _update_camera_canvas(self):
        if getattr(self, "_camera_frame", None) is None:
            return
        if not hasattr(self, "camera_preview_canvas") or self.camera_preview_canvas is None:
            return

        try:
            import cv2
            from PIL import Image, ImageTk

            frame = self._camera_frame
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)

            w = self.camera_preview_canvas.winfo_width()
            h = self.camera_preview_canvas.winfo_height()

            if w > 0 and h > 0:
                img = img.resize((w, h))

            tk_img = ImageTk.PhotoImage(img)

            self.camera_preview_canvas.delete("all")
            self.camera_preview_canvas.create_image(0, 0, anchor="nw", image=tk_img)
            self.camera_preview_canvas.image = tk_img

        except Exception as exc:
            self._append_console(f"[CAMERA CANVAS ERROR] {exc}")

    def _update_stitched_canvas(self):
        if getattr(self, "_stitched_image", None) is None:
            return
        if not hasattr(self, "stitched_preview_canvas") or self.stitched_preview_canvas is None:
            return

        try:
            import cv2
            import numpy as np
            from PIL import Image, ImageTk

            img = self._stitched_image

            if isinstance(img, np.ndarray):
                if len(img.shape) == 2:
                    pil = Image.fromarray(img)
                else:
                    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    pil = Image.fromarray(rgb)
            else:
                pil = img

            w = self.stitched_preview_canvas.winfo_width()
            h = self.stitched_preview_canvas.winfo_height()

            if w > 0 and h > 0:
                pil = pil.resize((w, h))

            tk_img = ImageTk.PhotoImage(pil)

            self.stitched_preview_canvas.delete("all")
            self.stitched_preview_canvas.create_image(0, 0, anchor="nw", image=tk_img)
            self.stitched_preview_canvas.image = tk_img

        except Exception as exc:
            self._append_console(f"[STITCHED CANVAS ERROR] {exc}")

    def _load_dxf_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            self.dxf_file_path = Path(path)
            self.dxf_dieline = DXFDieline(self.dxf_file_path)

            info = self.dxf_dieline.get_info()
            entity_count = info.get("entity_count", 0)
            bounds = info.get("bounds")

            self.dxf_canvas_zoom = 1.0
            self.dxf_canvas_pan_x = 0.0
            self.dxf_canvas_pan_y = 0.0

            if bounds:
                w = info.get("bounds_width")
                h = info.get("bounds_height")
                self.dxf_info_text.set(
                    f"{self.dxf_file_path.name} | {entity_count} entities | "
                    f"{w:.1f} × {h:.1f}"
                )
            else:
                self.dxf_info_text.set(f"{self.dxf_file_path.name} | {entity_count} entities")

            self._append_console(f"> Loaded DXF: {path}")
            self._dxf_fit_view()

        except Exception as e:
            messagebox.showerror("DXF Error", str(e))

    def _reset_dxf_view(self) -> None:
        if self.dxf_dieline is None:
            return

        try:
            self.dxf_dieline.reset_transform()
        except Exception:
            pass

        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0.0
        self.dxf_canvas_pan_y = 0.0
        self._draw_dxf_preview()

    def _rotate_dxf(self, delta_deg: float) -> None:
        if self.dxf_dieline is None:
            return

        try:
            self.dxf_dieline.rotate(delta_deg)
            self._draw_dxf_preview()
        except Exception as exc:
            self._append_console(f"[DXF ROTATE ERROR] {exc}")

    def _zoom_dxf(self, factor: float) -> None:
        if self.dxf_dieline is None:
            return

        try:
            self.dxf_canvas_zoom *= factor
            self.dxf_canvas_zoom = max(0.05, min(self.dxf_canvas_zoom, 100.0))
            self._draw_dxf_preview()
        except Exception as exc:
            self._append_console(f"[DXF ZOOM ERROR] {exc}")

    def _on_dxf_mousewheel(self, event) -> None:
        if self.dxf_dieline is None:
            return

        try:
            if hasattr(event, "delta") and event.delta:
                factor = 1.1 if event.delta > 0 else 0.9
            else:
                factor = 1.1 if getattr(event, "num", None) == 4 else 0.9
            self._zoom_dxf(factor)
        except Exception:
            pass

    def _dxf_fit_view(self) -> None:
        if self.dxf_dieline is None:
            return

        self.dxf_canvas_zoom = 1.0
        self.dxf_canvas_pan_x = 0.0
        self.dxf_canvas_pan_y = 0.0
        self._draw_dxf_preview()

    def _draw_dxf_preview(self) -> None:
        if self.dxf_dieline is None:
            return
        if not hasattr(self, "dxf_preview_canvas") or self.dxf_preview_canvas is None:
            return

        canvas = self.dxf_preview_canvas
        canvas.delete("all")

        try:
            geom = self.dxf_dieline.get_combined_geometry()
            if geom is None or geom.is_empty:
                canvas.create_text(
                    max(canvas.winfo_width(), 300) / 2,
                    max(canvas.winfo_height(), 200) / 2,
                    text="No DXF geometry to display",
                    fill="#999999",
                )
                return

            bounds = geom.bounds
            minx, miny, maxx, maxy = bounds
            geom_w = max(maxx - minx, 1e-6)
            geom_h = max(maxy - miny, 1e-6)

            cw = max(canvas.winfo_width(), 10)
            ch = max(canvas.winfo_height(), 10)

            if cw <= 10 or ch <= 10:
                self.after(50, self._draw_dxf_preview)
                return

            padding = 20.0
            fit_scale = min((cw - 2 * padding) / geom_w, (ch - 2 * padding) / geom_h)
            fit_scale = max(fit_scale, 1e-6)
            scale = fit_scale * self.dxf_canvas_zoom

            cx_geom = (minx + maxx) / 2.0
            cy_geom = (miny + maxy) / 2.0
            cx_canvas = cw / 2.0 + self.dxf_canvas_pan_x
            cy_canvas = ch / 2.0 + self.dxf_canvas_pan_y

            def map_point(x, y):
                px = cx_canvas + (x - cx_geom) * scale
                py = cy_canvas - (y - cy_geom) * scale
                return px, py

            def draw_geometry(g):
                gtype = getattr(g, "geom_type", "")

                if gtype == "LineString":
                    coords = list(g.coords)
                    if len(coords) >= 2:
                        pts = []
                        for x, y in coords:
                            px, py = map_point(x, y)
                            pts.extend([px, py])
                        canvas.create_line(*pts, fill="#FFD54A", width=2)

                elif gtype == "Polygon":
                    ext = list(g.exterior.coords)
                    if len(ext) >= 2:
                        pts = []
                        for x, y in ext:
                            px, py = map_point(x, y)
                            pts.extend([px, py])
                        canvas.create_line(*pts, fill="#FFD54A", width=2)

                    for interior in g.interiors:
                        pts = []
                        for x, y in interior.coords:
                            px, py = map_point(x, y)
                            pts.extend([px, py])
                        if len(pts) >= 4:
                            canvas.create_line(*pts, fill="#888888", width=1)

                elif hasattr(g, "geoms"):
                    for sub in g.geoms:
                        draw_geometry(sub)

            draw_geometry(geom)

            canvas.create_text(
                10,
                10,
                anchor="nw",
                text=f"Zoom: {self.dxf_canvas_zoom:.2f}x",
                fill="#BBBBBB",
                font=("Arial", 8, "bold"),
            )

        except Exception as exc:
            canvas.create_text(
                max(canvas.winfo_width(), 300) / 2,
                max(canvas.winfo_height(), 200) / 2,
                text=f"DXF preview error:\n{exc}",
                fill="#FF8888",
                justify="center",
            )

    def _on_dxf_pan_start(self, event):
        self._dxf_pan_last_x = event.x
        self._dxf_pan_last_y = event.y

    def _on_dxf_pan_move(self, event):
        if self.dxf_preview_canvas is None:
            return

        last_x = getattr(self, "_dxf_pan_last_x", None)
        last_y = getattr(self, "_dxf_pan_last_y", None)
        if last_x is None or last_y is None:
            self._dxf_pan_last_x = event.x
            self._dxf_pan_last_y = event.y
            return

        dx = event.x - last_x
        dy = event.y - last_y

        self.dxf_canvas_pan_x += dx
        self.dxf_canvas_pan_y += dy

        self._dxf_pan_last_x = event.x
        self._dxf_pan_last_y = event.y

        self._draw_dxf_preview()

    def _on_dxf_pan_end(self, event=None):
        self._dxf_pan_last_x = None
        self._dxf_pan_last_y = None

    # =========================
    # MESH
    # =========================
    def _load_scan_mesh(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Mesh",
            filetypes=[("Mesh files", "*.stl *.obj *.ply"), ("All files", "*.*")],
        )
        if not path:
            return
        self.scan_mesh_path = path
        self.mesh_info_text.set(f"Loaded mesh: {os.path.basename(path)}")
        self._draw_mesh_preview()

    def _clear_scan_mesh(self) -> None:
        self.scan_mesh_path = None
        self.mesh_info_text.set("No mesh loaded")
        self._draw_mesh_preview()

    def _set_mesh_view(self, view_name) -> None:
        if self.mesh_ax is None:
            return
        mapping = {
            "iso": (20, 35),
            "front": (0, -90),
            "side": (0, 0),
        }
        elev, azim = mapping.get(view_name, (20, 35))
        self.mesh_elev = elev
        self.mesh_azim = azim
        self.mesh_ax.view_init(elev=elev, azim=azim)
        if self.mesh_canvas is not None:
            self.mesh_canvas.draw_idle()

    def _reset_mesh_view(self) -> None:
        self._set_mesh_view("iso")

    def _draw_mesh_preview(self) -> None:
        if self.mesh_ax is None or self.mesh_canvas is None:
            return
        self.mesh_ax.clear()
        self.mesh_ax.set_facecolor("#111111")
        self.mesh_figure.patch.set_facecolor("#111111")
        self.mesh_ax.set_title("Mesh Preview")
        if self.scan_mesh_path:
            self.mesh_ax.text2D(
                0.05,
                0.95,
                os.path.basename(self.scan_mesh_path),
                transform=self.mesh_ax.transAxes,
                color="white",
            )
        self.mesh_canvas.draw_idle()

    # =========================
    # SLATS
    # =========================
    def _use_loaded_mesh_for_slats(self) -> None:
        if self.photogrammetry_raw_mesh is None or not self.photogrammetry_mesh_path:
            self.slat_info_text.set("No photogrammetry mesh loaded")
            self._append_console("[SLATS] No photogrammetry mesh loaded")
            return

        self.raw_mesh = self.photogrammetry_raw_mesh
        self.scan_mesh_path = self.photogrammetry_mesh_path

        mesh_name = os.path.basename(self.scan_mesh_path)
        self.mesh_info_text.set(f"Using mesh for slats: {mesh_name}")
        self.slat_info_text.set("Mesh linked. Ready to generate slats.")
        self._append_console(f"> Linked photogrammetry mesh to Slats tab: {mesh_name}")

        try:
            self._draw_slats_preview()
        except Exception:
            pass


    def _generate_slats(self) -> None:
        if not self.scan_mesh_path:
            self.slat_info_text.set("No mesh selected")
            self._append_console("[SLATS] No mesh selected")
            return

        try:
            n_xy = int(float(self.n_xy_var.get()))
            n_xz = int(float(self.n_xz_var.get()))
        except Exception:
            self.slat_info_text.set("Invalid slat counts")
            self._append_console("[SLATS] Invalid N_xy / N_xz values")
            return

        if n_xy <= 0 or n_xz <= 0:
            self.slat_info_text.set("Slat counts must be > 0")
            self._append_console("[SLATS] Slat counts must be > 0")
            return

        try:
            from apps.Filler.grid_slats import compute_worldgrid_from_stl

            self.slats_data = compute_worldgrid_from_stl(
                self.scan_mesh_path,
                n_xy=n_xy,
                n_xz=n_xz,
            )

            xy_r = len(self.slats_data.get("worldXY_right", []))
            xy_l = len(self.slats_data.get("worldXY_left", []))
            xz_r = len(self.slats_data.get("worldXZ_right", []))
            xz_l = len(self.slats_data.get("worldXZ_left", []))

            self.slat_info_text.set(
                f"Generated slats | XY R:{xy_r} L:{xy_l} | XZ R:{xz_r} L:{xz_l}"
            )
            self._append_console(
                f"> Generated slats | XY R:{xy_r} L:{xy_l} | XZ R:{xz_r} L:{xz_l}"
            )

            self._draw_slats_preview()

        except Exception as exc:
            self.slats_data = None
            self.slat_info_text.set(f"Slat generation failed: {exc}")
            self._append_console(f"[SLATS ERROR] {exc}")


    def _clear_slats(self) -> None:
        self.slats_data = None
        self.slat_info_text.set("No slats generated")
        self._append_console("> Cleared slats")

        try:
            self._draw_slats_preview()
        except Exception:
            pass


    def _draw_slats_preview(self) -> None:
        if self.slats_ax is None or self.slats_canvas is None or self.slats_figure is None:
            return

        ax = self.slats_ax
        fig = self.slats_figure

        ax.clear()
        ax.set_facecolor("#111111")
        fig.patch.set_facecolor("#111111")
        fig.subplots_adjust(left=0.00, right=1.00, bottom=0.00, top=1.00)

        all_pts = []

        # --- optional mesh overlay
        if self.show_mesh_overlay_var.get() and self.raw_mesh is not None:
            try:
                import numpy as np

                mesh_points = np.asarray(self.raw_mesh.vertices, dtype=float)
                if len(mesh_points) > 4000:
                    idx = np.random.choice(len(mesh_points), 4000, replace=False)
                    preview_points = mesh_points[idx]
                else:
                    preview_points = mesh_points

                ax.scatter(
                    preview_points[:, 0],
                    preview_points[:, 1],
                    preview_points[:, 2],
                    s=1,
                    c="#444444",
                    depthshade=False,
                )
                all_pts.append(mesh_points)
            except Exception as exc:
                self._append_console(f"[SLATS PREVIEW] Mesh overlay error: {exc}")

        if self.slats_data:
            try:
                import numpy as np

                z_levels = self.slats_data.get("zLevels", [])
                y_levels = self.slats_data.get("yLevels", [])

                worldXY_right = self.slats_data.get("worldXY_right", [])
                worldXY_left = self.slats_data.get("worldXY_left", [])
                worldXZ_right = self.slats_data.get("worldXZ_right", [])
                worldXZ_left = self.slats_data.get("worldXZ_left", [])

                def explode_polys(g):
                    if g is None or g.is_empty:
                        return []
                    t = g.geom_type
                    if t == "Polygon":
                        return [g]
                    if t == "MultiPolygon":
                        return list(g.geoms)
                    if t == "GeometryCollection":
                        out = []
                        for gg in g.geoms:
                            out.extend(explode_polys(gg))
                        return out
                    return []

                # XY slats live in constant Z planes
                for z, geom in zip(z_levels, worldXY_right):
                    if geom is None or geom.is_empty:
                        continue
                    for p in explode_polys(geom):
                        xy = np.asarray(p.exterior.coords)
                        xyz = np.column_stack([
                            xy[:, 0],
                            xy[:, 1],
                            np.full(len(xy), z),
                        ])
                        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color="#FF6666", linewidth=1.5)
                        all_pts.append(xyz)

                for z, geom in zip(z_levels, worldXY_left):
                    if geom is None or geom.is_empty:
                        continue
                    for p in explode_polys(geom):
                        xy = np.asarray(p.exterior.coords)
                        xyz = np.column_stack([
                            xy[:, 0],
                            xy[:, 1],
                            np.full(len(xy), z),
                        ])
                        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color="#FF6666", linewidth=1.5)
                        all_pts.append(xyz)

                # XZ slats live in constant Y planes
                for y, geom in zip(y_levels, worldXZ_right):
                    if geom is None or geom.is_empty:
                        continue
                    for p in explode_polys(geom):
                        xz = np.asarray(p.exterior.coords)
                        xyz = np.column_stack([
                            xz[:, 0],
                            np.full(len(xz), y),
                            xz[:, 1],
                        ])
                        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color="#66AAFF", linewidth=1.5)
                        all_pts.append(xyz)

                for y, geom in zip(y_levels, worldXZ_left):
                    if geom is None or geom.is_empty:
                        continue
                    for p in explode_polys(geom):
                        xz = np.asarray(p.exterior.coords)
                        xyz = np.column_stack([
                            xz[:, 0],
                            np.full(len(xz), y),
                            xz[:, 1],
                        ])
                        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color="#66AAFF", linewidth=1.5)
                        all_pts.append(xyz)

            except Exception as exc:
                self._append_console(f"[SLATS PREVIEW] Slat draw error: {exc}")

        # --- fit view nicely
        try:
            import numpy as np

            if all_pts:
                pts = np.vstack(all_pts)
                xmin, ymin, zmin = pts.min(axis=0)
                xmax, ymax, zmax = pts.max(axis=0)

                xspan = max(xmax - xmin, 1.0)
                yspan = max(ymax - ymin, 1.0)
                zspan = max(zmax - zmin, 1.0)

                cx = (xmin + xmax) / 2.0
                cy = (ymin + ymax) / 2.0
                cz = (zmin + zmax) / 2.0
                max_span = max(xspan, yspan, zspan)

                ax.set_xlim(cx - max_span / 2.0, cx + max_span / 2.0)
                ax.set_ylim(cy - max_span / 2.0, cy + max_span / 2.0)
                ax.set_zlim(cz - max_span / 2.0, cz + max_span / 2.0)
                ax.set_box_aspect([1, 1, 0.7])
        except Exception:
            pass

        ax.view_init(elev=20, azim=35)
        ax.grid(False)

        try:
            ax.xaxis.pane.fill = False
            ax.yaxis.pane.fill = False
            ax.zaxis.pane.fill = False
            ax.set_axis_off()
        except Exception:
            pass

        self.slats_canvas.draw_idle()

    def _draw_slats_preview(self) -> None:
        if self.slats_ax is None or self.slats_canvas is None or self.slats_figure is None:
            return

        ax = self.slats_ax
        fig = self.slats_figure

        ax.clear()
        ax.set_facecolor("#111111")
        fig.patch.set_facecolor("#111111")
        fig.subplots_adjust(left=0.00, right=1.00, bottom=0.00, top=1.00)

        mesh_points = None

        if self.show_mesh_overlay_var.get() and self.raw_mesh is not None:
            try:
                import numpy as np

                mesh_points = np.asarray(self.raw_mesh.vertices, dtype=float)
                if len(mesh_points) > 4000:
                    idx = np.random.choice(len(mesh_points), 4000, replace=False)
                    preview_points = mesh_points[idx]
                else:
                    preview_points = mesh_points

                ax.scatter(
                    preview_points[:, 0],
                    preview_points[:, 1],
                    preview_points[:, 2],
                    s=1,
                    c="#444444",
                    depthshade=False,
                )
            except Exception as exc:
                self._append_console(f"[SLATS PREVIEW] Mesh overlay error: {exc}")

        if self.slats_data:
            for slat in self.slats_data:
                center = slat.get("center")
                size = slat.get("size")

                if center is None or size is None or len(center) != 3 or len(size) != 3:
                    continue

                x, y, z = center
                dx, dy, dz = size

                ax.bar3d(
                    x - dx / 2.0,
                    y - dy / 2.0,
                    z - dz / 2.0,
                    dx,
                    dy,
                    dz,
                    color="#5FD16F",
                    alpha=0.65,
                    shade=True,
                )

        try:
            import numpy as np

            pts = []

            if mesh_points is not None and len(mesh_points) > 0:
                pts.append(mesh_points)

            if self.slats_data:
                slat_pts = []
                for slat in self.slats_data:
                    cx, cy, cz = slat["center"]
                    dx, dy, dz = slat["size"]
                    slat_pts.extend([
                        [cx - dx / 2.0, cy - dy / 2.0, cz - dz / 2.0],
                        [cx + dx / 2.0, cy + dy / 2.0, cz + dz / 2.0],
                    ])
                if slat_pts:
                    pts.append(np.asarray(slat_pts, dtype=float))

            if pts:
                pts = np.vstack(pts)
                xmin, ymin, zmin = pts.min(axis=0)
                xmax, ymax, zmax = pts.max(axis=0)

                xspan = max(xmax - xmin, 1.0)
                yspan = max(ymax - ymin, 1.0)
                zspan = max(zmax - zmin, 1.0)

                cx = (xmin + xmax) / 2.0
                cy = (ymin + ymax) / 2.0
                cz = (zmin + zmax) / 2.0
                max_span = max(xspan, yspan, zspan)

                ax.set_xlim(cx - max_span / 2.0, cx + max_span / 2.0)
                ax.set_ylim(cy - max_span / 2.0, cy + max_span / 2.0)
                ax.set_zlim(cz - max_span / 2.0, cz + max_span / 2.0)
                ax.set_box_aspect([1, 1, 0.7])
        except Exception:
            pass

        ax.view_init(elev=20, azim=35)
        ax.grid(False)

        try:
            ax.xaxis.pane.fill = False
            ax.yaxis.pane.fill = False
            ax.zaxis.pane.fill = False
            ax.set_axis_off()
        except Exception:
            pass

        self.slats_canvas.draw_idle()

    # =========================
    # SLATS CAM
    # =========================
    def _browse_mesh(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Mesh",
            filetypes=[
                ("Mesh files", "*.stl *.obj"),
                ("STL files", "*.stl"),
                ("OBJ files", "*.obj"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        p = Path(path)
        self.slats_cam_mesh_path = p
        self.slats_cam_stl_path = p   # legacy alias used by slats_cam_only

        if hasattr(self, "slats_cam_stl_path_var"):
            self.slats_cam_stl_path_var.set(p.name)

        self.slats_cam_slats_info_var.set(p.name)
        self.slats_cam_status_var.set("Mesh selected")
        self._append_console(f"> Selected mesh: {path}")

    def _browse_stl(self) -> None:
        self._browse_mesh()

    def _safe_float(self, value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def _safe_int(self, value, default=0):
        try:
            return int(value)
        except Exception:
            return int(default)

    def _update_selected_count(self):
        total = len(getattr(self, "all_slat_records", []))
        selected = len(getattr(self, "selected_slat_ids", set()))
        if hasattr(self, "selected_count_var"):
            self.selected_count_var.set(f"Selected: {selected} / {total}")

    def _on_library_inner_configure(self, event=None):
        if getattr(self, "library_canvas_container", None) is not None:
            self.library_canvas_container.configure(
                scrollregion=self.library_canvas_container.bbox("all")
            )

    def _on_library_canvas_configure(self, event):
        if getattr(self, "library_canvas_container", None) is not None and getattr(self, "library_window", None) is not None:
            self.library_canvas_container.itemconfigure(self.library_window, width=event.width)

    def _on_library_mousewheel(self, event):
        try:
            if getattr(self, "library_canvas_container", None) is not None:
                self.library_canvas_container.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _generate_slats(self):
        if not getattr(self, "slats_cam_stl_path", None):
            self._append_console("> No mesh selected")
            return

        xy = self._safe_int(self.xy_count_var.get(), 5)
        xz = self._safe_int(self.xz_count_var.get(), 5)

        self.all_slat_records = generate_slats(
            self.slats_cam_stl_path,
            xy,
            xz,
        )

        self.selected_slat_ids = set()
        self.packed_items = {}
        self.active_packed_slat_id = None

        self.slats_cam_slats_info_var.set(
            f"{len(self.all_slat_records)} slats generated"
        )

        self._rebuild_library_tiles()
        self._append_console("> Slats generated")

    def _auto_pack_selected(self):
        print("AUTO PACK CLICKED")

        if not getattr(self, "selected_slat_ids", None):
            print("No slats selected")
            return

        if getattr(self, "usable_region_mm", None) is None:
            print("No sheet loaded")
            return

        selected_records = [
            r for r in self.all_slat_records
            if record_id(r) in self.selected_slat_ids
        ]

        print("Selected:", len(selected_records))

        if not selected_records:
            return

        try:
            placements = fidxf.auto_place_selected_slats(
                selected_records,
                self.usable_region_mm,
                fidxf.AUTO_CFG,
            )
        except Exception as e:
            print("PACK ERROR:", e)
            return

        record_by_sid = {record_id(r): r for r in self.all_slat_records}

        self.packed_items = {}

        for sid, geom, pose, ok, note in placements:
            if ok and geom is not None:
                x, y, rot_deg = pose
                rec = record_by_sid.get(sid)

                self.packed_items[sid] = {
                    "rec": rec,
                    "x": x,
                    "y": y,
                    "rot": rot_deg,
                    "geom": geom,
                    "note": note,
                }

        print("Packed:", len(self.packed_items))

        # redraw views if available
        if hasattr(self, "_redraw_all_views"):
            self._redraw_all_views()

    def _select_all_slats(self):
        self.selected_slat_ids = {record_id(r) for r in self.all_slat_records}
        self._refresh_library_selection_styles()

    def _clear_selection(self):
        self.selected_slat_ids.clear()
        self._refresh_library_selection_styles()

    def _select_family(self, family):
        family = str(family).upper()
        self.selected_slat_ids = {
            record_id(r)
            for r in self.all_slat_records
            if record_family(r).upper().startswith(family)
        }
        self._refresh_library_selection_styles()

    def _select_side(self, side):
        side = str(side).lower()
        self.selected_slat_ids = {
            record_id(r)
            for r in self.all_slat_records
            if record_side(r).lower() == side
        }
        self._refresh_library_selection_styles()

    def _toggle_slat_selection(self, sid):
        if sid in self.selected_slat_ids:
            self.selected_slat_ids.remove(sid)
        else:
            self.selected_slat_ids.add(sid)
        self._refresh_library_selection_styles()

    def _rebuild_library_tiles(self):
        if getattr(self, "library_inner", None) is None:
            return

        for child in self.library_inner.winfo_children():
            child.destroy()
        self.library_tile_map.clear()

        if not self.all_slat_records:
            tk.Label(
                self.library_inner,
                text="Generate slats to see them here",
                bg="#101010",
                fg="#999999",
                font=("Arial", 12),
            ).pack(padx=20, pady=20)
            self._update_selected_count()
            self._on_library_inner_configure()
            return

        cols = 2
        for col in range(cols):
            self.library_inner.grid_columnconfigure(col, weight=1)

        for i, rec in enumerate(self.all_slat_records):
            row = i // cols
            col = i % cols

            sid = record_id(rec)
            fam = record_family(rec)
            side = record_side(rec)

            tile = tk.Frame(
                self.library_inner,
                bg="#181818",
                bd=2,
                relief="solid",
                cursor="hand2",
            )
            tile.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

            header = tk.Frame(tile, bg="#181818")
            header.pack(fill="x", padx=8, pady=(8, 2))

            lbl1 = tk.Label(header, text=sid, bg="#181818", fg="#FFFFFF", font=("Arial", 9, "bold"))
            lbl1.pack(anchor="w")

            lbl2 = tk.Label(header, text=f"{fam} • {side}", bg="#181818", fg="#BBBBBB", font=("Arial", 8))
            lbl2.pack(anchor="w")

            preview = tk.Canvas(tile, width=180, height=120, bg="#181818", highlightthickness=0, cursor="hand2")
            preview.pack(fill="both", expand=True, padx=8, pady=(2, 8))

            self.after(0, lambda c=preview, r=rec: self._draw_library_preview(c, r))

            widgets = [tile, header, lbl1, lbl2, preview]
            for w in widgets:
                w.bind("<Button-1>", lambda e, sid=sid: self._toggle_slat_selection(sid))

            self.library_tile_map[sid] = {
                "tile": tile,
                "header": header,
                "labels": [lbl1, lbl2],
                "preview": preview,
                "rec": rec,
            }

        self._refresh_library_selection_styles()
        self._on_library_inner_configure()

    def _draw_library_preview(self, canvas, rec):
        canvas.delete("all")

        geom = normalize_part(record_geom(rec))
        if geom is None or geom.is_empty:
            return

        canvas.update_idletasks()
        cw = max(canvas.winfo_width(), 150)
        ch = max(canvas.winfo_height(), 95)

        pad = 10

        bx0, by0, bx1, by1 = geom.bounds
        gw = max(bx1 - bx0, 1e-9)
        gh = max(by1 - by0, 1e-9)

        s = min((cw - 2 * pad) / gw, (ch - 2 * pad) / gh) * 0.9

        ox = (cw - gw * s) / 2
        oy = (ch - gh * s) / 2

        fam = record_family(rec).upper()
        outline = "#FFAA33" if fam.startswith("XZ") else "#66CCFF"

        for poly in iter_polys(geom):
            pts = []
            for x, y in list(poly.exterior.coords):
                cx = ox + (x - bx0) * s
                cy = ch - (oy + (y - by0) * s)
                pts.extend([cx, cy])

            canvas.create_polygon(pts, outline=outline, fill="", width=1)

    def _add_selected_to_library(self) -> None:
        # Kept for backward compatibility with old simple tab.
        self._append_console("> Library is already showing all generated slats")


    def _active_window(self):
        windows = getattr(self, "feed_windows", None) or []
        if not windows:
            return None

        i = max(0, min(self.active_window_index, len(windows) - 1))
        self.active_window_index = i
        return windows[i]

    def _prev_window(self):
        if not getattr(self, "feed_windows", None):
            return
        self.active_window_index = max(0, self.active_window_index - 1)
        self._redraw_all_views()

    def _next_window(self):
        if not getattr(self, "feed_windows", None):
            return
        self.active_window_index = min(len(self.feed_windows) - 1, self.active_window_index + 1)
        self._redraw_all_views()

    def _zoom_workspace(self, factor):
        self.workspace_zoom *= factor
        self.workspace_zoom = max(0.1, min(self.workspace_zoom, 25.0))
        self._redraw_all_views()

    def _fit_workspace(self):
        self.workspace_zoom = 1.0
        self.workspace_pan_x = 0.0
        self.workspace_pan_y = 0.0
        self._redraw_all_views()

    def _rotate_active(self, delta_deg):
        sid = self.active_packed_slat_id
        if not sid or sid not in self.packed_items:
            self.slats_cam_status_var.set("Select a packed slat to rotate")
            return

        item = self.packed_items[sid]

        new_rot = item["rot"] + delta_deg
        candidate = place_geom(record_geom(item["rec"]), item["x"], item["y"], new_rot)

        allowed = candidate is not None and not candidate.is_empty

        if allowed and self.usable_region_mm is not None:
            try:
                allowed = candidate.buffer(1e-6).within(self.usable_region_mm)
            except Exception:
                allowed = False

        if not allowed:
            self.slats_cam_status_var.set("Rotation blocked: outside usable area")
            return

        gap = float(self.slats_cam_gap_mm_var.get() or "4.0")

        for other_sid, other in self.packed_items.items():
            if other_sid == sid:
                continue

            other_geom = other.get("geom")
            if other_geom is None:
                continue

            try:
                if candidate.buffer(gap).intersects(other_geom):
                    self.slats_cam_status_var.set("Rotation blocked: overlaps another slat")
                    return
            except Exception:
                pass

        item["rot"] = new_rot
        item["geom"] = candidate
        self.slats_cam_status_var.set(f"Rotated {sid} to {new_rot:.0f}°")
        self._redraw_all_views()

    def _on_workspace_click(self, event):
        # 1️⃣ try boundary first
        boundary_index = self._pick_feed_boundary(event.x, event.y)
        if boundary_index is not None:
            self.drag_boundary_index = boundary_index
            self.drag_item_id = None
            self.drag_last_xy = (event.x, event.y)
            self.drag_original_pose = None
            self._redraw_all_views()
            return

        # 2️⃣ slat selection
        sid = self._pick_packed_slat(event.x, event.y)

        self.active_packed_slat_id = sid
        self.drag_item_id = sid
        self.drag_boundary_index = None
        self.drag_last_xy = (event.x, event.y)

        if sid and sid in self.packed_items:
            item = self.packed_items[sid]
            self.drag_original_pose = (item["x"], item["y"], item["rot"], item["geom"])
        else:
            self.drag_original_pose = None

        self._redraw_all_views()

    def _on_workspace_drag(self, event):
        # 🔴 boundary drag
        if self.drag_boundary_index is not None:
            _, to_world, _ = self._overview_view_transform()
            wx, _ = to_world(event.x, event.y)

            self._move_feed_boundary(self.drag_boundary_index, wx)
            self.drag_last_xy = (event.x, event.y)
            self._redraw_all_views()
            return

        # 🔵 slat drag
        if not self.drag_item_id or self.drag_item_id not in self.packed_items:
            return

        sid = self.drag_item_id
        _, to_world, _ = self._overview_view_transform()

        wx0, wy0 = to_world(*self.drag_last_xy)
        wx1, wy1 = to_world(event.x, event.y)

        dx = wx1 - wx0
        dy = wy1 - wy0

        item = self.packed_items[sid]

        new_x = item["x"] + dx
        new_y = item["y"] + dy

        candidate = place_geom(record_geom(item["rec"]), new_x, new_y, item["rot"])

        if candidate and not candidate.is_empty:
            item["x"] = new_x
            item["y"] = new_y
            item["geom"] = candidate

        self.drag_last_xy = (event.x, event.y)
        self._redraw_all_views()

    def _on_workspace_release(self, event):
        if self.drag_item_id and self.drag_item_id in self.packed_items:
            sid = self.drag_item_id
            item = self.packed_items[sid]
            candidate = item.get("geom")

            allowed = candidate is not None and not candidate.is_empty

            # ✅ region constraint
            if allowed and self.usable_region_mm is not None:
                try:
                    allowed = candidate.buffer(1e-6).within(self.usable_region_mm)
                except Exception:
                    allowed = False

            # ✅ collision constraint
            if allowed:
                gap = float(self.slats_cam_gap_mm_var.get() or "4.0")

                for other_sid, other in self.packed_items.items():
                    if other_sid == sid:
                        continue

                    other_geom = other.get("geom")
                    if other_geom is None:
                        continue

                    try:
                        if candidate.buffer(gap).intersects(other_geom):
                            allowed = False
                            break
                    except Exception:
                        pass

            # ❌ revert if invalid
            if not allowed and self.drag_original_pose:
                ox, oy, orot, ogeom = self.drag_original_pose
                item["x"] = ox
                item["y"] = oy
                item["rot"] = orot
                item["geom"] = ogeom

        self.drag_item_id = None
        self.drag_boundary_index = None
        self.drag_last_xy = None
        self.drag_original_pose = None

        self._redraw_all_views()


    def _on_workspace_pan_start(self, event):
        self._pan_start = (event.x, event.y)

    def _on_workspace_pan_move(self, event):
        if self._pan_start is None:
            return
        x0, y0 = self._pan_start
        self.workspace_pan_x += event.x - x0
        self.workspace_pan_y += event.y - y0
        self._pan_start = (event.x, event.y)
        self._redraw_all_views()

    def _on_workspace_mousewheel(self, event):
        factor = 1.1 if event.delta > 0 else 0.9
        self._zoom_workspace(factor)

    def _world_to_workspace_canvas(self, x, y, bounds, cw, ch):
        bx0, by0, bx1, by1 = bounds
        bw = max(bx1 - bx0, 1.0)
        bh = max(by1 - by0, 1.0)
        pad = 20

        base_scale = min((cw - 2 * pad) / bw, (ch - 2 * pad) / bh)
        scale = max(base_scale * self.workspace_zoom, 0.0001)
        self._workspace_mm_per_px = 1.0 / scale

        cx = pad + (x - bx0) * scale + self.workspace_pan_x
        cy = ch - (pad + (y - by0) * scale) + self.workspace_pan_y
        return cx, cy

    def _world_to_window_canvas(self, x, y, window_bounds, cw, ch):
        bx0, by0, bx1, by1 = window_bounds
        bw = max(bx1 - bx0, 1.0)
        bh = max(by1 - by0, 1.0)
        pad = 20

        scale = min((cw - 2 * pad) / bw, (ch - 2 * pad) / bh)
        scale = max(scale * self.window_zoom, 0.0001)

        cx = pad + (x - bx0) * scale + self.window_pan_x
        cy = ch - (pad + (y - by0) * scale) + self.window_pan_y
        return cx, cy

    def _refresh_library_selection_styles(self):
        for sid, info in getattr(self, "library_tile_map", {}).items():
            selected = sid in self.selected_slat_ids
            tile_bg = "#2A4E7A" if selected else "#181818"
            text_fg = "#FFFFFF"
            sub_fg = "#D7E7FF" if selected else "#BBBBBB"

            try:
                info["tile"].configure(
                    bg=tile_bg,
                    highlightbackground="#FFD54A" if selected else "#555555",
                    highlightthickness=2 if selected else 0,
                )
            except Exception:
                pass

            try:
                info["header"].configure(bg=tile_bg)
            except Exception:
                pass

            for lbl in info.get("labels", []):
                try:
                    is_bold = "bold" in str(lbl.cget("font")).lower()
                    lbl.configure(bg=tile_bg, fg=(text_fg if is_bold else sub_fg))
                except Exception:
                    pass

            try:
                info["preview"].configure(bg=tile_bg)
                self._draw_library_preview(info["preview"], info["rec"])
            except Exception:
                pass

        self._update_selected_count()

    def _draw_geom_on_canvas(self, canvas, geom, to_canvas, outline="#00FF99", fill="", width=1, tags=()):
        if geom is None or geom.is_empty:
            return

        for poly in iter_polys(geom):
            # ---- OUTER ----
            coords = list(poly.exterior.coords)
            if len(coords) >= 2:
                pts = []
                for x, y in coords:
                    cx, cy = to_canvas(x, y)
                    pts.extend([cx, cy])

                if fill:
                    canvas.create_polygon(
                        pts,
                        outline=outline,
                        fill=fill,
                        width=width,
                        stipple="gray50",
                        tags=tags,
                    )
                else:
                    canvas.create_line(pts, fill=outline, width=width, tags=tags)

            # ---- 🔥 INTERIORS (THIS IS WHAT YOU WERE MISSING) ----
            for interior in poly.interiors:
                coords = list(interior.coords)
                if len(coords) >= 2:
                    pts = []
                    for x, y in coords:
                        cx, cy = to_canvas(x, y)
                        pts.extend([cx, cy])

                    canvas.create_line(
                        pts,
                        fill=outline,
                        width=width,
                        tags=tags,
                    )

    def _generate_gcode(self) -> None:
        count = len(self.packed_items)
        self.slats_cam_status_var.set(f"G-code generation not wired yet ({count} packed)")
        self._append_console(f"> Generate G-code requested for {count} packed slats (not yet wired)")

    def _load_dxf(self):
        path = filedialog.askopenfilename(
            title="Load Cardboard DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            self.slats_cam_dxf_path = Path(path)

            polys = fidxf.load_closed_polygons_from_dxf(self.slats_cam_dxf_path)
            min_sheet_area = float(self.slats_cam_min_sheet_area_var.get() or "50000.0")
            sheet_index = int(self.slats_cam_sheet_index_var.get() or "0")

            sheets = fidxf.classify_sheet_candidates(polys, min_sheet_area=min_sheet_area)
            if sheet_index >= len(sheets):
                raise IndexError(f"sheet_index={sheet_index} but only {len(sheets)} sheet candidates found")

            sheet_raw, holes_raw = sheets[sheet_index]

            cardboard_width_mm = float(self.slats_cam_cardboard_width_mm.get() or "280.0")
            feed_window_len = float(self.slats_cam_feed_window_mm.get() or "120.0")
            edge_margin_mm = float(self.slats_cam_edge_margin_mm.get() or "5.0")
            cut_clearance_mm = float(self.slats_cam_cut_clearance_mm.get() or "1.0")

            cardboard_scale = fidxf.compute_cardboard_mm_scale(sheet_raw, cardboard_width_mm)

            sheet_mm = fidxf.scale_geom_from_sheet_origin(sheet_raw, sheet_raw, cardboard_scale)
            holes_mm = [fidxf.scale_geom_from_sheet_origin(h, sheet_raw, cardboard_scale) for h in holes_raw]
            holes_mm = [h for h in holes_mm if h is not None and not h.is_empty]

            dx, dy = fidxf.compute_window0_centering_translation(
                sheet_mm,
                feed_window_len,
                offset_x=0.0,
                offset_y=0.0,
            )

            sheet_mm = fidxf.translate_geometry(sheet_mm, dx, dy)
            holes_mm = fidxf.translate_geometries(holes_mm, dx, dy)

            usable_region_mm = fidxf.build_usable_region(
                sheet_mm,
                holes_mm,
                edge_margin=edge_margin_mm,
                cut_clearance=cut_clearance_mm,
            )

            self.sheet_raw = sheet_raw
            self.holes_raw = holes_raw
            self.sheet_mm = sheet_mm
            self.holes_mm = holes_mm
            self.usable_region_mm = usable_region_mm
            self.gantry_width_x_var.set(f"{cardboard_width_mm:.1}")
            self.feed_window_y_var.set(f"{feed_window_len:.1f}")
            self._rebuild_feed_windows()

            self.slats_cam_status_var.set(f"DXF loaded ({len(sheets)} sheet candidates)")
            self._fit_workspace()

        except Exception as e:
            messagebox.showerror("DXF Error", str(e))
            self.slats_cam_status_var.set("DXF error")

    def _rebuild_feed_windows(self):
        self.feed_windows = []
        self.active_window_index = 0

        if self.sheet_mm is None or self.sheet_mm.is_empty:
            self._update_window_info()
            return

        feed_window_len = float(self.slats_cam_feed_window_mm.get() or "200.0")
        self.feed_windows = fidxf.build_feed_windows_along_length(
            self.sheet_mm,
            feed_window_len,
        )
        self._update_window_info()

    def _update_window_info(self):
        if not getattr(self, "feed_windows", None):
            self.window_info_var.set("Window: none")
            return

        i = self.active_window_index
        n = len(self.feed_windows)

        _, x0, x1 = self.feed_windows[i]
        width = x1 - x0

        self.window_info_var.set(
            f"Window {i+1}/{n}\n"
            f"x=[{x0:.1f}, {x1:.1f}] mm"
        )
        
    def _sheet_y_bounds(self):
        if getattr(self, "sheet_mm", None) is not None and not self.sheet_mm.is_empty:
            _, miny, _, maxy = self.sheet_mm.bounds
            return miny, maxy
        _, miny, _, maxy = self._world_bounds()
        return miny, maxy


    def _world_bounds(self):
        geoms = []

        if getattr(self, "sheet_mm", None) is not None and not self.sheet_mm.is_empty:
            geoms.append(self.sheet_mm)

        for h in getattr(self, "holes_mm", []):
            if h is not None and not h.is_empty:
                geoms.append(h)

        for item in getattr(self, "packed_items", {}).values():
            g = item.get("geom")
            if g is not None and not g.is_empty:
                geoms.append(g)

        if not geoms:
            return (0.0, 0.0, 100.0, 100.0)

        u = unary_union(geoms)
        return u.bounds


    def _window_world_bounds(self):
        window = self._active_window()
        preview = self._window_preview_geoms(window)
        geoms = []

        sheet = preview.get("sheet")
        if sheet is not None and not sheet.is_empty:
            geoms.append(sheet)

        usable = preview.get("usable")
        if usable is not None and not usable.is_empty:
            geoms.append(usable)

        for h in preview.get("holes", []):
            if h is not None and not h.is_empty:
                geoms.append(h)

        for _sid, g in preview.get("packed", []):
            if g is not None and not g.is_empty:
                geoms.append(g)

        gantry_w = float(self.gantry_width_x_var.get() or self.slats_cam_cardboard_width_mm.get() or "280.0")
        gantry_h = float(self.feed_window_y_var.get() or self.slats_cam_feed_window_mm.get() or "120.0")
        geoms.append(box(-gantry_w / 2.0, -gantry_h / 2.0, gantry_w / 2.0, gantry_h / 2.0))

        u = unary_union(geoms)
        return u.bounds


    def _fit_workspace(self):
        self.workspace_zoom = 1.0
        self.workspace_pan_x = 0.0
        self.workspace_pan_y = 0.0
        self.window_zoom = 1.0
        self.window_pan_x = 0.0
        self.window_pan_y = 0.0
        self._redraw_all_views()


    def _zoom_workspace(self, factor):
        self.workspace_zoom *= factor
        self.workspace_zoom = max(0.1, min(50.0, self.workspace_zoom))
        self._redraw_all_views()


    def _overview_view_transform(self):
        c = self.workspace_canvas
        c.update_idletasks()
        cw = max(c.winfo_width(), 400)
        ch = max(c.winfo_height(), 300)

        minx, miny, maxx, maxy = self._world_bounds()
        ww = max(maxx - minx, 1.0)
        wh = max(maxy - miny, 1.0)

        margin = 30
        base = min((cw - 2 * margin) / ww, (ch - 2 * margin) / wh)
        s = base * self.workspace_zoom

        tx = (cw - ww * s) / 2 - minx * s + self.workspace_pan_x
        ty = (ch - wh * s) / 2 + maxy * s + self.workspace_pan_y

        def to_canvas(x, y):
            return (tx + x * s, ty - y * s)

        def to_world(cx, cy):
            return ((cx - tx) / s, (ty - cy) / s)

        return to_canvas, to_world, s


    def _window_view_transform(self):
        c = self.window_canvas
        c.update_idletasks()
        cw = max(c.winfo_width(), 400)
        ch = max(c.winfo_height(), 250)

        minx, miny, maxx, maxy = self._window_world_bounds()
        ww = max(maxx - minx, 1.0)
        wh = max(maxy - miny, 1.0)

        margin = 30
        base = min((cw - 2 * margin) / ww, (ch - 2 * margin) / wh)
        s = base * self.window_zoom

        tx = (cw - ww * s) / 2 - minx * s + self.window_pan_x
        ty = (ch - wh * s) / 2 + maxy * s + self.window_pan_y

        def to_canvas(x, y):
            return (tx + x * s, ty - y * s)

        return to_canvas, s


    def _draw_geom_on_canvas(self, canvas, geom, to_canvas, outline="#00FF99", fill="", width=1, tags=()):
        if geom is None or geom.is_empty:
            return

        for poly in iter_polys(geom):
            coords = list(poly.exterior.coords)
            if len(coords) < 2:
                continue

            pts = []
            for x, y in coords:
                cx, cy = to_canvas(x, y)
                pts.extend([cx, cy])

            if fill:
                canvas.create_polygon(
                    pts,
                    outline=outline,
                    fill=fill,
                    width=width,
                    stipple="gray50",
                    tags=tags,
                )
            else:
                canvas.create_line(pts, fill=outline, width=width, tags=tags)

    def _draw_feed_windows_on_workspace(self, to_canvas):
        if not getattr(self, "feed_windows", None):
            return

        c = self.workspace_canvas
        miny, maxy = self._sheet_y_bounds()

        # -------------------------
        # EXISTING: draw windows
        # -------------------------
        for j, (idx, x0, x1) in enumerate(self.feed_windows):
            active = j == self.active_window_index
            color = "#FFD54A" if active else "#4A7BFF"
            width = 3 if active else 2

            for edge_x in (x0, x1):
                cx0, cy0 = to_canvas(edge_x, miny)
                cx1, cy1 = to_canvas(edge_x, maxy)
                c.create_line(cx0, cy0, cx1, cy1, fill=color, dash=(6, 4), width=width)

            midx = 0.5 * (x0 + x1)
            lx, ly = to_canvas(midx, maxy + 34.0)
            c.create_text(
                lx, ly,
                text=f"Window {idx}",
                fill=color,
                anchor="n",
                font=("Arial", 10, "bold"),
            )

        # -------------------------
        # NEW: draw boundary handles
        # -------------------------
        for j in range(len(self.feed_windows) - 1):
            _idx, _x0, boundary_x = self.feed_windows[j]

            active_boundary = (getattr(self, "drag_boundary_index", None) == j)

            hx, hy0 = to_canvas(boundary_x, miny)
            _hx, hy1 = to_canvas(boundary_x, maxy)
            hy = 0.5 * (hy0 + hy1)

            r = 7 if active_boundary else 6
            fill = "#FFD54A" if active_boundary else "#FFFFFF"

            c.create_oval(
                hx - r, hy - r,
                hx + r, hy + r,
                fill=fill,
                outline="#222222",
                width=2,
            )


    def _window_rect_material(self, window):
        if window is None:
            return None
        _idx, x0, x1 = window
        miny, maxy = self._sheet_y_bounds()
        return box(x0, miny, x1, maxy)


    def _clip_geom_to_window(self, geom, window):
        if geom is None or geom.is_empty or window is None:
            return None
        rect = self._window_rect_material(window)
        if rect is None:
            return None
        clipped = geom.intersection(rect)
        if clipped is None or clipped.is_empty:
            return None
        return clipped


    def _material_to_machine_geom(self, geom, window):
        if geom is None or geom.is_empty or window is None:
            return None
        _idx, x0, x1 = window
        cx = 0.5 * (x0 + x1)

        def mapper(x, y, z=None):
            mx = y
            my = x - cx
            if z is None:
                return (mx, my)
            return (mx, my, z)

        transformed = geom_transform(mapper, geom)
        if transformed is None or transformed.is_empty:
            return None
        return transformed


    def _window_preview_geoms(self, window=None):
        if window is None:
            window = self._active_window()
        if window is None:
            return {"sheet": None, "holes": [], "usable": None, "packed": []}

        out = {"sheet": None, "holes": [], "usable": None, "packed": []}

        if getattr(self, "sheet_mm", None) is not None and not self.sheet_mm.is_empty:
            sheet_clip = self._clip_geom_to_window(self.sheet_mm, window)
            out["sheet"] = self._material_to_machine_geom(sheet_clip, window)

        for h in getattr(self, "holes_mm", []):
            h_clip = self._clip_geom_to_window(h, window)
            h_local = self._material_to_machine_geom(h_clip, window)
            if h_local is not None and not h_local.is_empty:
                out["holes"].append(h_local)

        if getattr(self, "usable_region_mm", None) is not None and not self.usable_region_mm.is_empty:
            usable_clip = self._clip_geom_to_window(self.usable_region_mm, window)
            out["usable"] = self._material_to_machine_geom(usable_clip, window)

        for sid, item in getattr(self, "packed_items", {}).items():
            g_clip = self._clip_geom_to_window(item["geom"], window)
            g_local = self._material_to_machine_geom(g_clip, window)
            if g_local is not None and not g_local.is_empty:
                out["packed"].append((sid, g_local))

        return out


    def _redraw_workspace(self):
        c = self.workspace_canvas
        c.delete("all")
        c.update_idletasks()

        w = max(c.winfo_width(), 400)
        h = max(c.winfo_height(), 300)
        to_canvas, _, _ = self._overview_view_transform()

        c.create_line(0, h / 2, w, h / 2, fill="#223322", dash=(3, 4))
        c.create_line(w / 2, 0, w / 2, h, fill="#223322", dash=(3, 4))

        if getattr(self, "sheet_mm", None) is not None and not self.sheet_mm.is_empty:
            self._draw_geom_on_canvas(c, self.sheet_mm, to_canvas, outline="#00FF99", fill="#0C4410", width=2, tags=("sheet",))

        for hgeom in getattr(self, "holes_mm", []):
            self._draw_geom_on_canvas(c, hgeom, to_canvas, outline="#00FF99", fill="#050505", width=2, tags=("hole",))

        if getattr(self, "usable_region_mm", None) is not None and not self.usable_region_mm.is_empty:
            self._draw_geom_on_canvas(c, self.usable_region_mm, to_canvas, outline="#335533", fill="", width=1, tags=("usable",))

        self._draw_feed_windows_on_workspace(to_canvas)

        for sid, item in getattr(self, "packed_items", {}).items():
            geom = item["geom"]
            active = sid == self.active_packed_slat_id
            outline = "#FFD54A" if active else "#66CCFF"
            fill = "#334455" if active else "#1B2730"
            self._draw_geom_on_canvas(
                c,
                geom,
                to_canvas,
                outline=outline,
                fill=fill,
                width=2 if active else 1,
                tags=("packed", f"packed:{sid}"),
            )

        if getattr(self, "sheet_mm", None) is None and not getattr(self, "packed_items", {}):
            c.create_text(w / 2, h / 2, text="Load DXF and pack slats", fill="#999999", font=("Arial", 12))


    def _redraw_window_preview(self):
        c = self.window_canvas
        c.delete("all")
        c.update_idletasks()

        w = max(c.winfo_width(), 400)
        h = max(c.winfo_height(), 250)

        if not getattr(self, "feed_windows", None):
            c.create_text(w / 2, h / 2, text="Load DXF to preview feed windows", fill="#999999", font=("Arial", 12))
            return

        to_canvas, _ = self._window_view_transform()
        preview = self._window_preview_geoms()

        ax0, ay0 = to_canvas(-10000, 0.0)
        ax1, ay1 = to_canvas(10000, 0.0)
        c.create_line(ax0, ay0, ax1, ay1, fill="#355535", dash=(3, 4))
        ax0, ay0 = to_canvas(0.0, -10000)
        ax1, ay1 = to_canvas(0.0, 10000)
        c.create_line(ax0, ay0, ax1, ay1, fill="#355535", dash=(3, 4))

        gantry_w = float(self.gantry_width_x_var.get() or self.slats_cam_cardboard_width_mm.get() or "280.0")
        gantry_h = float(self.feed_window_y_var.get() or self.slats_cam_feed_window_mm.get() or "120.0")
        gx0, gy0 = to_canvas(-gantry_w / 2.0, -gantry_h / 2.0)
        gx1, gy1 = to_canvas(gantry_w / 2.0, gantry_h / 2.0)
        c.create_rectangle(gx0, gy1, gx1, gy0, outline="#4A7BFF", width=2)

        if preview["sheet"] is not None:
            self._draw_geom_on_canvas(c, preview["sheet"], to_canvas, outline="#00FF99", fill="#0C4410", width=2)

        for hgeom in preview["holes"]:
            self._draw_geom_on_canvas(c, hgeom, to_canvas, outline="#00FF99", fill="#050505", width=2)

        if preview["usable"] is not None:
            self._draw_geom_on_canvas(c, preview["usable"], to_canvas, outline="#335533", fill="", width=1)

        for sid, g in preview["packed"]:
            active = sid == self.active_packed_slat_id
            outline = "#FFD54A" if active else "#66CCFF"
            fill = "#334455" if active else "#1B2730"
            self._draw_geom_on_canvas(c, g, to_canvas, outline=outline, fill=fill, width=2 if active else 1)

        c.create_text(12, 12, anchor="nw", text="Machine coords: X=cardboard width, Y=feed direction", fill="#BBBBBB", font=("Arial", 10, "bold"))


    def _redraw_all_views(self):
        self._redraw_workspace()
        self._redraw_window_preview()
            

    def _toggle_slat_selection(self, sid):
        if sid in self.selected_slat_ids:
            self.selected_slat_ids.remove(sid)
        else:
            self.selected_slat_ids.add(sid)

        print("selected:", self.selected_slat_ids)  # 👈 DEBUG
        self._refresh_library_selection_styles()


    def _use_blank_sheet(self):
        try:
            cardboard_width_mm = float(self.slats_cam_cardboard_width_mm.get() or "120.0")
            feed_window_len = float(self.slats_cam_feed_window_mm.get() or "120.0")
            edge_margin_mm = float(self.slats_cam_edge_margin_mm.get() or "5.0")

            length_mm = max(feed_window_len * 5.0, feed_window_len + 1.0)
            sheet_mm = box(
                -feed_window_len / 2.0,
                -cardboard_width_mm / 2.0,
                -feed_window_len / 2.0 + length_mm,
                cardboard_width_mm / 2.0,
            )

            usable_region_mm = sheet_mm.buffer(-edge_margin_mm)
            if usable_region_mm is None or usable_region_mm.is_empty:
                usable_region_mm = sheet_mm

            self.slats_cam_dxf_path = None
            self.sheet_raw = None
            self.holes_raw = []
            self.sheet_mm = sheet_mm
            self.holes_mm = []
            self.usable_region_mm = usable_region_mm
            self.gantry_width_x_var.set(f"{cardboard_width_mm:.3f}")
            self.feed_window_y_var.set(f"{feed_window_len:.3f}")
            self._rebuild_feed_windows()

            self.slats_cam_status_var.set("Blank sheet ready")
            self._fit_workspace()
        except Exception as e:
            messagebox.showerror("Blank Sheet Error", str(e))


    def _use_vision_dxf_for_slats_cam(self):
        if not getattr(self, "dxf_file_path", None):
            self.slats_cam_status_var.set("No Vision DXF loaded")
            self._append_console("> No DXF loaded in Vision + DXF tab")
            return

        try:
            self.slats_cam_dxf_path = Path(self.dxf_file_path)

            polys = fidxf.load_closed_polygons_from_dxf(self.slats_cam_dxf_path)
            min_sheet_area = float(self.slats_cam_min_sheet_area_var.get() or "50000.0")
            sheet_index = int(self.slats_cam_sheet_index_var.get() or "0")

            sheets = fidxf.classify_sheet_candidates(polys, min_sheet_area=min_sheet_area)
            if sheet_index >= len(sheets):
                raise IndexError(
                    f"sheet_index={sheet_index} but only {len(sheets)} sheet candidates found"
                )

            sheet_raw, holes_raw = sheets[sheet_index]

            cardboard_width_mm = float(self.slats_cam_cardboard_width_mm.get() or "280.0")
            feed_window_len = float(self.slats_cam_feed_window_mm.get() or "120.0")
            edge_margin_mm = float(self.slats_cam_edge_margin_mm.get() or "5.0")
            cut_clearance_mm = float(self.slats_cam_cut_clearance_mm.get() or "1.0")

            # same helper flow as normal CAM DXF load
            self.sheet_raw = sheet_raw
            self.holes_raw = holes_raw

            self.sheet_mm = fidxf.normalize_sheet_to_cardboard_width(sheet_raw, cardboard_width_mm)
            self.holes_mm = [
                fidxf.normalize_sheet_to_cardboard_width(h, cardboard_width_mm)
                for h in holes_raw
            ]

            usable = self.sheet_mm.buffer(-edge_margin_mm)
            if usable is None or usable.is_empty:
                usable = self.sheet_mm

            if self.holes_mm:
                try:
                    usable = usable.difference(unary_union([h.buffer(cut_clearance_mm) for h in self.holes_mm]))
                except Exception:
                    pass

            self.usable_region_mm = usable
            self.gantry_width_x_var.set(f"{cardboard_width_mm:.3f}")
            self.feed_window_y_var.set(f"{feed_window_len:.3f}")
            self._rebuild_feed_windows()

            name = self.slats_cam_dxf_path.name
            self.slats_cam_status_var.set(f"Using Vision DXF: {name}")
            self._append_console(f"> Linked Vision + DXF file to Slats CAM: {name}")
            self._fit_workspace()

        except Exception as exc:
            messagebox.showerror("Vision DXF Link Error", str(exc))
            self.slats_cam_status_var.set("Vision DXF link error")


    def _use_photogrammetry_mesh_for_slats_cam(self):
        if not getattr(self, "photogrammetry_mesh_path", None):
            self.slats_cam_status_var.set("No photogrammetry mesh loaded")
            self._append_console("> No mesh loaded in Photogrammetry tab")
            return

        p = Path(self.photogrammetry_mesh_path)
        self.slats_cam_mesh_path = p
        self.slats_cam_stl_path = p   # legacy alias used by CAM generator

        if hasattr(self, "slats_cam_stl_path_var"):
            self.slats_cam_stl_path_var.set(p.name)

        self.slats_cam_slats_info_var.set(f"Mesh linked: {p.name}")
        self.slats_cam_status_var.set("Using photogrammetry mesh")
        self._append_console(f"> Linked photogrammetry mesh to Slats CAM: {p.name}")


    def _use_slats_tab_setup_for_slats_cam(self):
        mesh_path = getattr(self, "scan_mesh_path", None) or getattr(self, "photogrammetry_mesh_path", None)
        if not mesh_path:
            self.slats_cam_status_var.set("No Slats-tab mesh available")
            self._append_console("> No mesh available from Slats tab")
            return

        try:
            xy = int(float(self.n_xy_var.get()))
            xz = int(float(self.n_xz_var.get()))
        except Exception:
            self.slats_cam_status_var.set("Invalid Slats-tab counts")
            self._append_console("> Invalid XY/XZ counts in Slats tab")
            return

        p = Path(mesh_path)
        self.slats_cam_mesh_path = p
        self.slats_cam_stl_path = p
        self.xy_count_var.set(str(xy))
        self.xz_count_var.set(str(xz))

        if hasattr(self, "slats_cam_stl_path_var"):
            self.slats_cam_stl_path_var.set(p.name)

        # CAM cannot directly reuse self.slats_data; it needs full CAM records.
        self.all_slat_records = generate_slats(self.slats_cam_stl_path, xy, xz)
        self.selected_slat_ids = set()
        self.packed_items = {}
        self.active_packed_slat_id = None

        self.slats_cam_slats_info_var.set(
            f"{len(self.all_slat_records)} slats linked from Slats tab"
        )

        self._rebuild_library_tiles()
        self._update_selected_count()
        self.slats_cam_status_var.set("Using Slats tab mesh + counts")
        self._append_console(
            f"> Linked Slats tab setup to Slats CAM: {p.name} | XY={xy} XZ={xz}"
        )

    def _generate_current_window_gcode(self):
        try:
            from apps.gcode.slat_toolpaths import geometry_to_knife_segments, chain_segments
            from gcode.emit_gcode import emit_gcode
            from apps.gcode.machine_ops_types import (
                RapidMove, ToolDown, ToolUp, CutPath, PivotAction
            )
            from gcode.emit_gcode import get_angle, angle_diff_deg

            window = self._active_window()
            if window is None:
                messagebox.showerror("G-code Error", "No active window.")
                return

            if not self.packed_items:
                messagebox.showerror("G-code Error", "No packed slats.")
                return

            # -----------------------------------------
            # 1) collect window geometry ONLY
            # -----------------------------------------
            machine_geoms = []

            for item in self.packed_items.values():
                geom = item.get("geom")
                if geom is None or geom.is_empty:
                    continue

                g_clip = self._clip_geom_to_window(geom, window)
                if g_clip is None or g_clip.is_empty:
                    continue

                g_local = self._material_to_machine_geom(g_clip, window)
                if g_local is None or g_local.is_empty:
                    continue

                machine_geoms.append(g_local)

            if not machine_geoms:
                messagebox.showwarning("No geometry", "Nothing in this window.")
                return

            # -----------------------------------------
            # 2) geometry → toolpaths
            # -----------------------------------------
            knife_segments = []
            for geom in machine_geoms:
                knife_segments.extend(geometry_to_knife_segments(geom))

            knife_paths = chain_segments(knife_segments)

            toolpaths = {
                "knife": knife_paths,
                "crease": [],
            }

            # -----------------------------------------
            # 3) single-window ops (from run_slats.py)
            # -----------------------------------------
            PIVOT_ANGLE_THRESHOLD = 10.0
            ops = []
            last_angle = None

            for path in toolpaths["knife"]:
                if not path or len(path) < 2:
                    continue

                angle = get_angle(path[0], path[1])

                if last_angle is None or abs(angle_diff_deg(angle, last_angle)) > PIVOT_ANGLE_THRESHOLD:
                    ops.append(PivotAction(tool="knife", angle=angle))

                ops.append(RapidMove(to=path[0]))
                ops.append(ToolDown(tool="knife"))
                ops.append(CutPath(path=path))
                ops.append(ToolUp())

                last_angle = angle

            # -----------------------------------------
            # 4) emit + load
            # -----------------------------------------
            gantry_h = float(self.slats_cam_feed_window_mm.get() or "200.0")

            gcode = emit_gcode(ops, feed_window_y=gantry_h)

            idx, x0, x1 = window
            default_name = f"slats_window_{idx+1:02d}_{x0:.1f}_{x1:.1f}.nc"

            from datetime import datetime
            from pathlib import Path

            if self.slats_cam_run_dir is None:
                run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                self.slats_cam_run_dir = Path("data/slats_cam") / run_id
                self.slats_cam_run_dir.mkdir(parents=True, exist_ok=True)

            out_path = self.slats_cam_run_dir / default_name

            Path(out_path).write_text(gcode)

            self.gcode_lines = [line for line in gcode.splitlines() if line.strip()]
            self.file_text.set(Path(out_path).name)
            self.slats_cam_status_var.set(f"G-code generated for window {idx+1}")

            self._append_console(f"> Generated single-window G-code: {out_path}")
            self._append_console(
                f"> Window {idx+1}: x=[{x0:.1f}, {x1:.1f}] | "
                f"parts={len(machine_geoms)} | paths={len(toolpaths['knife'])} | ops={len(ops)}"
            )

            try:
                self._load_gcode_from_string(gcode, display_name=Path(out_path).name)
            except Exception:
                pass

        except Exception as exc:
            messagebox.showerror("G-code Error", str(exc))
            self._append_console(f"[GCODE ERROR] {exc}")

    def _prepare_continuous_job(self):
        try:
            if not getattr(self, "packed_items", None):
                messagebox.showerror("G-code Error", "No packed slats to generate.")
                return

            # -----------------------------------------
            # 1) build FULL geometry (no window clipping)
            # -----------------------------------------
            from apps.gcode.slat_toolpaths import geometry_to_knife_segments, chain_segments

            world_geoms = []
            for item in self.packed_items.values():
                geom = item.get("geom")
                if geom is None or geom.is_empty:
                    continue
                world_geoms.append(geom)

            if not world_geoms:
                messagebox.showerror("G-code Error", "No geometry found.")
                return

            # -----------------------------------------
            # 2) geometry → toolpaths (WORLD space)
            # -----------------------------------------
            knife_segments = []
            for geom in world_geoms:
                knife_segments.extend(geometry_to_knife_segments(geom))

            knife_paths = chain_segments(knife_segments)

            toolpaths = {
                "knife": knife_paths,
                "crease": [],
            }

            # -----------------------------------------
            # 3) build roll-feed ops
            # -----------------------------------------
            from gantry.roll_feed_cam import RollFeedGantry, build_roll_feed_ops

            gantry = RollFeedGantry(
                feed_window_y=float(self.slats_cam_feed_window_mm.get() or "120.0"),
                gantry_width_x=float(self.slats_cam_cardboard_width_mm.get() or "280.0"),
                feed_clearance_y=20.0,
            )

            ops, feed_positions = build_roll_feed_ops(toolpaths, gantry)

            # -----------------------------------------
            # 4) store job (IMPORTANT)
            # -----------------------------------------
            self.slats_cam_toolpaths = toolpaths
            self.slats_cam_continuous_ops = ops
            self.slats_cam_feed_positions = feed_positions

            # -----------------------------------------
            # 5) UI feedback
            # -----------------------------------------
            self.slats_cam_status_var.set("Continuous job prepared")
            self._append_console(
                f"> Continuous job ready | paths={len(toolpaths['knife'])} | ops={len(ops)}"
            )

        except Exception as exc:
            messagebox.showerror("Continuous Job Error", str(exc))
            self._append_console(f"[CONTINUOUS ERROR] {exc}")

    def _generate_continuous_gcode(self):
        try:
            if not getattr(self, "packed_items", None):
                messagebox.showerror("G-code Error", "No packed slats to generate.")
                return

            self.slats_cam_status_var.set("Continuous G-code not implemented yet")
            self._append_console("> Continuous all-windows G-code not implemented yet")

        except Exception as exc:
            messagebox.showerror("G-code Error", str(exc))
            self._append_console(f"[GCODE ERROR] {exc}")


    # =========================
    # STATUS PARSING
    # =========================
    def _parse_status(self, line: str) -> None:
        """
        Parse status lines like:
        <Idle|MPos:0.000,0.000,0.000|WPos:0.000,0.000,0.000|Pn:XZ>
        or:
        <Idle|MPos:...|WCO:...|Pn:...>
        """
        if not line.startswith("<") or not line.endswith(">"):
            return

        body = line[1:-1]
        parts = body.split("|")
        if not parts:
            return

        state = parts[0].strip()
        self.machine_state = state
        self.state_text.set(f"State: {state}")

        if state == "Alarm":
            self.in_alarm = True
        elif state in ("Idle", "Run", "Jog", "Hold", "Home", "Check", "Door", "Sleep"):
            self.in_alarm = False

        saw_pn = False
        mpos_coords = None
        wpos_coords = None
        wco_coords = None

        for part in parts[1:]:
            if ":" not in part:
                continue

            key, val = part.split(":", 1)
            key = key.strip()
            val = val.strip()

            if key == "MPos":
                coords = [c.strip() for c in val.split(",")]
                mpos_coords = coords
                self.machine_pos_text.set(f"MPos: {val}")

                if len(coords) > 0:
                    self.machine_pos_x_text.set(coords[0])
                if len(coords) > 1:
                    self.machine_pos_y_text.set(coords[1])
                if len(coords) > 2:
                    self.machine_pos_z_text.set(coords[2])
                if len(coords) > 3:
                    self.machine_pos_a_text.set(coords[3])
                if len(coords) > 4:
                    self.machine_pos_b_text.set(coords[4])
                if len(coords) > 5:
                    self.machine_pos_c_text.set(coords[5])

                self._update_preview_from_machine_pos()

            elif key == "WPos":
                coords = [c.strip() for c in val.split(",")]
                wpos_coords = coords
                self.work_pos_text.set(f"WPos: {val}")

                if len(coords) > 0:
                    self.work_pos_x_text.set(coords[0])
                if len(coords) > 1:
                    self.work_pos_y_text.set(coords[1])
                if len(coords) > 2:
                    self.work_pos_z_text.set(coords[2])
                if len(coords) > 3:
                    self.work_pos_a_text.set(coords[3])
                if len(coords) > 4:
                    self.work_pos_b_text.set(coords[4])
                if len(coords) > 5:
                    self.work_pos_c_text.set(coords[5])

            elif key == "WCO":
                wco_coords = [c.strip() for c in val.split(",")]

            elif key == "Pn":
                saw_pn = True
                active = set(val.upper())

                labels = []
                for axis in ["X", "Y", "Z", "A", "B"]:
                    if axis in active:
                        labels.append(f"[{axis}]")
                    else:
                        labels.append(axis)

                self.limit_switch_text.set("Limits: " + " ".join(labels))

                if hasattr(self, "limit_labels"):
                    for axis, lbl in self.limit_labels.items():
                        if axis in active:
                            lbl.config(bg="#FFD54A", fg="#111111")
                        else:
                            lbl.config(bg="#444444", fg="#FFFFFF")

        # If firmware reports MPos + WCO but not WPos, compute WPos ourselves
        if wpos_coords is None and mpos_coords is not None and wco_coords is not None:
            try:
                n = min(len(mpos_coords), len(wco_coords), 6)
                computed = [f"{float(mpos_coords[i]) - float(wco_coords[i]):.2f}" for i in range(n)]
                joined = ",".join(computed)
                self.work_pos_text.set(f"WPos: {joined}")

                if len(computed) > 0:
                    self.work_pos_x_text.set(computed[0])
                if len(computed) > 1:
                    self.work_pos_y_text.set(computed[1])
                if len(computed) > 2:
                    self.work_pos_z_text.set(computed[2])
                if len(computed) > 3:
                    self.work_pos_a_text.set(computed[3])
                if len(computed) > 4:
                    self.work_pos_b_text.set(computed[4])
                if len(computed) > 5:
                    self.work_pos_c_text.set(computed[5])
            except Exception:
                pass

        if not saw_pn:
            self.limit_switch_text.set("Limits: --")
            if hasattr(self, "limit_labels"):
                for lbl in self.limit_labels.values():
                    lbl.config(bg="#444444", fg="#FFFFFF")

    # =========================
    # RX / STATUS POLLING
    # =========================
    def _process_rx(self) -> None:
        try:
            for line in self.ctrl.get_status_lines():
                self.last_status_text.set(f"Last status: {line}")

                if hasattr(self, "machine_status_var"):
                    self.machine_status_var.set(line)

                if line.startswith("<") and line.endswith(">"):
                    self._parse_status(line)
                else:
                    self._append_console(f"<< {line}")
        finally:
            self.after(self.RX_PROCESS_MS, self._process_rx)

    def _status_poll_loop(self) -> None:
        try:
            if self.polling and self.ctrl.is_connected:
                self.ctrl.send_realtime(b"?")
        finally:
            self.after(self.POLL_MS, self._status_poll_loop)


if __name__ == "__main__":
    app = TouchUI()
    app.mainloop()