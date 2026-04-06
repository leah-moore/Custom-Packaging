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
    BTN_PRESSED,
)


def build_mesh_tab(app, parent) -> None:
    default_font = ("Arial", 8, "bold")
    title_font = ("Arial", 9, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=0, pady=0)

    # =========================
    # TOP CONTROLS
    # =========================
    top = tk.LabelFrame(
        main,
        text="Mesh Controls",
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
        text="Load Mesh",
        command=app._load_scan_mesh,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Clear Mesh",
        command=app._clear_scan_mesh,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Iso View",
        command=lambda: app._set_mesh_view("iso"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Front View",
        command=lambda: app._set_mesh_view("front"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Side View",
        command=lambda: app._set_mesh_view("side"),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    tk.Button(
        btn_row,
        text="Reset View",
        command=app._reset_mesh_view,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=10,
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4, pady=4)

    # =========================
    # INFO
    # =========================
    info_box = tk.LabelFrame(
        main,
        text="Mesh Info",
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
        textvariable=app.mesh_info_text,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x")

    # =========================
    # 3D VIEW
    # =========================
    view_box = tk.LabelFrame(
        main,
        text="Mesh Preview",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    view_box.pack(fill="both", expand=True)

    app.mesh_figure = Figure(figsize=(8, 6), dpi=100)
    app.mesh_ax = app.mesh_figure.add_subplot(111, projection="3d")
    app.mesh_figure.patch.set_facecolor("#111111")
    app.mesh_ax.set_facecolor("#111111")

    app.mesh_canvas = FigureCanvasTkAgg(app.mesh_figure, master=view_box)
    app.mesh_canvas.get_tk_widget().pack(fill="both", expand=True)

    # draw current state if any
    try:
        app._draw_mesh_preview()
    except Exception:
        pass