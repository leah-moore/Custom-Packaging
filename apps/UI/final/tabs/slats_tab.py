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
    BTN_PRESSED,
)


def build_slats_tab(app, parent) -> None:
    default_font = ("Arial", 8, "bold")
    title_font = ("Arial", 9, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=4, pady=4)

    # =========================
    # TOP CONTROLS
    # =========================
    top = tk.LabelFrame(
        main,
        text="Slat Generation Controls",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    top.pack(fill="x", pady=(0, 8))

    btn_row = tk.Frame(top, bg=PANEL_BG)
    btn_row.pack(fill="x")

    tk.Button(
        btn_row,
        text="Use Mesh",
        command=app._use_loaded_mesh_for_slats,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=12,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Generate Slats",
        command=app._generate_slats,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        font=default_font,
        width=14,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Clear Slats",
        command=app._clear_slats,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=12,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    # =========================
    # SETTINGS
    # =========================
    settings = tk.LabelFrame(
        main,
        text="Slat Settings",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    settings.pack(fill="x", pady=(0, 8))

    row = tk.Frame(settings, bg=PANEL_BG)
    row.pack(fill="x", pady=2)

    tk.Label(
        row,
        text="Spacing:",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
    ).pack(side="left")
    tk.Entry(
        row,
        textvariable=app.slat_spacing_var,
        width=10,
    ).pack(side="left", padx=6)

    tk.Label(
        row,
        text="Thickness:",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
    ).pack(side="left", padx=(10, 0))
    tk.Entry(
        row,
        textvariable=app.slat_thickness_var,
        width=10,
    ).pack(side="left", padx=6)

    tk.Label(
        row,
        text="Height:",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
    ).pack(side="left", padx=(10, 0))
    tk.Entry(
        row,
        textvariable=app.slat_height_var,
        width=10,
    ).pack(side="left", padx=6)

    tk.Checkbutton(
        settings,
        text="Show Mesh Overlay",
        variable=app.show_mesh_overlay_var,
        bg=PANEL_BG,
        fg=FG,
        selectcolor=BG,
        activebackground=PANEL_BG,
        activeforeground=FG,
        font=default_font,
        command=getattr(app, "_draw_slats_preview", None),
    ).pack(anchor="w", pady=2)

    # =========================
    # INFO
    # =========================
    info_box = tk.LabelFrame(
        main,
        text="Slat Info",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    info_box.pack(fill="x", pady=(0, 8))

    tk.Label(
        info_box,
        textvariable=app.slat_info_text,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x")

    # Optional mesh status line if app has mesh_info_text
    if hasattr(app, "mesh_info_text"):
        tk.Label(
            info_box,
            textvariable=app.mesh_info_text,
            bg=PANEL_BG,
            fg="#999999",
            font=default_font,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 0))

    # =========================
    # 3D VIEW
    # =========================
    view_box = tk.LabelFrame(
        main,
        text="3D Slat View",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    view_box.pack(fill="both", expand=True)

    app.slats_figure = Figure(figsize=(8, 6), dpi=100)
    app.slats_figure.patch.set_facecolor("#111111")
    app.slats_figure.subplots_adjust(left=0.00, right=1.00, bottom=0.00, top=1.00)

    app.slats_ax = app.slats_figure.add_subplot(111, projection="3d")
    app.slats_ax.set_facecolor("#111111")

    app.slats_canvas = FigureCanvasTkAgg(app.slats_figure, master=view_box)
    app.slats_canvas.get_tk_widget().pack(fill="both", expand=True)

    try:
        app._draw_slats_preview()
    except Exception:
        pass