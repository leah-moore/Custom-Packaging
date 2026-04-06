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

    # =====================================================
    # TOP CONTROLS
    # =====================================================
    top = tk.LabelFrame(
        main,
        text="Vision + DXF Controls",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    top.pack(fill="x", pady=(0, 6))

    btn_row = tk.Frame(top, bg=PANEL_BG)
    btn_row.pack(fill="x")

    tk.Button(
        btn_row,
        text="Start Camera",
        command=app._start_live_camera,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=(0, 4), pady=2)

    tk.Button(
        btn_row,
        text="Stop Camera",
        command=app._stop_live_camera,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        btn_row,
        text="Load DXF",
        command=app._load_dxf_file,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        btn_row,
        text="Run DXF Vision",
        command=app._run_dxf_vision_pipeline,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    app.vision_dxf_status_var = tk.StringVar(value="Idle")
    tk.Label(
        btn_row,
        textvariable=app.vision_dxf_status_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=status_font,
        anchor="e",
    ).pack(side="right", padx=8)

    # =====================================================
    # VIEW MODE + DXF TOOLS
    # =====================================================
    tools = tk.LabelFrame(
        main,
        text="DXF View Tools",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    tools.pack(fill="x", pady=(0, 6))

    tools_row = tk.Frame(tools, bg=PANEL_BG)
    tools_row.pack(fill="x")

    if not hasattr(app, "vision_dxf_view_mode"):
        app.vision_dxf_view_mode = tk.StringVar(value="split")

    app._vision_dxf_view_buttons = {}

    def refresh_view_mode_buttons() -> None:
        current = app.vision_dxf_view_mode.get()
        for mode, btn in app._vision_dxf_view_buttons.items():
            if mode == current:
                btn.config(bg=BTN_BLUE, fg=BTN_BLUE_FG)
            else:
                btn.config(bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG)

    def refresh_layout() -> None:
        for child in app.vision_dxf_content.winfo_children():
            child.pack_forget()

        mode = app.vision_dxf_view_mode.get()

        if mode == "camera":
            app.vision_camera_panel.pack(fill="both", expand=True)
        elif mode == "dxf":
            app.vision_dxf_panel.pack(fill="both", expand=True)
        else:
            app.vision_camera_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
            app.vision_dxf_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))

    def set_view_mode(mode: str) -> None:
        app.vision_dxf_view_mode.set(mode)
        refresh_view_mode_buttons()
        refresh_layout()

        app.update_idletasks()

        if hasattr(app, "camera_preview_canvas"):
            app.camera_preview_canvas.update_idletasks()

        if hasattr(app, "dxf_preview_canvas"):
            app.dxf_preview_canvas.update_idletasks()

        app.after(10, lambda: hasattr(app, "_draw_dxf_preview") and app._draw_dxf_preview())

    tk.Label(
        tools_row,
        text="View:",
        bg=PANEL_BG,
        fg=FG,
        font=small_font,
    ).pack(side="left", padx=(0, 6))

    def make_mode_button(text: str, mode: str):
        btn = tk.Button(
            tools_row,
            text=text,
            command=lambda m=mode: set_view_mode(m),
            bg=BTN_NEUTRAL,
            fg=BTN_NEUTRAL_FG,
            activebackground=BTN_PRESSED,
            activeforeground="#000000",
            font=small_font,
            width=11,
            bd=2,
            relief="raised",
            pady=1,
        )
        btn.pack(side="left", padx=(0, 4), pady=2)
        app._vision_dxf_view_buttons[mode] = btn

    make_mode_button("Split", "split")
    make_mode_button("Camera Only", "camera")
    make_mode_button("DXF Only", "dxf")

    tk.Frame(tools_row, bg=PANEL_BG, width=18).pack(side="left")

    tk.Button(
        tools_row,
        text="Rotate -5°",
        command=lambda: app._rotate_dxf(-5.0),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Rotate +5°",
        command=lambda: app._rotate_dxf(5.0),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Frame(tools_row, bg=PANEL_BG, width=18).pack(side="left")

    tk.Button(
        tools_row,
        text="Zoom -",
        command=lambda: app._zoom_dxf(0.8),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Zoom +",
        command=lambda: app._zoom_dxf(1.25),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Fit",
        command=app._dxf_fit_view,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(12, 4), pady=2)

    tk.Button(
        tools_row,
        text="Reset",
        command=app._reset_dxf_view,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    # =====================================================
    # MAIN VIEW AREA
    # =====================================================
    app.vision_dxf_content = tk.Frame(main, bg=BG)
    app.vision_dxf_content.pack(fill="both", expand=True)

    # LEFT: LIVE CAMERA
    app.vision_camera_panel = tk.LabelFrame(
        app.vision_dxf_content,
        text="Live Camera View",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )

    app.camera_preview_canvas = tk.Canvas(
        app.vision_camera_panel,
        bg="#111111",
        highlightthickness=0,
    )
    app.camera_preview_canvas.pack(fill="both", expand=True, padx=2, pady=2)

    app.camera_info_var = tk.StringVar(value="Camera idle")
    tk.Label(
        app.vision_camera_panel,
        textvariable=app.camera_info_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    # RIGHT: DXF PREVIEW
    app.vision_dxf_panel = tk.LabelFrame(
        app.vision_dxf_content,
        text="DXF Preview",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )

    app.dxf_preview_canvas = tk.Canvas(
        app.vision_dxf_panel,
        bg="#111111",
        highlightthickness=0,
    )
    app.dxf_preview_canvas.pack(fill="both", expand=True, padx=2, pady=2)

    app.dxf_preview_canvas.bind("<Configure>", lambda _e: app._draw_dxf_preview())
    app.dxf_preview_canvas.bind("<MouseWheel>", app._on_dxf_mousewheel)
    app.dxf_preview_canvas.bind("<Button-4>", app._on_dxf_mousewheel)
    app.dxf_preview_canvas.bind("<Button-5>", app._on_dxf_mousewheel)

    app.dxf_info_text = tk.StringVar(value="No DXF loaded")
    tk.Label(
        app.vision_dxf_panel,
        textvariable=app.dxf_info_text,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    refresh_view_mode_buttons()
    refresh_layout()

    # =====================================================
    # BOTTOM STATUS / RESULTS
    # =====================================================
    bottom = tk.LabelFrame(
        main,
        text="Vision Run Status",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    bottom.pack(fill="x", pady=(6, 0))

    app.vision_result_var = tk.StringVar(value="No run yet")
    tk.Label(
        bottom,
        textvariable=app.vision_result_var,
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x")