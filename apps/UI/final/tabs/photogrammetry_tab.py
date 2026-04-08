import tkinter as tk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

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


def build_photogrammetry_tab(app, parent) -> None:
    default_font = ("Arial", 8, "bold")
    title_font = ("Arial", 9, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=4, pady=4)

    # =====================================================
    # TOP CONTROLS
    # =====================================================
    top = tk.LabelFrame(
        main,
        text="Photogrammetry Controls",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    top.pack(fill="x", pady=(0, 4))

    btn_row = tk.Frame(top, bg=PANEL_BG)
    btn_row.pack(fill="x")

    tk.Button(
        btn_row,
        text="Start Process",
        command=app._start_photogrammetry_process,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=(12, 4), pady=2)

    tk.Button(
        btn_row,
        text="Load Result Mesh",
        command=app._load_photogrammetry_mesh,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Label(
        btn_row,
        textvariable=app.photogrammetry_info_text,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(side="left", fill="x", expand=True, padx=(12, 8))
        
    tk.Label(
        btn_row,
        textvariable=app.photogrammetry_status_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=("Arial", 10, "bold"),
        anchor="e",
    ).pack(side="right", padx=8)

    # =====================================================
    # ORIENTATION / VIEW TOOLS
    # =====================================================
    tools = tk.LabelFrame(
        main,
        text="Orientation (View + Packaging)",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    tools.pack(fill="x", pady=(0, 4))

    tools_row = tk.Frame(tools, bg=PANEL_BG)
    tools_row.pack(fill="x")

    tk.Button(
        tools_row,
        text="Iso",
        command=lambda: app._set_photogrammetry_mesh_view("iso"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=8,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(0, 4), pady=2)

    tk.Button(
        tools_row,
        text="Front",
        command=lambda: app._set_photogrammetry_mesh_view("front"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=8,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Side",
        command=lambda: app._set_photogrammetry_mesh_view("side"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=8,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Top",
        command=lambda: app._set_photogrammetry_mesh_view("top"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=8,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Lay Flat",
        command=app._lay_flat_photogrammetry_mesh,
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
        text="Reset View",
        command=app._reset_photogrammetry_mesh_view,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    # --- Z rotation (plan rotation / packaging spin) ---
    tk.Button(
        tools_row,
        text="Rotate Z -90°",
        command=lambda: app._rotate_photogrammetry_mesh("z", -90),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(16, 4), pady=2)

    tk.Button(
        tools_row,
        text="Rotate Z +90°",
        command=lambda: app._rotate_photogrammetry_mesh("z", 90),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    # --- X rotation (tilt forward/back for packaging) ---
    tk.Button(
        tools_row,
        text="Rotate X -90°",
        command=lambda: app._rotate_photogrammetry_mesh("x", -90),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(12, 4), pady=2)

    tk.Button(
        tools_row,
        text="Rotate X +90°",
        command=lambda: app._rotate_photogrammetry_mesh("x", 90),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=14,
        bd=2,
        relief="raised",
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        tools_row,
        text="Use This Orientation",
        command=app._use_photogrammetry_orientation,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=22,
        bd=2,
        relief="raised",
    ).pack(side="right", padx=(8, 0), pady=2)

    # =====================================================
    # MAIN SPLIT VIEW
    # =====================================================
    content = tk.Frame(main, bg=BG)
    content.pack(fill="both", expand=True)

    # LEFT: CAMERA (narrower)
    left = tk.LabelFrame(
        content,
        text="Camera View",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
        width=320,
    )
    left.pack(side="left", fill="both", padx=(0, 6))
    left.pack_propagate(False)

    app.photogrammetry_camera_canvas = tk.Canvas(
        left,
        bg="#111111",
        highlightthickness=0,
    )
    app.photogrammetry_camera_canvas.pack(fill="both", expand=True, padx=2, pady=2)

    app.photogrammetry_camera_canvas.create_text(
        160,
        180,
        text="Camera Preview\n(Ready)",
        fill="#666666",
        font=("Arial", 14, "bold"),
        justify="center",
    )

    tk.Label(
        left,
        textvariable=app.photogrammetry_camera_info_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    # RIGHT: MESH PREVIEW (larger)
    right = tk.LabelFrame(
        content,
        text="Mesh Preview",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    right.pack(side="left", fill="both", expand=True, padx=(6, 0))

    app.photogrammetry_figure = Figure(figsize=(8, 6), dpi=100)
    app.photogrammetry_ax = app.photogrammetry_figure.add_subplot(111, projection="3d")
    app.photogrammetry_figure.patch.set_facecolor("#111111")
    app.photogrammetry_ax.set_facecolor("#111111")

    app.photogrammetry_canvas = FigureCanvasTkAgg(app.photogrammetry_figure, master=right)
    app.photogrammetry_canvas.get_tk_widget().pack(fill="both", expand=True)

    tk.Label(
        right,
        textvariable=app.photogrammetry_mesh_info_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x", pady=(4, 0))

    try:
        app._draw_photogrammetry_mesh_preview()
    except Exception:
        pass