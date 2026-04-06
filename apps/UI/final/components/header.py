import tkinter as tk
from tkinter import ttk

from ..theme import BG, FG, BTN_NEUTRAL, BTN_NEUTRAL_FG, BTN_PRESSED


def build_header(app, parent):
    header = tk.Frame(parent, bg=BG)
    header.pack(fill="x", pady=(1, 0))

    left = tk.Frame(header, bg=BG)
    left.pack(side="left", fill="x", expand=True)

    right = tk.Frame(header, bg=BG)
    right.pack(side="right", padx=(8, 6))

    label_font = ("Arial", 10, "bold")
    status_font = ("Arial", 10, "bold")
    small_font = ("Arial", 8, "bold")

    tk.Label(left, text="Port", bg=BG, fg=FG, font=label_font).pack(side="left", padx=(6, 2))

    app.port_combo = ttk.Combobox(left, textvariable=app.port_var, width=14)
    app.port_combo.pack(side="left", padx=2)

    tk.Button(
        left,
        text="Refresh",
        command=app._refresh_ports,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        font=small_font,
        padx=5,
        pady=1,
    ).pack(side="left", padx=4)

    tk.Label(left, text="Baud", bg=BG, fg=FG, font=label_font).pack(side="left", padx=(8, 2))

    tk.Entry(left, textvariable=app.baud_var, width=7, font=small_font).pack(side="left", padx=2)

    tk.Button(
        left,
        text="Connect",
        command=app._connect,
        font=small_font,
        padx=5,
        pady=1,
    ).pack(side="left", padx=4)

    tk.Button(
        left,
        text="Disconnect",
        command=app._disconnect,
        font=small_font,
        padx=5,
        pady=1,
    ).pack(side="left", padx=4)

    tk.Label(
        right,
        textvariable=app.status_text,
        bg=BG,
        fg="#CCCCCC",
        font=status_font,
    ).pack(anchor="e")

    tk.Label(
        right,
        textvariable=app.state_text,
        bg=BG,
        fg="#AAAAAA",
        font=small_font,
    ).pack(anchor="e")

    tk.Label(
        right,
        textvariable=app.job_progress_text,
        bg=BG,
        fg="#00FF88",
        font=small_font,
    ).pack(anchor="e")

    limits_row = tk.Frame(right, bg=BG)
    limits_row.pack(anchor="e", pady=(1, 0))

    tk.Label(
        limits_row,
        text="Limits:",
        bg=BG,
        fg="#FFD54A",
        font=small_font,
    ).pack(side="left", padx=(0, 4))

    app.limit_labels = {}
    for axis in ["X", "Y", "Z", "B", "C"]:
        lbl = tk.Label(
            limits_row,
            text=axis,
            bg="#444444",
            fg="#FFFFFF",
            width=2,
            font=("Arial", 8, "bold"),
            relief="raised",
            bd=1,
        )
        lbl.pack(side="left", padx=1)
        app.limit_labels[axis] = lbl