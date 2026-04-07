import tkinter as tk
from tkinter import ttk

from ..theme import BG, FG, BTN_NEUTRAL, BTN_NEUTRAL_FG, BTN_PRESSED


def build_header(app, parent):
    header = tk.Frame(parent, bg=BG)
    header.pack(fill="x", pady=(2, 0), padx=0)

    # 3-column layout: left controls | centered limits | right status
    header.grid_columnconfigure(0, weight=0)
    header.grid_columnconfigure(1, weight=1)
    header.grid_columnconfigure(2, weight=0)

    left = tk.Frame(header, bg=BG)
    left.grid(row=0, column=0, sticky="w", padx=(8, 0), pady=2)

    center = tk.Frame(header, bg=BG)
    center.grid(row=0, column=1, sticky="nsew", padx=(12, 12), pady=2)

    right = tk.Frame(header, bg=BG)
    right.grid(row=0, column=2, sticky="e", padx=(16, 12), pady=2)

    label_font = ("Arial", 12, "bold")
    button_font = ("Arial", 11, "bold")
    entry_font = ("Arial", 10, "bold")
    status_font = ("Arial", 12, "bold")
    info_font = ("Arial", 10, "bold")
    limits_font = ("Arial", 10, "bold")

    # LEFT SIDE
    tk.Label(
        left,
        text="Port",
        bg=BG,
        fg=FG,
        font=label_font,
    ).pack(side="left", padx=(0, 4))

    app.port_combo = ttk.Combobox(
        left,
        textvariable=app.port_var,
        width=22,
        font=entry_font,
    )
    app.port_combo.pack(side="left", padx=(0, 10), ipady=2)

    tk.Button(
        left,
        text="Refresh",
        command=app._refresh_ports,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        font=button_font,
        padx=12,
        pady=2,
    ).pack(side="left", padx=(0, 12))

    tk.Label(
        left,
        text="Baud",
        bg=BG,
        fg=FG,
        font=label_font,
    ).pack(side="left", padx=(0, 4))

    tk.Entry(
        left,
        textvariable=app.baud_var,
        width=8,
        font=entry_font,
    ).pack(side="left", padx=(0, 12), ipady=2)

    tk.Button(
        left,
        text="Connect",
        command=app._connect,
        font=button_font,
        padx=12,
        pady=2,
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        left,
        text="Disconnect",
        command=app._disconnect,
        font=button_font,
        padx=12,
        pady=2,
    ).pack(side="left", padx=(0, 0))

    # CENTER: LIMITS
    limits_row = tk.Frame(center, bg=BG)
    limits_row.pack(expand=True)

    tk.Label(
        limits_row,
        text="Limits:",
        bg=BG,
        fg="#FFD54A",
        font=info_font,
    ).pack(side="left", padx=(0, 4))

    app.limit_labels = {}
    for axis in ["X", "Y", "Z", "A", "B"]:
        lbl = tk.Label(
            limits_row,
            text=axis,
            bg="#4A4A4A",
            fg="#FFFFFF",
            width=3,
            font=limits_font,
            relief="solid",
            bd=1,
            padx=2,
            pady=2,
        )
        lbl.pack(side="left", padx=2)
        app.limit_labels[axis] = lbl

    # RIGHT SIDE
    tk.Label(
        right,
        textvariable=app.status_text,
        bg=BG,
        fg="#DDDDDD",
        font=status_font,
    ).pack(anchor="e")

    tk.Label(
        right,
        textvariable=app.state_text,
        bg=BG,
        fg="#BBBBBB",
        font=info_font,
    ).pack(anchor="e", pady=(2, 0))

    tk.Label(
        right,
        textvariable=app.job_progress_text,
        bg=BG,
        fg="#00FF88",
        font=info_font,
    ).pack(anchor="e", pady=(2, 0))