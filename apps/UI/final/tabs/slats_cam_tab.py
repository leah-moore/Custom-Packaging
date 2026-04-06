import tkinter as tk
from tkinter import ttk

from ..theme import BG, PANEL_BG, FG, BTN_YELLOW

BTN_BLUE = "#4A90E2"
BTN_BLUE_FG = "#000000"
BTN_NEUTRAL = "#DDDDDD"
BTN_NEUTRAL_FG = "#000000"
BTN_ORANGE = "#FFAA33"
BTN_ORANGE_FG = "#000000"
ENTRY_BG = "#FFFFFF"


def _style_combobox(app):
    style = ttk.Style(app)
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


def _init_slats_cam_state(app):
    if getattr(app, "_slats_cam_state_initialized", False):
        return

    app._slats_cam_state_initialized = True
    app.slats_cam_view_var = tk.StringVar(value="overview")

    # real slats_cam_only names
    app.slats_cam_stl_path = None
    app.slats_cam_dxf_path = None

    # keep your newer naming too
    app.slats_cam_mesh_path = None

    app.all_slat_records = []
    app.selected_slat_ids = set()
    app.packed_items = {}
    app.active_packed_slat_id = None

    app.sheet_raw = None
    app.holes_raw = []
    app.sheet_mm = None
    app.holes_mm = []
    app.usable_region_mm = None
    app.feed_windows = []
    app.active_window_index = 0

    app.gantry_width_x_var = tk.StringVar(value="300.0")
    app.feed_window_y_var = tk.StringVar(value="200.0")
    app.cardboard_offset_x_var = tk.StringVar(value="0.0")
    app.cardboard_offset_y_var = tk.StringVar(value="0.0")

    app.workspace_zoom = 1.0
    app.workspace_pan_x = 0.0
    app.workspace_pan_y = 0.0
    app.drag_item_id = None
    app.drag_last_xy = None
    app.drag_original_pose = None
    app.drag_boundary_index = None
    app._pan_start = None

    app.window_zoom = 1.0
    app.window_pan_x = 0.0
    app.window_pan_y = 0.0

    app.library_tile_map = {}
    app.library_canvas_container = None
    app.library_inner = None
    app.library_window = None

    if not hasattr(app, "slats_cam_slats_info_var"):
        app.slats_cam_slats_info_var = tk.StringVar(value="No slats loaded")
    else:
        app.slats_cam_slats_info_var.set("No slats loaded")

    if not hasattr(app, "slats_cam_status_var"):
        app.slats_cam_status_var = tk.StringVar(value="No cardboard loaded")
    else:
        app.slats_cam_status_var.set("No cardboard loaded")

    app.selected_count_var = tk.StringVar(value="Selected: 0 / 0")
    app.window_info_var = tk.StringVar(value="Window: none")

    app.slats_cam_cardboard_width_mm = tk.StringVar(value="300.0")
    app.slats_cam_edge_margin_mm = tk.StringVar(value="5.0")
    app.slats_cam_cut_clearance_mm = tk.StringVar(value="1.0")
    app.slats_cam_gap_mm_var = tk.StringVar(value="4.0")
    app.slats_cam_feed_window_mm = tk.StringVar(value="200.0")
    app.slats_cam_sheet_index_var = tk.StringVar(value="0")
    app.slats_cam_min_sheet_area_var = tk.StringVar(value="50000.0")

    app.xy_count_var = tk.StringVar(value="5")
    app.xz_count_var = tk.StringVar(value="5")


def _set_initial_viewer_sash(app):
    viewers = getattr(app, "viewers_paned", None)
    if viewers is None:
        return
    try:
        total_h = max(viewers.winfo_height(), 600)
        viewers.sash_place(0, 0, int(total_h * 0.72))
    except Exception:
        pass

def _set_slats_cam_view(app):
    mode = app.slats_cam_view_var.get()

    if mode == "overview":
        if hasattr(app, "overview_frame"):
            app.overview_frame.lift()
    else:
        if hasattr(app, "window_frame"):
            app.window_frame.lift()

    redraw = getattr(app, "_redraw_all_views", None)
    if callable(redraw):
        try:
            redraw()
        except Exception:
            pass

