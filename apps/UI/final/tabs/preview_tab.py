import tkinter as tk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from ..theme import (
    BG,
    PANEL_BG,
    FG,
    BTN_BLUE,
    BTN_BLUE_FG,
    BTN_GREEN,
    BTN_GREEN_FG,
    BTN_ORANGE,
    BTN_ORANGE_FG,
    BTN_RED,
    BTN_RED_FG,
    BTN_PRESSED,
)


def build_preview_tab(app, parent) -> None:
    title_font = ("Arial", 10, "bold")
    mode_font = ("Arial", 11, "bold")
    control_font = ("Arial", 12, "bold")
    info_font = ("Arial", 12, "bold")
    speed_font = ("Arial", 11, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=0, pady=0)

    # =========================================================
    # STATE
    # =========================================================
    app.preview_mode = tk.StringVar(value="2d")
    app.preview_speed_var = tk.StringVar(value="1.0x")
    app.preview_live_follow_var = tk.BooleanVar(value=True)

    if not hasattr(app, "preview_time_var") or app.preview_time_var is None:
        app.preview_time_var = tk.StringVar(value="Time: --:--")
    if not hasattr(app, "preview_segment_var") or app.preview_segment_var is None:
        app.preview_segment_var = tk.StringVar(value="Segments: 0/0")
    if not hasattr(app, "preview_scrubber_var") or app.preview_scrubber_var is None:
        app.preview_scrubber_var = tk.DoubleVar(value=0.0)

    # =========================================================
    # HELPERS
    # =========================================================
    def _set_mode(mode: str) -> None:
        app.preview_mode.set(mode)

        if mode == "2d":
            btn_mode_2d.config(bg=BTN_BLUE, fg=BTN_BLUE_FG, relief="sunken")
            btn_mode_3d.config(bg="#2E2E2E", fg=FG, relief="raised")
        else:
            btn_mode_2d.config(bg="#2E2E2E", fg=FG, relief="raised")
            btn_mode_3d.config(bg=BTN_BLUE, fg=BTN_BLUE_FG, relief="sunken")

        if hasattr(app, "_switch_preview_mode"):
            app._switch_preview_mode()

    def _set_speed(speed_text: str) -> None:
        app.preview_speed_var.set(speed_text)

        for value, btn in speed_buttons.items():
            if value == speed_text:
                btn.config(bg=BTN_BLUE, fg=BTN_BLUE_FG, relief="sunken")
            else:
                btn.config(bg="#2E2E2E", fg=FG, relief="raised")

        if hasattr(app, "_update_preview_speed"):
            app._update_preview_speed()

    def _safe_call(name: str):
        fn = getattr(app, name, None)
        if callable(fn):
            fn()

    def _set_view_top() -> None:
        if getattr(app, "preview_3d_ax", None) is None:
            return
        try:
            app.preview_3d_ax.view_init(elev=90, azim=-90)
            app.preview_3d_canvas.draw_idle()
        except Exception:
            pass

    def _set_view_front() -> None:
        if getattr(app, "preview_3d_ax", None) is None:
            return
        try:
            app.preview_3d_ax.view_init(elev=0, azim=-90)
            app.preview_3d_canvas.draw_idle()
        except Exception:
            pass

    def _set_view_iso() -> None:
        if getattr(app, "preview_3d_ax", None) is None:
            return
        try:
            app.preview_3d_ax.view_init(elev=20, azim=-90)
            app.preview_3d_canvas.draw_idle()
        except Exception:
            pass

    def _toggle_live_follow() -> None:
        current = bool(app.preview_live_follow_var.get())
        app.preview_live_follow_var.set(not current)
        _refresh_follow_button()

    def _refresh_follow_button() -> None:
        if bool(app.preview_live_follow_var.get()):
            btn_follow.config(bg=BTN_GREEN, fg=BTN_GREEN_FG, relief="sunken", text="FOLLOW ON")
        else:
            btn_follow.config(bg="#2E2E2E", fg=FG, relief="raised", text="FOLLOW OFF")

    # =========================================================
    # TOP BAR
    # =========================================================
    top = tk.Frame(main, bg=PANEL_BG, height=70)
    top.pack(fill="x", padx=0, pady=0)
    top.pack_propagate(False)

    # Left section: mode buttons
    mode_frame = tk.Frame(top, bg=PANEL_BG)
    mode_frame.pack(side="left", padx=12, pady=10)

    tk.Label(
        mode_frame,
        text="VIEW MODE",
        bg=PANEL_BG,
        fg="#BFBFBF",
        font=title_font,
    ).pack(anchor="w", pady=(0, 6))

    mode_btn_row = tk.Frame(mode_frame, bg=PANEL_BG)
    mode_btn_row.pack(anchor="w")

    btn_mode_2d = tk.Button(
        mode_btn_row,
        text="2D XY",
        command=lambda: _set_mode("2d"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=mode_font,
        width=8,
        height=1,
        bd=2,
        relief="sunken",
    )
    btn_mode_2d.pack(side="left", padx=(0, 8))

    btn_mode_3d = tk.Button(
        mode_btn_row,
        text="3D PATH",
        command=lambda: _set_mode("3d"),
        bg="#2E2E2E",
        fg=FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=mode_font,
        width=8,
        height=1,
        bd=2,
        relief="raised",
    )
    btn_mode_3d.pack(side="left")

    # Center section: playback
    playback_frame = tk.Frame(top, bg=PANEL_BG)
    playback_frame.pack(side="left", padx=14, pady=10)

    tk.Label(
        playback_frame,
        text="PLAYBACK",
        bg=PANEL_BG,
        fg="#BFBFBF",
        font=title_font,
    ).pack(anchor="w", pady=(0, 6))

    playback_btn_row = tk.Frame(playback_frame, bg=PANEL_BG)
    playback_btn_row.pack(anchor="w")

    app.preview_play_btn = tk.Button(
        playback_btn_row,
        text="▶ PLAY",
        command=lambda: _safe_call("_preview_play"),
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=8,
        height=1,
        bd=2,
        relief="raised",
    )
    app.preview_play_btn.pack(side="left", padx=(0, 6))

    app.preview_pause_btn = tk.Button(
        playback_btn_row,
        text="⏸ PAUSE",
        command=lambda: _safe_call("_preview_pause"),
        bg=BTN_ORANGE,
        fg=BTN_ORANGE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=8,
        height=1,
        bd=2,
        relief="raised",
        state="disabled",
    )
    app.preview_pause_btn.pack(side="left", padx=6)

    app.preview_step_btn = tk.Button(
        playback_btn_row,
        text="⏭ STEP",
        command=lambda: _safe_call("_preview_step_frame"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=8,
        height=1,
        bd=2,
        relief="raised",
    )
    app.preview_step_btn.pack(side="left", padx=6)

    app.preview_stop_btn = tk.Button(
        playback_btn_row,
        text="⏹ STOP",
        command=lambda: _safe_call("_preview_stop"),
        bg=BTN_RED,
        fg=BTN_RED_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=8,
        height=1,
        bd=2,
        relief="raised",
    )
    app.preview_stop_btn.pack(side="left", padx=(6, 0))

    # Right section: info
    info_frame = tk.Frame(top, bg=PANEL_BG)
    info_frame.pack(side="right", padx=14, pady=10, fill="y")

    tk.Label(
        info_frame,
        text="STATUS",
        bg=PANEL_BG,
        fg="#BFBFBF",
        font=title_font,
    ).pack(anchor="e", pady=(0, 6))

    tk.Label(
        info_frame,
        textvariable=app.preview_segment_var,
        bg=PANEL_BG,
        fg=FG,
        font=info_font,
        anchor="e",
        justify="right",
    ).pack(anchor="e")

    tk.Label(
        info_frame,
        textvariable=app.preview_time_var,
        bg=PANEL_BG,
        fg=FG,
        font=info_font,
        anchor="e",
        justify="right",
    ).pack(anchor="e", pady=(6, 0))

    # =========================================================
    # SECOND TOOLBAR
    # =========================================================
    controls2 = tk.Frame(main, bg="#171717", height=60)
    controls2.pack(fill="x", padx=0, pady=0)
    controls2.pack_propagate(False)

    # View presets
    view_frame = tk.Frame(controls2, bg="#171717")
    view_frame.pack(side="left", padx=12, pady=10)

    tk.Label(
        view_frame,
        text="CAMERA",
        bg="#171717",
        fg="#BFBFBF",
        font=title_font,
    ).pack(anchor="w", pady=(0, 6))

    view_btn_row = tk.Frame(view_frame, bg="#171717")
    view_btn_row.pack(anchor="w")

    btn_top = tk.Button(
        view_btn_row,
        text="TOP",
        command=_set_view_top,
        bg="#2E2E2E",
        fg=FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=mode_font,
        width=7,
        height=1,
        bd=2,
        relief="raised",
    )
    btn_top.pack(side="left", padx=(0, 6))

    btn_front = tk.Button(
        view_btn_row,
        text="FRONT",
        command=_set_view_front,
        bg="#2E2E2E",
        fg=FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=mode_font,
        width=7,
        height=1,
        bd=2,
        relief="raised",
    )
    btn_front.pack(side="left", padx=6)

    btn_iso = tk.Button(
        view_btn_row,
        text="ISO",
        command=_set_view_iso,
        bg="#2E2E2E",
        fg=FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=mode_font,
        width=7,
        height=1,
        bd=2,
        relief="raised",
    )
    btn_iso.pack(side="left", padx=6)

    btn_follow = tk.Button(
        view_btn_row,
        text="FOLLOW ON",
        command=_toggle_live_follow,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=mode_font,
        width=8,
        height=1,
        bd=2,
        relief="sunken",
    )
    btn_follow.pack(side="left", padx=(6, 0))

    # Speed presets
    speed_frame = tk.Frame(controls2, bg="#171717")
    speed_frame.pack(side="left", padx=24, pady=10)

    tk.Label(
        speed_frame,
        text="SPEED",
        bg="#171717",
        fg="#BFBFBF",
        font=title_font,
    ).pack(anchor="w", pady=(0, 6))

    speed_btn_row = tk.Frame(speed_frame, bg="#171717")
    speed_btn_row.pack(anchor="w")

    speed_buttons = {}
    for value in ["0.5x", "1.0x", "2.0x", "4.0x"]:
        btn = tk.Button(
            speed_btn_row,
            text=value,
            command=lambda v=value: _set_speed(v),
            bg="#2E2E2E",
            fg=FG,
            activebackground=BTN_PRESSED,
            activeforeground="#000000",
            font=speed_font,
            width=6,
            height=1,
            bd=2,
            relief="raised",
        )
        btn.pack(side="left", padx=(0, 6))
        speed_buttons[value] = btn

    # =========================================================
    # PREVIEW AREA
    # =========================================================
    app.preview_container = tk.Frame(main, bg=BG)
    app.preview_container.pack(fill="both", expand=True)

    app.preview_canvas_2d = tk.Canvas(
        app.preview_container,
        bg="#0D0D0D",
        highlightthickness=0,
    )

    app.preview_3d_figure = Figure(figsize=(18, 12), dpi=100)
    app.preview_3d_figure.subplots_adjust(left=0.00, right=1.00, bottom=0.00, top=1.00)
    app.preview_3d_ax = app.preview_3d_figure.add_subplot(111, projection="3d")

    app.preview_3d_figure.patch.set_facecolor("#111111")
    app.preview_3d_ax.set_facecolor("#111111")

    try:
        app.preview_3d_ax.set_proj_type("ortho")
    except Exception:
        pass

    try:
        app.preview_3d_ax.view_init(elev=20, azim=-90)
    except Exception:
        pass

    try:
        app.preview_3d_ax.set_box_aspect([1, 1, 0.2])
    except Exception:
        pass

    try:
        app.preview_3d_ax.grid(False)
        app.preview_3d_ax.xaxis.pane.fill = False
        app.preview_3d_ax.yaxis.pane.fill = False
        app.preview_3d_ax.zaxis.pane.fill = False
        app.preview_3d_ax.set_axis_off()
    except Exception:
        pass

    app.preview_3d_canvas = FigureCanvasTkAgg(
        app.preview_3d_figure,
        master=app.preview_container,
    )

    # =========================================================
    # BOTTOM SCRUBBER
    # =========================================================
    scrubber_frame = tk.Frame(main, bg=PANEL_BG, height=90)
    scrubber_frame.pack(fill="x", padx=0, pady=0)
    scrubber_frame.pack_propagate(False)

    scrubber_inner = tk.Frame(scrubber_frame, bg=PANEL_BG)
    scrubber_inner.pack(fill="both", expand=True, padx=10, pady=8)

    tk.Label(
        scrubber_inner,
        text="TIMELINE",
        bg=PANEL_BG,
        fg="#BFBFBF",
        font=title_font,
    ).pack(anchor="w", pady=(0, 4))

    app.preview_scrubber = tk.Scale(
        scrubber_inner,
        from_=0.0,
        to=100.0,
        orient="horizontal",
        variable=app.preview_scrubber_var,
        bg=PANEL_BG,
        fg=FG,
        troughcolor="#1A1A1A",
        activebackground=BTN_BLUE,
        highlightthickness=0,
        sliderlength=40,
        width=28,
        font=("Arial", 10, "bold"),
        command=app._preview_scrubber_moved,
    )
    app.preview_scrubber.pack(fill="x", expand=True)

    # init visuals
    _set_speed("1.0x")
    _refresh_follow_button()
    _set_mode("2d")