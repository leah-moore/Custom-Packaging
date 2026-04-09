import tkinter as tk

from ..theme import (
    BG,
    PANEL_BG,
    FG,
    BTN_NEUTRAL,
    BTN_NEUTRAL_FG,
    BTN_BLUE,
    BTN_BLUE_FG,
    BTN_GREEN,
    BTN_GREEN_FG,
    BTN_RED,
    BTN_RED_FG,
    BTN_PRESSED,
)


def build_vision_dxf_tab(app, parent) -> None:
    default_font = ("Arial", 8, "bold")
    title_font = ("Arial", 9, "bold")
    status_font = ("Arial", 10, "bold")
    small_font = ("Arial", 8, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=4, pady=4)

    if not hasattr(app, "vision_status_var"):
        app.vision_status_var = tk.StringVar(value="Idle")
    if not hasattr(app, "vision_process_var"):
        app.vision_process_var = tk.StringVar(value="No scan yet")
    if not hasattr(app, "vision_result_var"):
        app.vision_result_var = tk.StringVar(value="No run yet")
    if not hasattr(app, "stitched_info_var"):
        app.stitched_info_var = tk.StringVar(value="No stitched image")
    if not hasattr(app, "generated_dxf_var"):
        app.generated_dxf_var = tk.StringVar(value="No generated DXF")
    if not hasattr(app, "camera_info_var"):
        app.camera_info_var = tk.StringVar(value="Camera idle")
    if not hasattr(app, "dxf_info_text"):
        app.dxf_info_text = tk.StringVar(value="No DXF loaded")
    if not hasattr(app, "vision_dxf_status_var"):
        app.vision_dxf_status_var = tk.StringVar(value="Idle")
    if not hasattr(app, "vision_dxf_view_mode"):
        app.vision_dxf_view_mode = tk.StringVar(value="split")
    if not hasattr(app, "_vision_dxf_view_buttons"):
        app._vision_dxf_view_buttons = {}

    # =====================================================
    # SINGLE TOP PANEL: BUTTONS + STATUS
    # =====================================================
    top = tk.LabelFrame(
        main,
        text="Vision Controls",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    top.pack(fill="x", pady=(0, 6))

    row = tk.Frame(top, bg=PANEL_BG)
    row.pack(fill="x")

    # CAMERA FIRST
    tk.Button(
        row,
        text="Start Camera",
        command=app._start_live_camera,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        font=default_font,
        width=11,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=(0, 4), pady=2)

    tk.Button(
        row,
        text="Stop Camera",
        command=app._stop_live_camera,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    # THEN SCAN
    tk.Button(
        row,
        text="Start Scan",
        command=app._start_vision_scan,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        row,
        text="Stop Scan",
        command=app._stop_vision_scan,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        row,
        text="Load DXF",
        command=app._load_dxf_file,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=9,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Frame(row, bg=PANEL_BG).pack(side="left", fill="x", expand=True)

    tk.Label(
        row,
        text="View:",
        bg=PANEL_BG,
        fg=FG,
        font=small_font,
    ).pack(side="left", padx=(6, 4))

    def refresh_view_mode_buttons():
        current = app.vision_dxf_view_mode.get()
        for mode, btn in app._vision_dxf_view_buttons.items():
            if mode == current:
                btn.config(bg=BTN_BLUE, fg=BTN_BLUE_FG)
            else:
                btn.config(bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG)

    def refresh_layout():
        for child in app.vision_dxf_content.winfo_children():
            child.pack_forget()

        mode = app.vision_dxf_view_mode.get()

        if mode == "camera":
            app.camera_view_panel.pack(fill="both", expand=True)
        elif mode == "dxf":
            app.dxf_stitch_panel.pack(fill="both", expand=True)
        else:
            app.camera_view_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
            app.dxf_stitch_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))

    def set_view_mode(mode: str):
        app.vision_dxf_view_mode.set(mode)
        refresh_view_mode_buttons()
        refresh_layout()
        app.update_idletasks()

        if getattr(app, "dxf_preview_canvas", None) is not None:
            app.after(10, app._draw_dxf_preview)
        if getattr(app, "_stitched_image", None) is not None and hasattr(app, "_update_stitched_canvas"):
            app.after(10, app._update_stitched_canvas)
        if getattr(app, "_camera_frame", None) is not None and hasattr(app, "_update_camera_canvas"):
            app.after(10, app._update_camera_canvas)

    def make_mode_button(text: str, mode: str, width: int):
        btn = tk.Button(
            row,
            text=text,
            command=lambda m=mode: set_view_mode(m),
            bg=BTN_NEUTRAL,
            fg=BTN_NEUTRAL_FG,
            activebackground=BTN_PRESSED,
            activeforeground="#000000",
            font=small_font,
            width=width,
            bd=2,
            relief="raised",
            pady=1,
        )
        btn.pack(side="left", padx=(0, 4), pady=2)
        app._vision_dxf_view_buttons[mode] = btn

    make_mode_button("Split", "split", 8)
    make_mode_button("Camera", "camera", 8)
    make_mode_button("DXF/Stitch", "dxf", 10)

    tk.Label(
        row,
        textvariable=app.vision_status_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=status_font,
        anchor="e",
        width=12,
    ).pack(side="right", padx=(8, 0))

    # =====================================================
    # CONTENT AREA
    # =====================================================
    app.vision_dxf_content = tk.Frame(main, bg=BG)
    app.vision_dxf_content.pack(fill="both", expand=True)

    def make_panel(parent_, title):
        return tk.LabelFrame(
            parent_,
            text=title,
            bg=PANEL_BG,
            fg=FG,
            font=title_font,
            padx=4,
            pady=4,
            bd=2,
            relief="solid",
        )

    # LEFT SIDE: STITCHED + DXF
    app.dxf_stitch_panel = tk.Frame(app.vision_dxf_content, bg=BG)
    app.dxf_stitch_panel.grid_columnconfigure(0, weight=1)
    app.dxf_stitch_panel.grid_columnconfigure(1, weight=1)
    app.dxf_stitch_panel.grid_rowconfigure(0, weight=1)

    stitched_panel = make_panel(app.dxf_stitch_panel, "Stitched Image")
    stitched_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 3))

    app.stitched_preview_canvas = tk.Canvas(
        stitched_panel,
        bg="#111111",
        highlightthickness=0,
    )
    app.stitched_preview_canvas.pack(fill="both", expand=True, padx=2, pady=2)

    tk.Label(
        stitched_panel,
        textvariable=app.stitched_info_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    dxf_panel = make_panel(app.dxf_stitch_panel, "DXF")
    dxf_panel.grid(row=0, column=1, sticky="nsew", padx=(3, 0))

    app.dxf_preview_canvas = tk.Canvas(
        dxf_panel,
        bg="#111111",
        highlightthickness=0,
    )
    app.dxf_preview_canvas.pack(fill="both", expand=True, padx=2, pady=2)

    app.dxf_preview_canvas.bind("<Configure>", lambda _e: app._draw_dxf_preview())
    app.dxf_preview_canvas.bind("<MouseWheel>", app._on_dxf_mousewheel)
    app.dxf_preview_canvas.bind("<Button-4>", app._on_dxf_mousewheel)
    app.dxf_preview_canvas.bind("<Button-5>", app._on_dxf_mousewheel)
    app.dxf_preview_canvas.bind("<ButtonPress-1>", app._on_dxf_pan_start)
    app.dxf_preview_canvas.bind("<B1-Motion>", app._on_dxf_pan_move)
    app.dxf_preview_canvas.bind("<ButtonRelease-1>", app._on_dxf_pan_end)

    tk.Label(
        dxf_panel,
        textvariable=app.dxf_info_text,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    # RIGHT SIDE: CAMERA + STATUS
    app.camera_view_panel = tk.Frame(app.vision_dxf_content, bg=BG)
    app.camera_view_panel.grid_columnconfigure(0, weight=3)
    app.camera_view_panel.grid_columnconfigure(1, weight=2)
    app.camera_view_panel.grid_rowconfigure(0, weight=1)

    camera_panel = make_panel(app.camera_view_panel, "Camera View")
    camera_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 3))

    app.camera_preview_canvas = tk.Canvas(
        camera_panel,
        bg="#111111",
        highlightthickness=0,
    )
    app.camera_preview_canvas.pack(fill="both", expand=True, padx=2, pady=2)

    tk.Label(
        camera_panel,
        textvariable=app.camera_info_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    process_panel = make_panel(app.camera_view_panel, "Process Status")
    process_panel.grid(row=0, column=1, sticky="nsew", padx=(3, 0))

    tk.Label(
        process_panel,
        text="Pipeline Status",
        bg=PANEL_BG,
        fg=FG,
        font=("Arial", 9, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 4))

    tk.Label(
        process_panel,
        textvariable=app.vision_process_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=small_font,
        anchor="nw",
        justify="left",
        wraplength=180,
    ).pack(fill="x", pady=(0, 8))

    tk.Label(
        process_panel,
        text="Generated DXF",
        bg=PANEL_BG,
        fg=FG,
        font=("Arial", 9, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 4))

    tk.Label(
        process_panel,
        textvariable=app.generated_dxf_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=small_font,
        anchor="nw",
        justify="left",
        wraplength=180,
    ).pack(fill="x", pady=(0, 8))

    tk.Label(
        process_panel,
        text="Run Result",
        bg=PANEL_BG,
        fg=FG,
        font=("Arial", 9, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 4))

    tk.Label(
        process_panel,
        textvariable=app.vision_result_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=small_font,
        anchor="nw",
        justify="left",
        wraplength=180,
    ).pack(fill="x", pady=(0, 8))

    refresh_view_mode_buttons()
    refresh_layout()