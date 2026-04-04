from __future__ import annotations

import sys
import importlib.util
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, Point, box
from shapely.affinity import translate
from shapely.ops import unary_union, transform as geom_transform


# =========================================================
# PATH SETUP
# =========================================================
HERE = Path(__file__).resolve().parent
APPS_DIR = HERE.parents[2]          # .../apps
PROJECT_ROOT = APPS_DIR.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =========================================================
# LOAD ORIGINAL TOUCH UI MODULE
# =========================================================
SOURCE_FILE = HERE / "grbl_touch_ui.py"


def load_touchui_module(py_file: Path):
    if not py_file.exists():
        raise FileNotFoundError(f"Could not find: {py_file}")

    spec = importlib.util.spec_from_file_location("grbl_touch_ui_module", str(py_file))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from: {py_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["grbl_touch_ui_module"] = module
    spec.loader.exec_module(module)
    return module


mod = load_touchui_module(SOURCE_FILE)
TouchUI = mod.TouchUI

BG = getattr(mod, "BG", "#111111")
FG = getattr(mod, "FG", "#F2F2F2")
PANEL_BG = getattr(mod, "PANEL_BG", "#202020")
BTN_BLUE = getattr(mod, "BTN_BLUE", "#4A90E2")
BTN_BLUE_FG = getattr(mod, "BTN_BLUE_FG", "#000000")
BTN_NEUTRAL = getattr(mod, "BTN_NEUTRAL", "#DDDDDD")
BTN_NEUTRAL_FG = getattr(mod, "BTN_NEUTRAL_FG", "#000000")
BTN_ORANGE = getattr(mod, "BTN_ORANGE", "#FFAA33")
BTN_ORANGE_FG = getattr(mod, "BTN_ORANGE_FG", "#000000")
ENTRY_BG = getattr(mod, "ENTRY_BG", "#FFFFFF")


# =========================================================
# FILLER INTEGRATION BACKEND
# =========================================================
from integration import filler_integration_dxf as fidxf


# =========================================================
# SMALL RECORD HELPERS
# =========================================================
def rec_get(rec, key, default=None):
    if isinstance(rec, dict):
        return rec.get(key, default)
    return getattr(rec, key, default)



def record_geom(rec):
    try:
        return fidxf.record_geom(rec)
    except Exception:
        return rec_get(rec, "geom")



def record_id(rec):
    try:
        return fidxf.record_id(rec)
    except Exception:
        sid = rec_get(rec, "slat_id")
        if sid:
            return str(sid)
        fam = rec_get(rec, "family", "SLAT")
        side = rec_get(rec, "side", "na")
        idx = rec_get(rec, "index", 0)
        return f"{fam}_{side}_{idx:02d}"



def record_family(rec):
    fam = rec_get(rec, "family")
    if fam:
        return str(fam)
    sid = record_id(rec).upper()
    if sid.startswith("XY"):
        return "XY"
    if sid.startswith("XZ"):
        return "XZ"
    return "UNK"



def record_side(rec):
    side = rec_get(rec, "side")
    if side:
        return str(side)
    sid = record_id(rec).lower()
    if "_left_" in sid:
        return "left"
    if "_right_" in sid:
        return "right"
    return "na"



def iter_polys(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            yield from iter_polys(g)
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            yield from iter_polys(g)
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from iter_polys(g)



def normalize_part(geom):
    try:
        return fidxf.normalize_part_to_origin(geom)
    except Exception:
        if geom is None or geom.is_empty:
            return None
        bx0, by0, _, _ = geom.bounds
        return translate(geom, xoff=-bx0, yoff=-by0)



def place_geom(geom, x, y, rot_deg):
    try:
        return fidxf.place_geom(geom, x, y, rot_deg)
    except Exception:
        g = normalize_part(geom)
        if g is None:
            return None
        return translate(g, xoff=x, yoff=y)



def filter_records_by_requested_counts(records, xy_count, xz_count):
    buckets = {
        ("XY", "left"): [],
        ("XY", "right"): [],
        ("XZ", "left"): [],
        ("XZ", "right"): [],
    }

    for rec in records:
        fam = record_family(rec).upper()
        side = record_side(rec).lower()
        key = (fam, side)
        if key in buckets:
            buckets[key].append(rec)

    for key in buckets:
        buckets[key] = sorted(buckets[key], key=lambda r: record_id(r))

    out = []
    out.extend(buckets[("XY", "left")][:xy_count])
    out.extend(buckets[("XY", "right")][:xy_count])
    out.extend(buckets[("XZ", "left")][:xz_count])
    out.extend(buckets[("XZ", "right")][:xz_count])
    return out


# =========================================================
# APP
# =========================================================
class SlatsCamOnlyApp(TouchUI):
    def __init__(self):
        super().__init__()
        self.title("Slats CAM Only")
        self.geometry("1760x1020")

        keep_name = "Slats CAM"
        for name, frame in list(self.tab_frames.items()):
            if name != keep_name:
                try:
                    self.notebook.forget(frame)
                except Exception:
                    pass

        if keep_name in self.tab_frames:
            self.notebook.select(self.tab_frames[keep_name])

        self.slats_tab = self.tab_frames[keep_name]
        for child in self.slats_tab.winfo_children():
            child.destroy()

        # -------------------------
        # state
        # -------------------------
        self.slats_cam_stl_path = None
        self.slats_cam_dxf_path = None

        self.all_slat_records = []
        self.selected_slat_ids = set()
        self.packed_items = {}          # sid -> {"rec","x","y","rot","geom","note"}
        self.active_packed_slat_id = None

        self.sheet_raw = None
        self.holes_raw = []
        self.sheet_mm = None
        self.holes_mm = []
        self.usable_region_mm = None
        self.feed_windows = []          # list[(idx, x0, x1)] in material/cardboard space
        self.active_window_index = 0

        self.gantry_width_x_var = tk.StringVar(value="300.0")
        self.feed_window_y_var = tk.StringVar(value="200.0")
        self.cardboard_offset_x_var = tk.StringVar(value="0.0")
        self.cardboard_offset_y_var = tk.StringVar(value="0.0")

        self.workspace_zoom = 1.0
        self.workspace_pan_x = 0.0
        self.workspace_pan_y = 0.0
        self.drag_item_id = None
        self.drag_last_xy = None
        self.drag_original_pose = None
        self.drag_boundary_index = None   # index of interior boundary between windows
        self._pan_start = None

        self.window_zoom = 1.0
        self.window_pan_x = 0.0
        self.window_pan_y = 0.0

        self.library_tile_map = {}
        self.library_canvas_container = None
        self.library_inner = None
        self.library_window = None

        # -------------------------
        # vars
        # -------------------------
        self.slats_cam_slats_info_var = tk.StringVar(value="No slats loaded")
        self.slats_cam_status_var = tk.StringVar(value="No cardboard loaded")
        self.selected_count_var = tk.StringVar(value="Selected: 0 / 0")
        self.window_info_var = tk.StringVar(value="Window: none")

        self.slats_cam_cardboard_width_mm = tk.StringVar(value="300.0")
        self.slats_cam_edge_margin_mm = tk.StringVar(value="5.0")
        self.slats_cam_cut_clearance_mm = tk.StringVar(value="1.0")
        self.slats_cam_gap_mm_var = tk.StringVar(value="4.0")
        self.slats_cam_feed_window_mm = tk.StringVar(value="200.0")
        self.slats_cam_sheet_index_var = tk.StringVar(value="0")
        self.slats_cam_min_sheet_area_var = tk.StringVar(value="50000.0")

        self.xy_count_var = tk.StringVar(value="5")
        self.xz_count_var = tk.StringVar(value="5")

        self._build_new_slats_cam_tab(self.slats_tab)

    # =====================================================
    # UI BUILD
    # =====================================================
    def _style_combobox(self):
        style = ttk.Style(self)
        try:
            style.theme_use("default")
        except Exception:
            pass
        style.configure(
            "Slats.TCombobox",
            fieldbackground=ENTRY_BG,
            background="#FFFFFF",
            foreground="#000000",
            arrowsize=16,
        )


    def _build_new_slats_cam_tab(self, parent):
        self._style_combobox()

        title_font = ("Arial", 13, "bold")
        ui_font = ("Arial", 10, "bold")
        section_font = ("Arial", 11, "bold")
        small_font = ("Arial", 9)

        right_col_width = 420

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=8, pady=8)

        # -------------------------
        # Bottom action bar first so it never gets squished
        # -------------------------
        bottom = tk.Frame(main, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))

        tk.Button(
            bottom,
            text="✓ GENERATE G-CODE",
            command=self._generate_gcode_stub,
            bg="#EEEEEE",
            fg="#111111",
            font=("Arial", 14, "bold"),
            height=2,
        ).pack(fill="x")

        # -------------------------
        # TOP STRIP
        #   left  = setup / packing / overview controls
        #   right = slat library controls (same width as right column below)
        # -------------------------
        top_strip = tk.Frame(main, bg=BG)
        top_strip.pack(side="top", fill="x", pady=(0, 8))

        setup_frame = tk.LabelFrame(
            top_strip,
            text="Setup & Packing",
            bg=PANEL_BG,
            fg=FG,
            font=title_font,
            padx=10,
            pady=8,
            bd=2,
            relief="solid",
        )
        setup_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # row 1: STL generation
        row1 = tk.Frame(setup_frame, bg=PANEL_BG)
        row1.pack(fill="x", pady=(0, 6))

        tk.Button(
            row1,
            text="Browse STL",
            command=self._browse_stl,
            bg=BTN_NEUTRAL,
            fg=BTN_NEUTRAL_FG,
            font=ui_font,
            width=12,
        ).pack(side="left", padx=(0, 10))

        tk.Label(row1, text="XY Slats:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(4, 4))
        self.xy_combo = ttk.Combobox(
            row1,
            textvariable=self.xy_count_var,
            values=[str(i) for i in range(2, 11)],
            state="readonly",
            width=4,
            style="Slats.TCombobox",
        )
        self.xy_combo.pack(side="left", padx=(0, 10))

        tk.Label(row1, text="XZ Slats:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(4, 4))
        self.xz_combo = ttk.Combobox(
            row1,
            textvariable=self.xz_count_var,
            values=[str(i) for i in range(2, 11)],
            state="readonly",
            width=4,
            style="Slats.TCombobox",
        )
        self.xz_combo.pack(side="left", padx=(0, 10))

        tk.Button(
            row1,
            text="Generate Slats",
            command=self._generate_slats,
            bg=BTN_BLUE,
            fg=BTN_BLUE_FG,
            font=ui_font,
        ).pack(side="left", padx=(0, 10))

        tk.Label(
            row1,
            textvariable=self.slats_cam_slats_info_var,
            bg=PANEL_BG,
            fg="#FFD54A",
            font=ui_font,
        ).pack(side="left", padx=10)

        # row 2: sheet / packing actions
        row2 = tk.Frame(setup_frame, bg=PANEL_BG)
        row2.pack(fill="x", pady=(0, 6))

        tk.Button(
            row2,
            text="Load DXF",
            command=self._load_dxf,
            bg=BTN_NEUTRAL,
            fg=BTN_NEUTRAL_FG,
            font=ui_font,
            width=11,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            row2,
            text="Blank Sheet",
            command=self._use_blank_sheet,
            bg=BTN_NEUTRAL,
            fg=BTN_NEUTRAL_FG,
            font=ui_font,
            width=11,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            row2,
            text="Auto-Pack Selected",
            command=self._auto_pack_selected,
            bg=BTN_BLUE,
            fg=BTN_BLUE_FG,
            font=ui_font,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            row2,
            text="Clear Packed",
            command=self._clear_packed,
            bg=BTN_ORANGE,
            fg=BTN_ORANGE_FG,
            font=ui_font,
        ).pack(side="left", padx=(0, 8))

        # row 3: dimensions + status
        row3 = tk.Frame(setup_frame, bg=PANEL_BG)
        row3.pack(fill="x", pady=(0, 6))

        tk.Label(row3, text="Cardboard W", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(0, 4))
        tk.Entry(row3, textvariable=self.slats_cam_cardboard_width_mm, width=8).pack(side="left", padx=(0, 10))

        tk.Label(row3, text="Feed Len", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(8, 4))
        tk.Entry(row3, textvariable=self.slats_cam_feed_window_mm, width=8).pack(side="left", padx=(0, 10))

        tk.Label(row3, text="Gap", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(8, 4))
        tk.Entry(row3, textvariable=self.slats_cam_gap_mm_var, width=5).pack(side="left", padx=(0, 14))

        tk.Label(row3, text="Status:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(12, 4))
        tk.Label(row3, textvariable=self.slats_cam_status_var, bg=PANEL_BG, fg="#FFD54A", font=ui_font).pack(side="left")

        # row 4: overview + active feed window controls
        row4 = tk.Frame(setup_frame, bg=PANEL_BG)
        row4.pack(fill="x")

        tk.Label(row4, text="Overview:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(0, 8))
        tk.Button(row4, text="−", command=lambda: self._zoom_workspace(0.9), bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, width=3, font=ui_font).pack(side="left", padx=1)
        tk.Button(row4, text="+", command=lambda: self._zoom_workspace(1.1), bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, width=3, font=ui_font).pack(side="left", padx=1)
        tk.Button(row4, text="Fit View", command=self._fit_workspace, bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).pack(side="left", padx=8)
        tk.Button(row4, text="Rotate -90", command=lambda: self._rotate_active(-90), bg=BTN_ORANGE, fg=BTN_ORANGE_FG, font=ui_font).pack(side="left", padx=8)
        tk.Button(row4, text="Rotate +90", command=lambda: self._rotate_active(90), bg=BTN_ORANGE, fg=BTN_ORANGE_FG, font=ui_font).pack(side="left", padx=4)

        tk.Label(row4, text="   Active Window:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(14, 6))
        tk.Button(row4, text="◀ Prev", command=self._prev_window, bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).pack(side="left", padx=2)
        tk.Button(row4, text="Next ▶", command=self._next_window, bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).pack(side="left", padx=2)
        tk.Label(row4, textvariable=self.window_info_var, bg=PANEL_BG, fg="#FFD54A", font=ui_font).pack(side="left", padx=(10, 0))

        # top-right controls; same width as the lower slat library column
        library_ctrl = tk.LabelFrame(
            top_strip,
            text="Slat Library",
            bg=PANEL_BG,
            fg=FG,
            font=section_font,
            bd=2,
            relief="solid",
            width=right_col_width,
        )
        library_ctrl.pack(side="right", fill="y")
        library_ctrl.pack_propagate(False)

        btngrid = tk.Frame(library_ctrl, bg=PANEL_BG)
        btngrid.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        for col in range(2):
            btngrid.grid_columnconfigure(col, weight=1, uniform="libbtn")

        tk.Button(btngrid, text="Select All", command=self._select_all_slats, bg=BTN_BLUE, fg=BTN_BLUE_FG, font=ui_font).grid(row=0, column=0, padx=3, pady=3, sticky="ew")
        tk.Button(btngrid, text="Clear", command=self._clear_selection, bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).grid(row=0, column=1, padx=3, pady=3, sticky="ew")
        tk.Button(btngrid, text="Select XY", command=lambda: self._select_family("XY"), bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).grid(row=1, column=0, padx=3, pady=3, sticky="ew")
        tk.Button(btngrid, text="Select XZ", command=lambda: self._select_family("XZ"), bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).grid(row=1, column=1, padx=3, pady=3, sticky="ew")
        tk.Button(btngrid, text="Select Left", command=lambda: self._select_side("left"), bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).grid(row=2, column=0, padx=3, pady=3, sticky="ew")
        tk.Button(btngrid, text="Select Right", command=lambda: self._select_side("right"), bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=ui_font).grid(row=2, column=1, padx=3, pady=3, sticky="ew")
        tk.Button(btngrid, text="Insert Selected", command=self._insert_selected_slats, bg=BTN_BLUE, fg=BTN_BLUE_FG, font=ui_font).grid(row=3, column=0, columnspan=2, padx=3, pady=(6, 3), sticky="ew")

        btnrow3 = tk.Frame(library_ctrl, bg=PANEL_BG)
        btnrow3.pack(fill="x", padx=8, pady=(0, 8))
        tk.Label(btnrow3, textvariable=self.selected_count_var, bg=PANEL_BG, fg="#CCCCCC", font=small_font).pack(side="left")

        # -------------------------
        # Body
        # -------------------------
        body = tk.Frame(main, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right = tk.Frame(body, bg=BG, width=right_col_width)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)

        viewers = tk.PanedWindow(left, orient="vertical", bg=BG, sashwidth=8, sashrelief="raised")
        viewers.pack(fill="both", expand=True)
        self.viewers_paned = viewers
        self.after(250, self._set_initial_viewer_sash)

        overview_frame = tk.LabelFrame(
            viewers,
            text="Layout Overview (full cardboard / material coordinates)",
            bg=PANEL_BG,
            fg=FG,
            font=section_font,
            bd=2,
            relief="solid",
        )
        viewers.add(overview_frame, stretch="always")

        self.workspace_canvas = tk.Canvas(
            overview_frame,
            bg="#050505",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.workspace_canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.workspace_canvas.bind("<Configure>", lambda e: self._redraw_all_views())
        self.workspace_canvas.bind("<Button-1>", self._on_workspace_click)
        self.workspace_canvas.bind("<B1-Motion>", self._on_workspace_drag)
        self.workspace_canvas.bind("<ButtonRelease-1>", self._on_workspace_release)
        self.workspace_canvas.bind("<Button-3>", self._on_workspace_pan_start)
        self.workspace_canvas.bind("<B3-Motion>", self._on_workspace_pan_move)
        self.workspace_canvas.bind("<MouseWheel>", self._on_workspace_mousewheel)

        window_frame = tk.LabelFrame(
            viewers,
            text="Active Feed Window (gantry coordinates)",
            bg=PANEL_BG,
            fg=FG,
            font=section_font,
            bd=2,
            relief="solid",
        )
        viewers.add(window_frame, stretch="always")

        self.window_canvas = tk.Canvas(
            window_frame,
            bg="#090909",
            highlightthickness=0,
            cursor="arrow",
        )
        self.window_canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.window_canvas.bind("<Configure>", lambda e: self._redraw_all_views())

        library_host = tk.Frame(right, bg=BG)
        library_host.pack(fill="both", expand=True)

        self.library_canvas_container = tk.Canvas(
            library_host,
            bg="#101010",
            highlightthickness=1,
            highlightbackground="#333333",
        )
        self.library_canvas_container.pack(side="left", fill="both", expand=True)

        library_scrollbar = tk.Scrollbar(
            library_host,
            orient="vertical",
            command=self.library_canvas_container.yview,
        )
        library_scrollbar.pack(side="right", fill="y")
        self.library_canvas_container.configure(yscrollcommand=library_scrollbar.set)

        self.library_inner = tk.Frame(self.library_canvas_container, bg="#101010")
        self.library_window = self.library_canvas_container.create_window((0, 0), window=self.library_inner, anchor="nw")

        self.library_inner.bind("<Configure>", self._on_library_inner_configure)
        self.library_canvas_container.bind("<Configure>", self._on_library_canvas_configure)
        self.library_canvas_container.bind_all("<MouseWheel>", self._on_library_mousewheel, add="+")


    def _set_initial_viewer_sash(self):
        viewers = getattr(self, "viewers_paned", None)
        if viewers is None:
            return
        try:
            total_h = max(viewers.winfo_height(), 600)
            viewers.sash_place(0, 0, int(total_h * 0.72))
        except Exception:
            pass

    # =====================================================
    # STL
    # =====================================================
    def _browse_stl(self):
        path = filedialog.askopenfilename(
            title="Select STL",
            filetypes=[("STL files", "*.stl"), ("All files", "*.*")],
        )
        if path:
            self.slats_cam_stl_path = Path(path)
            self.slats_cam_slats_info_var.set(self.slats_cam_stl_path.name)

    def _generate_slats(self):
        if not self.slats_cam_stl_path:
            self._browse_stl()
            if not self.slats_cam_stl_path:
                return

        try:
            xy_count = int(self.xy_count_var.get())
            xz_count = int(self.xz_count_var.get())

            raw_records = fidxf.load_all_slat_records(
                self.slats_cam_stl_path,
                n_xy=xy_count,
                n_xz=xz_count,
            )
            self.all_slat_records = filter_records_by_requested_counts(raw_records, xy_count, xz_count)

            self.selected_slat_ids.clear()
            self.packed_items.clear()
            self.active_packed_slat_id = None

            xy = sum(1 for r in self.all_slat_records if record_family(r).upper().startswith("XY"))
            xz = sum(1 for r in self.all_slat_records if record_family(r).upper().startswith("XZ"))

            self.slats_cam_slats_info_var.set(f"{len(self.all_slat_records)} slats loaded (XY {xy}, XZ {xz})")
            self.slats_cam_status_var.set("Slats generated")

            self._rebuild_library_tiles()
            self._redraw_all_views()
        except Exception as e:
            messagebox.showerror("Generate Slats Error", str(e))
            self.slats_cam_status_var.set("Generate error")

    # =====================================================
    # LIBRARY
    # =====================================================
    def _update_selected_count(self):
        self.selected_count_var.set(f"Selected: {len(self.selected_slat_ids)} / {len(self.all_slat_records)}")

    def _on_library_inner_configure(self, event=None):
        self.library_canvas_container.configure(scrollregion=self.library_canvas_container.bbox("all"))

    def _on_library_canvas_configure(self, event):
        self.library_canvas_container.itemconfigure(self.library_window, width=event.width)

    def _on_library_mousewheel(self, event):
        try:
            self.library_canvas_container.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _select_all_slats(self):
        self.selected_slat_ids = {record_id(r) for r in self.all_slat_records}
        self._refresh_library_selection_styles()

    def _clear_selection(self):
        self.selected_slat_ids.clear()
        self._refresh_library_selection_styles()

    def _select_family(self, family):
        family = family.upper()
        self.selected_slat_ids = {
            record_id(r)
            for r in self.all_slat_records
            if record_family(r).upper().startswith(family)
        }
        self._refresh_library_selection_styles()

    def _select_side(self, side):
        side = side.lower()
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

            tile = tk.Frame(self.library_inner, bg="#181818", bd=2, relief="solid", cursor="hand2")
            tile.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

            header = tk.Frame(tile, bg="#181818")
            header.pack(fill="x", padx=8, pady=(8, 2))

            lbl1 = tk.Label(header, text=sid, bg="#181818", fg="#FFFFFF", font=("Arial", 9, "bold"))
            lbl1.pack(anchor="w")

            lbl2 = tk.Label(header, text=f"{fam} • {side}", bg="#181818", fg="#BBBBBB", font=("Arial", 8))
            lbl2.pack(anchor="w")

            preview = tk.Canvas(tile, width=180, height=120, bg="#181818", highlightthickness=0, cursor="hand2")
            preview.pack(fill="both", expand=True, padx=8, pady=(2, 8))

            self._draw_library_preview(preview, rec)

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

        cw = max(int(canvas.winfo_reqwidth()), 150)
        ch = max(int(canvas.winfo_reqheight()), 95)
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

    def _refresh_library_selection_styles(self):
        for sid, item in self.library_tile_map.items():
            selected = sid in self.selected_slat_ids
            tile_bg = "#162830" if selected else "#181818"

            item["tile"].configure(bg=tile_bg)
            item["header"].configure(bg=tile_bg)
            for lbl in item["labels"]:
                lbl.configure(bg=tile_bg)
            item["preview"].configure(bg=tile_bg)
            self._draw_library_preview(item["preview"], item["rec"])

        self._update_selected_count()

    def _use_blank_sheet(self):
        try:
            cardboard_width_mm = float(self.slats_cam_cardboard_width_mm.get() or "300.0")
            feed_window_len = float(self.slats_cam_feed_window_mm.get() or "200.0")
            edge_margin_mm = float(self.slats_cam_edge_margin_mm.get() or "5.0")

            length_mm = max(feed_window_len * 5.0, feed_window_len + 1.0)
            sheet_mm = box(-feed_window_len / 2.0, -cardboard_width_mm / 2.0, -feed_window_len / 2.0 + length_mm, cardboard_width_mm / 2.0)

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

    # =====================================================
    # DXF / PACKING
    # =====================================================
    def _rebuild_feed_windows(self):
        self.feed_windows = []
        self.active_window_index = 0

        if self.sheet_mm is None or self.sheet_mm.is_empty:
            self._update_window_info()
            return

        feed_window_len = float(self.slats_cam_feed_window_mm.get() or "200.0")
        self.feed_windows = fidxf.build_feed_windows_along_length(self.sheet_mm, feed_window_len)
        self._update_window_info()

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

            cardboard_width_mm = float(self.slats_cam_cardboard_width_mm.get() or "300.0")
            feed_window_len = float(self.slats_cam_feed_window_mm.get() or "200.0")
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
            self.gantry_width_x_var.set(f"{cardboard_width_mm:.3f}")
            self.feed_window_y_var.set(f"{feed_window_len:.3f}")
            self._rebuild_feed_windows()

            self.slats_cam_status_var.set(f"DXF loaded ({len(sheets)} sheet candidates)")
            self._fit_workspace()

        except Exception as e:
            messagebox.showerror("DXF Error", str(e))
            self.slats_cam_status_var.set("DXF error")

    def _clear_packed(self):
        self.packed_items.clear()
        self.active_packed_slat_id = None
        self._redraw_all_views()

    def _auto_pack_selected(self):
        if self.usable_region_mm is None or self.usable_region_mm.is_empty:
            messagebox.showwarning("Load DXF", "Load cardboard DXF first")
            return

        if not self.selected_slat_ids:
            messagebox.showwarning("No Selection", "Select one or more slats first")
            return

        try:
            selected_ids = sorted(self.selected_slat_ids)
            selected_records = fidxf.get_selected_slats(self.all_slat_records, selected_ids)

            cfg = fidxf.AutoPlaceConfig(
                part_gap=float(self.slats_cam_gap_mm_var.get() or "4.0"),
                search_step_x=getattr(fidxf.AUTO_CFG, "search_step_x", 10.0),
                search_step_y=getattr(fidxf.AUTO_CFG, "search_step_y", 10.0),
                rotations_deg=getattr(fidxf.AUTO_CFG, "rotations_deg", (0.0, 90.0)),
                sort_largest_first=getattr(fidxf.AUTO_CFG, "sort_largest_first", True),
            )

            placements = fidxf.auto_place_selected_slats(
                selected_records,
                self.usable_region_mm,
                cfg,
            )

            lookup = {record_id(r): r for r in self.all_slat_records}
            self.packed_items.clear()
            self.active_packed_slat_id = None

            packed_count = 0
            failed = 0

            for sid, geom, pose, ok, note in placements:
                rec = lookup.get(sid)
                x, y, rot_deg = pose
                if ok and geom is not None and rec is not None:
                    self.packed_items[sid] = {
                        "rec": rec,
                        "x": x,
                        "y": y,
                        "rot": rot_deg,
                        "geom": geom,
                        "note": note,
                    }
                    packed_count += 1
                else:
                    failed += 1

            if failed:
                self.slats_cam_status_var.set(f"Packed {packed_count} slats, {failed} skipped")
            else:
                self.slats_cam_status_var.set(f"Packed {packed_count} slats")

            self._fit_workspace()

        except Exception as e:
            messagebox.showerror("Auto-Pack Error", str(e))
            self.slats_cam_status_var.set("Auto-pack error")


    def _insert_selected_slats(self):
        if self.usable_region_mm is None or self.usable_region_mm.is_empty:
            messagebox.showwarning("Load DXF", "Load cardboard DXF first")
            return

        if not self.selected_slat_ids:
            messagebox.showwarning("No Selection", "Select one or more slats first")
            return

        try:
            # Only insert slats not already packed
            lookup = {record_id(r): r for r in self.all_slat_records}
            candidate_ids = [sid for sid in sorted(self.selected_slat_ids) if sid not in self.packed_items]
            if not candidate_ids:
                self.slats_cam_status_var.set("Selected slats already packed")
                return

            selected_records = fidxf.get_selected_slats(self.all_slat_records, candidate_ids)

            gap = float(self.slats_cam_gap_mm_var.get() or "4.0")
            available_region = self.usable_region_mm

            occupied = []
            for item in self.packed_items.values():
                g = item.get("geom")
                if g is None or g.is_empty:
                    continue
                try:
                    occupied.append(g.buffer(gap))
                except Exception:
                    occupied.append(g)

            if occupied:
                try:
                    available_region = self.usable_region_mm.difference(unary_union(occupied))
                except Exception:
                    pass

            cfg = fidxf.AutoPlaceConfig(
                part_gap=gap,
                search_step_x=getattr(fidxf.AUTO_CFG, "search_step_x", 10.0),
                search_step_y=getattr(fidxf.AUTO_CFG, "search_step_y", 10.0),
                rotations_deg=getattr(fidxf.AUTO_CFG, "rotations_deg", (0.0, 90.0)),
                sort_largest_first=getattr(fidxf.AUTO_CFG, "sort_largest_first", True),
            )

            placements = fidxf.auto_place_selected_slats(
                selected_records,
                available_region,
                cfg,
            )

            inserted = 0
            skipped = 0
            for sid, geom, pose, ok, note in placements:
                rec = lookup.get(sid)
                x, y, rot_deg = pose
                if ok and geom is not None and rec is not None:
                    self.packed_items[sid] = {
                        "rec": rec,
                        "x": x,
                        "y": y,
                        "rot": rot_deg,
                        "geom": geom,
                        "note": note,
                    }
                    inserted += 1
                else:
                    skipped += 1

            self.active_packed_slat_id = None
            if inserted and skipped:
                self.slats_cam_status_var.set(f"Inserted {inserted} slats, {skipped} skipped")
            elif inserted:
                self.slats_cam_status_var.set(f"Inserted {inserted} slats")
            else:
                self.slats_cam_status_var.set("No room to insert selected slats")

            self._redraw_all_views()

        except Exception as e:
            messagebox.showerror("Insert Selected Error", str(e))
            self.slats_cam_status_var.set("Insert selected error")

    # =====================================================
    # WINDOW / GEOMETRY HELPERS
    # =====================================================
    def _window_utilization_stats(self, window=None):
        if window is None:
            window = self._active_window()
        if window is None:
            return {
                "packed_area": 0.0,
                "usable_area": 0.0,
                "ratio": 0.0,
                "part_count": 0,
            }

        rect = self._window_rect_material(window)

        usable_area = 0.0
        if self.usable_region_mm is not None and not self.usable_region_mm.is_empty:
            try:
                usable_area = self.usable_region_mm.intersection(rect).area
            except Exception:
                usable_area = 0.0

        packed_geoms = []
        part_count = 0
        for item in self.packed_items.values():
            g = item.get("geom")
            if g is None or g.is_empty:
                continue
            try:
                gc = g.intersection(rect)
            except Exception:
                continue
            if gc is not None and not gc.is_empty:
                packed_geoms.append(gc)
                part_count += 1

        packed_area = 0.0
        if packed_geoms:
            try:
                packed_area = unary_union(packed_geoms).area
            except Exception:
                packed_area = sum(g.area for g in packed_geoms)

        ratio = (packed_area / usable_area) if usable_area > 1e-9 else 0.0
        return {
            "packed_area": packed_area,
            "usable_area": usable_area,
            "ratio": max(0.0, min(1.0, ratio)),
            "part_count": part_count,
        }

    def _update_window_info(self):
        if not self.feed_windows:
            self.window_info_var.set("Window: none")
            return

        idx, x0, x1 = self.feed_windows[self.active_window_index]
        stats = self._window_utilization_stats(self.feed_windows[self.active_window_index])
        self.window_info_var.set(
            f"Window {idx + 1}/{len(self.feed_windows)}   x=[{x0:.1f}, {x1:.1f}] mm   "
            f"util {stats['ratio'] * 100:.0f}%   parts {stats['part_count']}"
        )

    def _prev_window(self):
        if not self.feed_windows:
            return
        self.active_window_index = max(0, self.active_window_index - 1)
        self._update_window_info()
        self._redraw_all_views()

    def _next_window(self):
        if not self.feed_windows:
            return
        self.active_window_index = min(len(self.feed_windows) - 1, self.active_window_index + 1)
        self._update_window_info()
        self._redraw_all_views()

    def _active_window(self):
        if not self.feed_windows:
            return None
        if not (0 <= self.active_window_index < len(self.feed_windows)):
            self.active_window_index = 0
        return self.feed_windows[self.active_window_index]

    def _sheet_y_bounds(self):
        if self.sheet_mm is not None and not self.sheet_mm.is_empty:
            _, miny, _, maxy = self.sheet_mm.bounds
            return miny, maxy
        _, miny, _, maxy = self._world_bounds()
        return miny, maxy

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

        if self.sheet_mm is not None and not self.sheet_mm.is_empty:
            sheet_clip = self._clip_geom_to_window(self.sheet_mm, window)
            out["sheet"] = self._material_to_machine_geom(sheet_clip, window)

        for h in self.holes_mm:
            h_clip = self._clip_geom_to_window(h, window)
            h_local = self._material_to_machine_geom(h_clip, window)
            if h_local is not None and not h_local.is_empty:
                out["holes"].append(h_local)

        if self.usable_region_mm is not None and not self.usable_region_mm.is_empty:
            usable_clip = self._clip_geom_to_window(self.usable_region_mm, window)
            out["usable"] = self._material_to_machine_geom(usable_clip, window)

        for sid, item in self.packed_items.items():
            g_clip = self._clip_geom_to_window(item["geom"], window)
            g_local = self._material_to_machine_geom(g_clip, window)
            if g_local is not None and not g_local.is_empty:
                out["packed"].append((sid, g_local))

        return out

    # =====================================================
    # WORKSPACE VIEW
    # =====================================================
    def _world_bounds(self):
        geoms = []

        if self.sheet_mm is not None and not self.sheet_mm.is_empty:
            geoms.append(self.sheet_mm)

        for h in self.holes_mm:
            if h is not None and not h.is_empty:
                geoms.append(h)

        for item in self.packed_items.values():
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

        gantry_w = float(self.gantry_width_x_var.get() or self.slats_cam_cardboard_width_mm.get() or "300.0")
        gantry_h = float(self.feed_window_y_var.get() or self.slats_cam_feed_window_mm.get() or "200.0")
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
        if not self.feed_windows:
            return

        c = self.workspace_canvas
        miny, maxy = self._sheet_y_bounds()

        for j, (idx, x0, x1) in enumerate(self.feed_windows):
            active = j == self.active_window_index
            color = "#FFD54A" if active else "#4A7BFF"
            width = 3 if active else 2

            # left and right bounds of each window
            for edge_x in (x0, x1):
                cx0, cy0 = to_canvas(edge_x, miny)
                cx1, cy1 = to_canvas(edge_x, maxy)
                c.create_line(cx0, cy0, cx1, cy1, fill=color, dash=(6, 4), width=width)

            # draggable interior boundary handle at the right edge of each window,
            # except for the final window edge.
            if j < len(self.feed_windows) - 1:
                handle_active = self.drag_boundary_index == j
                handle_color = "#FF8844" if handle_active else color
                hx, hy0 = to_canvas(x1, miny)
                _hx, hy1 = to_canvas(x1, maxy)
                hy_mid = 0.5 * (hy0 + hy1)
                c.create_oval(
                    hx - 7, hy_mid - 7, hx + 7, hy_mid + 7,
                    outline=handle_color, fill="#111111", width=2,
                    tags=("feed_handle", f"feed_handle:{j}"),
                )

            midx = 0.5 * (x0 + x1)
            lx, ly = to_canvas(midx, maxy + 34.0)
            stats = self._window_utilization_stats((idx, x0, x1))
            c.create_text(
                lx,
                ly,
                text=f"Window {idx}",
                fill=color,
                anchor="n",
                font=("Arial", 10, "bold"),
            )
            c.create_text(
                lx,
                ly + 14,
                text=f"{stats['ratio'] * 100:.0f}% used • {stats['part_count']} parts",
                fill="#BBD0FF" if not active else "#FFE7A0",
                anchor="n",
                font=("Arial", 8, "bold"),
            )

        c.create_text(
            12,
            12,
            anchor="nw",
            text="Drag dashed roll boundaries/handles to adjust feed windows",
            fill="#BBBBBB",
            font=("Arial", 10, "bold"),
        )

    def _redraw_workspace(self):
        c = self.workspace_canvas
        c.delete("all")
        c.update_idletasks()

        w = max(c.winfo_width(), 400)
        h = max(c.winfo_height(), 300)
        to_canvas, _, _ = self._overview_view_transform()

        c.create_line(0, h / 2, w, h / 2, fill="#223322", dash=(3, 4))
        c.create_line(w / 2, 0, w / 2, h, fill="#223322", dash=(3, 4))

        if self.sheet_mm is not None and not self.sheet_mm.is_empty:
            self._draw_geom_on_canvas(c, self.sheet_mm, to_canvas, outline="#00FF99", fill="#0C4410", width=2, tags=("sheet",))

        for hgeom in self.holes_mm:
            self._draw_geom_on_canvas(c, hgeom, to_canvas, outline="#00FF99", fill="#050505", width=2, tags=("hole",))

        if self.usable_region_mm is not None and not self.usable_region_mm.is_empty:
            self._draw_geom_on_canvas(c, self.usable_region_mm, to_canvas, outline="#335533", fill="", width=1, tags=("usable",))

        self._draw_feed_windows_on_workspace(to_canvas)

        for sid, item in self.packed_items.items():
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

        if self.sheet_mm is None and not self.packed_items:
            c.create_text(w / 2, h / 2, text="Load DXF and pack slats", fill="#999999", font=("Arial", 12))

    def _redraw_window_preview(self):
        c = self.window_canvas
        c.delete("all")
        c.update_idletasks()

        w = max(c.winfo_width(), 400)
        h = max(c.winfo_height(), 250)

        if not self.feed_windows:
            c.create_text(w / 2, h / 2, text="Load DXF to preview feed windows", fill="#999999", font=("Arial", 12))
            return

        to_canvas, _ = self._window_view_transform()
        preview = self._window_preview_geoms()

        # axes in gantry/machine coordinates
        ax0, ay0 = to_canvas(-10000, 0.0)
        ax1, ay1 = to_canvas(10000, 0.0)
        c.create_line(ax0, ay0, ax1, ay1, fill="#355535", dash=(3, 4))
        ax0, ay0 = to_canvas(0.0, -10000)
        ax1, ay1 = to_canvas(0.0, 10000)
        c.create_line(ax0, ay0, ax1, ay1, fill="#355535", dash=(3, 4))

        # gantry boundary rectangle in machine coordinates
        gantry_w = float(self.gantry_width_x_var.get() or self.slats_cam_cardboard_width_mm.get() or "300.0")
        gantry_h = float(self.feed_window_y_var.get() or self.slats_cam_feed_window_mm.get() or "200.0")
        gx0, gy0 = to_canvas(-gantry_w / 2.0, -gantry_h / 2.0)
        gx1, gy1 = to_canvas(gantry_w / 2.0, gantry_h / 2.0)
        c.create_rectangle(gx0, gy1, gx1, gy0, outline="#4A7BFF", width=2)

        if preview["sheet"] is not None:
            self._draw_geom_on_canvas(c, preview["sheet"], to_canvas, outline="#00FF99", fill="#0C4410", width=2)

        for hgeom in preview["holes"]:
            self._draw_geom_on_canvas(c, hgeom, to_canvas, outline="#00FF99", fill="#050505", width=2)

        if preview["usable"] is not None:
            self._draw_geom_on_canvas(c, preview["usable"], to_canvas, outline="#335533", fill="", width=1)

        for sid, geom in preview["packed"]:
            active = sid == self.active_packed_slat_id
            outline = "#FFD54A" if active else "#66CCFF"
            fill = "#334455" if active else "#1B2730"
            self._draw_geom_on_canvas(c, geom, to_canvas, outline=outline, fill=fill, width=2 if active else 1)

        stats = self._window_utilization_stats()
        c.create_text(
            12,
            12,
            anchor="nw",
            text=(
                "Machine frame: X = cardboard width, Y = feed direction"
                f"   |   utilization {stats['ratio'] * 100:.0f}%"
                f"   |   parts in window {stats['part_count']}"
            ),
            fill="#BBBBBB",
            font=("Arial", 10, "bold"),
        )

    def _redraw_all_views(self):
        self._update_window_info()
        self._redraw_workspace()
        self._redraw_window_preview()

    # =====================================================
    # WORKSPACE INTERACTION
    # =====================================================
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

            dist = min(abs(canvas_x - hx), ((canvas_x - hx) ** 2 + (canvas_y - hy_mid) ** 2) ** 0.5)
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

        # A window may be shorter than the gantry feed length, but never longer.
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

    def _on_workspace_click(self, event):
        boundary_index = self._pick_feed_boundary(event.x, event.y)
        if boundary_index is not None:
            self.drag_boundary_index = boundary_index
            self.drag_item_id = None
            self.drag_last_xy = (event.x, event.y)
            self.drag_original_pose = None
            self._redraw_all_views()
            return

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
        if self.drag_boundary_index is not None:
            _, to_world, _ = self._overview_view_transform()
            wx1, _wy1 = to_world(event.x, event.y)
            self._move_feed_boundary(self.drag_boundary_index, wx1)
            self.drag_last_xy = (event.x, event.y)
            self._redraw_all_views()
            return

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

        if candidate is not None and not candidate.is_empty:
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
            if allowed and self.usable_region_mm is not None and not self.usable_region_mm.is_empty:
                try:
                    allowed = candidate.buffer(1e-6).within(self.usable_region_mm)
                except Exception:
                    allowed = False

            if allowed:
                gap = float(self.slats_cam_gap_mm_var.get() or "4.0")
                for other_sid, other in self.packed_items.items():
                    if other_sid == sid:
                        continue
                    other_geom = other.get("geom")
                    if other_geom is None or other_geom.is_empty:
                        continue
                    try:
                        if candidate.buffer(gap).intersects(other_geom):
                            allowed = False
                            break
                    except Exception:
                        pass

            if not allowed and getattr(self, "drag_original_pose", None) is not None:
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

    def _rotate_active(self, delta_deg):
        sid = self.active_packed_slat_id
        if not sid or sid not in self.packed_items:
            return

        item = self.packed_items[sid]
        new_rot = item["rot"] + delta_deg
        candidate = place_geom(record_geom(item["rec"]), item["x"], item["y"], new_rot)

        allowed = candidate is not None and not candidate.is_empty
        if allowed and self.usable_region_mm is not None and not self.usable_region_mm.is_empty:
            try:
                allowed = candidate.buffer(1e-6).within(self.usable_region_mm)
            except Exception:
                allowed = False

        if allowed:
            gap = float(self.slats_cam_gap_mm_var.get() or "4.0")
            for other_sid, other in self.packed_items.items():
                if other_sid == sid:
                    continue
                other_geom = other.get("geom")
                if other_geom is None or other_geom.is_empty:
                    continue
                try:
                    if candidate.buffer(gap).intersects(other_geom):
                        allowed = False
                        break
                except Exception:
                    pass

        if allowed:
            item["rot"] = new_rot
            item["geom"] = candidate
        self._redraw_all_views()

    def _on_workspace_pan_start(self, event):
        self._pan_start = (event.x, event.y)

    def _on_workspace_pan_move(self, event):
        if self._pan_start is None:
            return

        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        self.workspace_pan_x += dx
        self.workspace_pan_y += dy
        self._pan_start = (event.x, event.y)
        self._redraw_all_views()

    def _on_workspace_mousewheel(self, event):
        if event.delta > 0:
            self._zoom_workspace(1.1)
        else:
            self._zoom_workspace(0.9)

    # =====================================================
    # GCODE HANDOFF
    # =====================================================
    def _generate_gcode_stub(self):
        if not self.packed_items:
            messagebox.showwarning("No layout", "Pack at least one slat first")
            return

        if not self.feed_windows:
            messagebox.showwarning("No windows", "Load DXF first so feed windows can be built")
            return

        try:
            from slat_toolpaths import geometry_to_knife_segments, chain_segments
            from gcode.emit_gcode import emit_gcode
            from gcode.machine_ops_types import RapidMove, ToolDown, ToolUp, CutPath

            def build_single_window_ops(toolpaths):
                ops = []
                for path in toolpaths.get("knife", []):
                    if not path or len(path) < 2:
                        continue
                    ops.append(RapidMove(to=path[0]))
                    ops.append(ToolDown(tool="knife"))
                    ops.append(CutPath(path=path))
                    ops.append(ToolUp())

                for path in toolpaths.get("crease", []):
                    if not path or len(path) < 2:
                        continue
                    ops.append(RapidMove(to=path[0]))
                    ops.append(ToolDown(tool="crease"))
                    ops.append(CutPath(path=path))
                    ops.append(ToolUp())
                return ops

            feed_window_y = float(self.feed_window_y_var.get() or self.slats_cam_feed_window_mm.get() or "200.0")
            combined_chunks = []
            exported = 0

            for window in self.feed_windows:
                idx, x0, x1 = window
                machine_geoms = []
                for item in self.packed_items.values():
                    g_clip = self._clip_geom_to_window(item["geom"], window)
                    g_local = self._material_to_machine_geom(g_clip, window)
                    if g_local is not None and not g_local.is_empty:
                        machine_geoms.append(g_local)

                if not machine_geoms:
                    combined_chunks.append(f"; --- WINDOW {idx}: EMPTY x=[{x0:.3f}, {x1:.3f}] ---\n")
                    continue

                knife_segments = []
                for geom in machine_geoms:
                    knife_segments.extend(geometry_to_knife_segments(geom))

                knife_paths = chain_segments(knife_segments)
                if not knife_paths:
                    combined_chunks.append(f"; --- WINDOW {idx}: NO PATHS x=[{x0:.3f}, {x1:.3f}] ---\n")
                    continue

                toolpaths = {"knife": knife_paths, "crease": []}
                ops = build_single_window_ops(toolpaths)
                window_gcode = emit_gcode(ops, feed_window_y=feed_window_y)
                combined_chunks.append(f"; --- WINDOW {idx} START x=[{x0:.3f}, {x1:.3f}] ---\n")
                combined_chunks.append(window_gcode)
                combined_chunks.append(f"\n; --- ROLL FEED AFTER WINDOW {idx} ---\n\n")
                exported += 1

            if exported == 0:
                messagebox.showwarning("No output", "No non-empty feed windows were found for G-code export")
                return

            gcode = "".join(combined_chunks)
            out = filedialog.asksaveasfilename(
                title="Save G-code",
                defaultextension=".nc",
                filetypes=[("NC files", "*.nc"), ("G-code files", "*.gcode"), ("All files", "*.*")],
            )
            if out:
                Path(out).write_text(gcode)
                messagebox.showinfo("Done", f"Wrote G-code with {exported} populated windows:\n{out}")

        except Exception as e:
            messagebox.showinfo(
                "Layout Ready",
                "Overview/window planning is ready.\n\n"
                "G-code export failed in this environment.\n\n"
                f"Reason:\n{e}"
            )



def main():
    app = SlatsCamOnlyApp()
    try:
        app.protocol("WM_DELETE_WINDOW", app.on_close)
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
