import tkinter as tk
from tkinter import ttk

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
    default_font = ("Arial", 8, "bold")
    control_font = ("Arial", 12, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=0, pady=0)

    # ===== TOP TOOLBAR =====
    top = tk.Frame(main, bg=PANEL_BG, height=50)
    top.pack(fill="x", padx=0, pady=0)
    top.pack_propagate(False)

    # Left: Mode selector
    mode_frame = tk.Frame(top, bg=PANEL_BG)
    mode_frame.pack(side="left", padx=10, pady=6)

    app.preview_mode = tk.StringVar(value="2d")

    tk.Radiobutton(
        mode_frame,
        text="2D XY",
        variable=app.preview_mode,
        value="2d",
        bg=PANEL_BG,
        fg=FG,
        activebackground=BG,
        selectcolor=BTN_BLUE,
        font=("Arial", 9, "bold"),
        command=app._switch_preview_mode,
    ).pack(side="left", padx=8)

    tk.Radiobutton(
        mode_frame,
        text="3D Path",
        variable=app.preview_mode,
        value="3d",
        bg=PANEL_BG,
        fg=FG,
        activebackground=BG,
        selectcolor=BTN_BLUE,
        font=("Arial", 9, "bold"),
        command=app._switch_preview_mode,
    ).pack(side="left", padx=8)

    # Center: Playback controls
    playback_frame = tk.Frame(top, bg=PANEL_BG)
    playback_frame.pack(side="left", padx=20, pady=6)

    app.preview_play_btn = tk.Button(
        playback_frame,
        text="▶ Play",
        command=app._preview_play,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=6,
        bd=2,
        relief="raised",
    )
    app.preview_play_btn.pack(side="left", padx=2)

    app.preview_pause_btn = tk.Button(
        playback_frame,
        text="⏸ Pause",
        command=app._preview_pause,
        bg=BTN_ORANGE,
        fg=BTN_ORANGE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=6,
        bd=2,
        relief="raised",
        state="disabled",
    )
    app.preview_pause_btn.pack(side="left", padx=2)

    tk.Button(
        playback_frame,
        text="⏭ Step",
        command=app._preview_step_frame,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=6,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=2)

    tk.Button(
        playback_frame,
        text="⏹ Stop",
        command=app._preview_stop,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=control_font,
        width=6,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=2)

    tk.Label(
        playback_frame,
        text="Speed:",
        bg=PANEL_BG,
        fg=FG,
        font=("Arial", 11, "bold"),
    ).pack(side="left", padx=(20, 4))

    app.preview_speed_var = tk.StringVar(value="1.0x")
    speed_combo = ttk.Combobox(
        playback_frame,
        textvariable=app.preview_speed_var,
        values=["0.25x", "0.5x", "0.75x", "1.0x", "1.5x", "2.0x", "4.0x"],
        width=6,
        state="readonly",
        font=("Arial", 11, "bold"),
    )
    speed_combo.pack(side="left", padx=2)
    speed_combo.current(3)
    speed_combo.bind("<<ComboboxSelected>>", lambda e: app._update_preview_speed())

    app.preview_live_follow_var = tk.BooleanVar(value=True)

    tk.Checkbutton(
        top,
        text="Live Follow",
        variable=app.preview_live_follow_var,
        bg=PANEL_BG,
        fg=FG,
        activebackground=PANEL_BG,
        activeforeground=FG,
        selectcolor=BTN_BLUE,
        font=("Arial", 9, "bold"),
    ).pack(side="right", padx=10)


    # Right: Info display
    info_frame = tk.Frame(top, bg=PANEL_BG)
    info_frame.pack(side="right", padx=10, pady=6, fill="x", expand=True)

    app.preview_time_var = tk.StringVar(value="Time: --:--")
    app.preview_segment_var = tk.StringVar(value="Segments: 0/0")

    tk.Label(
        info_frame,
        textvariable=app.preview_segment_var,
        bg=PANEL_BG,
        fg=FG,
        font=("Arial", 11, "bold"),
    ).pack(side="left", padx=(0, 20))

    tk.Label(
        info_frame,
        textvariable=app.preview_time_var,
        bg=PANEL_BG,
        fg=FG,
        font=("Arial", 11, "bold"),
    ).pack(side="left", padx=0)

    # ===== CANVAS AREA =====
    app.preview_container = tk.Frame(main, bg=BG)
    app.preview_container.pack(fill="both", expand=True)

    app.preview_canvas_2d = tk.Canvas(
        app.preview_container,
        bg="#0D0D0D",
        highlightthickness=0,
    )

    app.preview_3d_figure = Figure(figsize=(18, 12), dpi=100)
    app.preview_3d_figure.subplots_adjust(left=0.01, right=0.99, bottom=0.02, top=0.98)
    app.preview_3d_ax = app.preview_3d_figure.add_subplot(111, projection="3d")
    app.preview_3d_figure.patch.set_facecolor("#111111")
    app.preview_3d_ax.set_facecolor("#111111")
    app.preview_3d_canvas = FigureCanvasTkAgg(
        app.preview_3d_figure,
        master=app.preview_container,
    )

    # ===== BOTTOM SCRUBBER =====
    scrubber_frame = tk.Frame(main, bg=PANEL_BG, height=40)
    scrubber_frame.pack(fill="x", padx=0, pady=0)
    scrubber_frame.pack_propagate(False)

    app.preview_scrubber_var = tk.DoubleVar(value=0.0)
    app.preview_scrubber = tk.Scale(
        scrubber_frame,
        from_=0.0,
        to=100.0,
        orient="horizontal",
        variable=app.preview_scrubber_var,
        bg=PANEL_BG,
        fg=FG,
        troughcolor="#1A1A1A",
        activebackground=BTN_BLUE,
        highlightthickness=0,
        command=app._preview_scrubber_moved,
    )
    app.preview_scrubber.pack(fill="both", expand=True, padx=2, pady=1)

    app._switch_preview_mode()