def build_slats_cam_tab(app, parent):
    """
    Full replacement Slats CAM tab UI.

    Important:
    - This file upgrades the tab UI and initializes the richer state.
    - The backing methods still need to exist on app (TouchUI), e.g.
      _generate_slats, _load_dxf, _auto_pack_selected, _clear_packed,
      _insert_selected_slats, _redraw_all_views, _zoom_workspace, etc.
    - For mesh support, the button now prefers app._browse_mesh if present,
      and falls back to app._browse_stl otherwise.
    """
    _init_slats_cam_state(app)
    _style_combobox(app)

    # Clean any old contents if the tab is rebuilt.
    for child in parent.winfo_children():
        child.destroy()

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
        command=getattr(app, "_generate_gcode", getattr(app, "_generate_gcode_stub", lambda: None)),
        bg="#EEEEEE",
        fg="#111111",
        font=("Arial", 14, "bold"),
        height=2,
    ).pack(fill="x")

    # -------------------------
    # TOP STRIP
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

    # Mesh browse callback: prefer OBJ/STL-aware method if present.
    browse_mesh_cmd = getattr(app, "_browse_mesh", None)
    if browse_mesh_cmd is None:
        browse_mesh_cmd = getattr(app, "_browse_stl", lambda: None)

    # row 1: mesh generation
    row1 = tk.Frame(setup_frame, bg=PANEL_BG)
    row1.pack(fill="x", pady=2)

    tk.Button(
        row1,
        text="Browse Mesh",
        command=browse_mesh_cmd,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
        width=12,
    ).pack(side="left", padx=(0, 10))

    tk.Label(row1, text="XY Slats:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(4, 4))
    app.xy_combo = ttk.Combobox(
        row1,
        textvariable=app.xy_count_var,
        values=[str(i) for i in range(2, 11)],
        state="readonly",
        width=4,
        style="Slats.TCombobox",
    )
    app.xy_combo.pack(side="left", padx=(0, 10))

    tk.Label(row1, text="XZ Slats:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(4, 4))
    app.xz_combo = ttk.Combobox(
        row1,
        textvariable=app.xz_count_var,
        values=[str(i) for i in range(2, 11)],
        state="readonly",
        width=4,
        style="Slats.TCombobox",
    )
    app.xz_combo.pack(side="left", padx=(0, 10))

    tk.Button(
        row1,
        text="Generate Slats",
        command=getattr(app, "_generate_slats", lambda: None),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=ui_font,
        width=14,
    ).pack(side="left", padx=(0, 10))

    tk.Frame(row1, bg=PANEL_BG).pack(side="left", fill="x", expand=True)

    tk.Label(
        row1,
        textvariable=app.slats_cam_slats_info_var,
        bg=PANEL_BG,
        fg="#FFD54A",
        font=ui_font,
    ).pack(side="right", padx=(10, 0))

    # row 2: sheet / packing actions
    row2 = tk.Frame(setup_frame, bg=PANEL_BG)
    row2.pack(fill="x", pady=2)

    tk.Button(
        row2,
        text="Load DXF",
        command=getattr(app, "_load_dxf", lambda: None),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
        width=14,
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        row2,
        text="Blank Sheet",
        command=getattr(app, "_use_blank_sheet", lambda: None),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
        width=14,
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        row2,
        text="Auto-Pack Selected",
        command=app._auto_pack_selected,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=ui_font,
        width=14,
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        row2,
        text="Clear Packed",
        command=getattr(app, "_clear_packed", lambda: None),
        bg=BTN_ORANGE,
        fg=BTN_ORANGE_FG,
        font=ui_font,
        width=14,
    ).pack(side="left", padx=(0, 8))

    # row 3: dimensions + status
    row3 = tk.Frame(setup_frame, bg=PANEL_BG)
    row3.pack(fill="x", pady=2)

    for c in range(8):
        row3.grid_columnconfigure(c, weight=0)
    row3.grid_columnconfigure(7, weight=1)

    tk.Label(row3, text="Cardboard W", bg=PANEL_BG, fg=FG, font=ui_font).grid(row=0, column=0, sticky="w", padx=(0, 6))
    tk.Entry(row3, textvariable=app.slats_cam_cardboard_width_mm, width=8).grid(row=0, column=1, sticky="w", padx=(0, 12))

    tk.Label(row3, text="Feed Len", bg=PANEL_BG, fg=FG, font=ui_font).grid(row=0, column=2, sticky="w", padx=(0, 6))
    tk.Entry(row3, textvariable=app.slats_cam_feed_window_mm, width=8).grid(row=0, column=3, sticky="w", padx=(0, 12))

    tk.Label(row3, text="Gap", bg=PANEL_BG, fg=FG, font=ui_font).grid(row=0, column=4, sticky="w", padx=(0, 6))
    tk.Entry(row3, textvariable=app.slats_cam_gap_mm_var, width=5).grid(row=0, column=5, sticky="w", padx=(0, 16))

    tk.Label(row3, text="Status:", bg=PANEL_BG, fg=FG, font=ui_font).grid(row=0, column=6, sticky="w", padx=(0, 6))
    tk.Label(row3, textvariable=app.slats_cam_status_var, bg=PANEL_BG, fg="#FFD54A", font=ui_font).grid(row=0, column=7, sticky="w")

    # row 4: overview + active feed window controls
    row4 = tk.Frame(setup_frame, bg=PANEL_BG)
    row4.pack(fill="x", pady=2)

    # LEFT SIDE: overview / rotate controls
    row4_left = tk.Frame(row4, bg=PANEL_BG)
    row4_left.pack(side="left", fill="x", expand=True)

    tk.Label(row4_left, text="Overview:", bg=PANEL_BG, fg=FG, font=ui_font).pack(side="left", padx=(0, 8))
    tk.Button(row4_left, text="−", command=lambda: getattr(app, "_zoom_workspace", lambda _s: None)(0.9),
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, width=3, font=ui_font).pack(side="left", padx=1)
    tk.Button(row4_left, text="+", command=lambda: getattr(app, "_zoom_workspace", lambda _s: None)(1.1),
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, width=3, font=ui_font).pack(side="left", padx=1)
    
    tk.Button(
        row4_left,
        text="Fit View",
        command=getattr(app, "_fit_workspace", lambda: None),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
        width=10,
    ).pack(side="left", padx=8)

    tk.Button(
        row4_left,
        text="Rotate -90",
        command=lambda: getattr(app, "_rotate_active", lambda _deg: None)(-90),
        bg=BTN_ORANGE,
        fg=BTN_ORANGE_FG,
        font=ui_font,
        width=10,
    ).pack(side="left", padx=8)

    tk.Button(
        row4_left,
        text="Rotate +90",
        command=lambda: getattr(app, "_rotate_active", lambda _deg: None)(90),
        bg=BTN_ORANGE,
        fg=BTN_ORANGE_FG,
        font=ui_font,
        width=10,
    ).pack(side="left", padx=4)

    # RIGHT SIDE: active window controls + info
    row4_right = tk.Frame(row4, bg=PANEL_BG)
    row4_right.pack(side="right", anchor="e", padx=(24, 0))

    window_top = tk.Frame(row4_right, bg=PANEL_BG)
    window_top.pack(anchor="e")

    tk.Label(
        window_top,
        text="Active Window:",
        bg=PANEL_BG,
        fg=FG,
        font=ui_font,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        window_top,
        text="◀ Prev",
        command=getattr(app, "_prev_window", lambda: None),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
        width=9,
    ).pack(side="left", padx=2)

    tk.Button(
        window_top,
        text="Next ▶",
        command=getattr(app, "_next_window", lambda: None),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
        width=9,
    ).pack(side="left", padx=2)

    tk.Label(
        row4_right,
        textvariable=app.window_info_var,
        bg=PANEL_BG,
        fg="#FFD54A",
        font=ui_font,
        justify="right",
        anchor="e",
    ).pack(anchor="e", pady=(4, 0))

    # top-right controls
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

    tk.Button(
        btngrid,
        text="Select All",
        command=getattr(app, "_select_all_slats", lambda: None),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=ui_font,
    ).grid(row=0, column=0, padx=3, pady=3, sticky="ew")

    tk.Button(
        btngrid,
        text="Clear",
        command=getattr(app, "_clear_selection", lambda: None),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
    ).grid(row=0, column=1, padx=3, pady=3, sticky="ew")

    tk.Button(
        btngrid,
        text="Select XY",
        command=lambda: getattr(app, "_select_family", lambda _f: None)("XY"),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
    ).grid(row=1, column=0, padx=3, pady=3, sticky="ew")

    tk.Button(
        btngrid,
        text="Select XZ",
        command=lambda: getattr(app, "_select_family", lambda _f: None)("XZ"),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
    ).grid(row=1, column=1, padx=3, pady=3, sticky="ew")

    tk.Button(
        btngrid,
        text="Select Left",
        command=lambda: getattr(app, "_select_side", lambda _s: None)("left"),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
    ).grid(row=2, column=0, padx=3, pady=3, sticky="ew")

    tk.Button(
        btngrid,
        text="Select Right",
        command=lambda: getattr(app, "_select_side", lambda _s: None)("right"),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=ui_font,
    ).grid(row=2, column=1, padx=3, pady=3, sticky="ew")

    tk.Button(
        btngrid,
        text="Insert Selected",
        command=getattr(app, "_insert_selected_slats", lambda: None),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=ui_font,
    ).grid(row=3, column=0, columnspan=2, padx=3, pady=(6, 3), sticky="ew")

    btnrow3 = tk.Frame(library_ctrl, bg=PANEL_BG)
    btnrow3.pack(fill="x", padx=8, pady=(0, 8))
    tk.Label(
        btnrow3,
        textvariable=app.selected_count_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=small_font,
    ).pack(side="left")

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

    # --- viewer switcher instead of vertical split ---
    view_switch = tk.Frame(left, bg=BG)
    view_switch.pack(fill="x", pady=(0, 6))

    tk.Radiobutton(
        view_switch,
        text="Layout Overview",
        variable=app.slats_cam_view_var,
        value="overview",
        indicatoron=0,
        command=lambda: _set_slats_cam_view(app),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=ui_font,
        width=16,
        padx=10,
        pady=4,
    ).pack(side="left", padx=(0, 6))

    tk.Radiobutton(
        view_switch,
        text="Active Feed Window",
        variable=app.slats_cam_view_var,
        value="window",
        indicatoron=0,
        command=lambda: _set_slats_cam_view(app),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=ui_font,
        width=16,
        padx=10,
        pady=4,
    ).pack(side="left")

    viewer_host = tk.Frame(left, bg=BG)
    viewer_host.pack(fill="both", expand=True)

    overview_frame = tk.LabelFrame(
        viewer_host,
        text="Layout Overview (full cardboard / material coordinates)",
        bg=PANEL_BG,
        fg=FG,
        font=section_font,
        bd=2,
        relief="solid",
    )
    overview_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

    window_frame = tk.LabelFrame(
        viewer_host,
        text="Active Feed Window (machine coordinates)",
        bg=PANEL_BG,
        fg=FG,
        bd=2,
        relief="solid",
    )
    window_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

    app.overview_frame = overview_frame
    app.window_frame = window_frame

    app.workspace_canvas = tk.Canvas(
        overview_frame,
        bg="#050505",
        highlightthickness=0,
        cursor="crosshair",
    )
    app.workspace_canvas.pack(fill="both", expand=True, padx=4, pady=4)
    app.workspace_canvas.bind("<Configure>", lambda e: getattr(app, "_redraw_all_views", lambda: None)())
    app.workspace_canvas.bind("<Button-1>", getattr(app, "_on_workspace_click", lambda e: None))
    app.workspace_canvas.bind("<B1-Motion>", getattr(app, "_on_workspace_drag", lambda e: None))
    app.workspace_canvas.bind("<ButtonRelease-1>", getattr(app, "_on_workspace_release", lambda e: None))
    app.workspace_canvas.bind("<Button-3>", getattr(app, "_on_workspace_pan_start", lambda e: None))
    app.workspace_canvas.bind("<B3-Motion>", getattr(app, "_on_workspace_pan_move", lambda e: None))
    app.workspace_canvas.bind("<MouseWheel>", getattr(app, "_on_workspace_mousewheel", lambda e: None))


    app.window_canvas = tk.Canvas(
        window_frame,
        bg="#090909",
        highlightthickness=0,
        cursor="arrow",
    )
    app.window_canvas.pack(fill="both", expand=True, padx=4, pady=4)
    app.window_canvas.bind("<Configure>", lambda e: getattr(app, "_redraw_all_views", lambda: None)())

    library_host = tk.Frame(right, bg=BG)
    library_host.pack(fill="both", expand=True)

    app.library_canvas_container = tk.Canvas(
        library_host,
        bg="#101010",
        highlightthickness=1,
        highlightbackground="#333333",
    )
    app.library_canvas_container.pack(side="left", fill="both", expand=True)

    library_scrollbar = tk.Scrollbar(
        library_host,
        orient="vertical",
        command=app.library_canvas_container.yview,
    )
    library_scrollbar.pack(side="right", fill="y")
    app.library_canvas_container.configure(yscrollcommand=library_scrollbar.set)

    app.library_inner = tk.Frame(app.library_canvas_container, bg="#101010")
    app.library_window = app.library_canvas_container.create_window((0, 0), window=app.library_inner, anchor="nw")

    app.library_inner.bind("<Configure>", getattr(app, "_on_library_inner_configure", lambda e=None: None))
    app.library_canvas_container.bind("<Configure>", getattr(app, "_on_library_canvas_configure", lambda e: None))
    app.library_canvas_container.bind_all("<MouseWheel>", getattr(app, "_on_library_mousewheel", lambda e: None), add="+")

    # Backward compatibility aliases so older methods don't explode if they
    # still reference the old widget names from the simple tab.
    app.overview_canvas = app.workspace_canvas
    app.feed_canvas = app.window_canvas

    _set_slats_cam_view(app)

    # Build empty/default visuals if app already has helpers.
    redraw = getattr(app, "_redraw_all_views", None)
    if callable(redraw):
        try:
            redraw()
        except Exception:
            pass