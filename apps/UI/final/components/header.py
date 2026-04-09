import tkinter as tk
from tkinter import ttk

from ..theme import BG, FG, BTN_NEUTRAL, BTN_NEUTRAL_FG, BTN_PRESSED


def build_header(app, parent):
    header = tk.Frame(parent, bg=BG, height=58)
    header.pack(fill="x", pady=(2, 0), padx=8)
    header.pack_propagate(False)

    label_font = ("Arial", 10, "bold")
    button_font = ("Arial", 10, "bold")
    entry_font = ("Arial", 10, "bold")
    status_font = ("Arial", 10, "bold")
    info_font = ("Arial", 9, "bold")
    limits_font = ("Arial", 10, "bold")

    # =========================
    # LEFT: CONNECTION CONTROLS
    # =========================
    left = tk.Frame(header, bg=BG)
    left.pack(side="left", fill="y")

    tk.Label(left, text="Port", bg=BG, fg=FG, font=label_font).pack(side="left", padx=(0, 4))

    app.port_combo = ttk.Combobox(
        left,
        textvariable=app.port_var,
        width=18,
        font=entry_font,
        state="readonly",
    )
    app.port_combo.pack(side="left", padx=(0, 8), ipady=1)

    tk.Button(
        left,
        text="Refresh",
        command=app._refresh_ports,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=button_font,
        width=8,
        pady=1,
    ).pack(side="left", padx=(0, 10))

    tk.Label(left, text="Baud", bg=BG, fg=FG, font=label_font).pack(side="left", padx=(0, 4))

    app.baud_combo = ttk.Combobox(
        left,
        textvariable=app.baud_var,
        width=8,
        font=entry_font,
        state="readonly",
        values=["9600", "19200", "38400", "57600", "115200", "230400"],
    )
    app.baud_combo.pack(side="left", padx=(0, 8), ipady=1)

    tk.Button(
        left,
        text="Connect",
        command=app._connect,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=button_font,
        width=9,
        pady=1,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        left,
        text="Disconnect",
        command=app._disconnect,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=button_font,
        width=10,
        pady=1,
    ).pack(side="left")

    # =========================
    # RIGHT: STATUS
    # =========================
    # Fixed-width area so long status text doesn't shove the limits around
    right = tk.Frame(header, bg=BG, width=250)
    right.pack(side="right", fill="y")
    right.pack_propagate(False)

    tk.Label(
        right,
        textvariable=app.status_text,
        bg=BG,
        fg="#DDDDDD",
        font=status_font,
        anchor="e",
        justify="right",
    ).pack(anchor="e", pady=(2, 0))

    tk.Label(
        right,
        textvariable=app.state_text,
        bg=BG,
        fg="#BBBBBB",
        font=info_font,
        anchor="e",
        justify="right",
    ).pack(anchor="e")

    tk.Label(
        right,
        textvariable=app.job_progress_text,
        bg=BG,
        fg="#00FF88",
        font=info_font,
        anchor="e",
        justify="right",
    ).pack(anchor="e")

    # =========================
    # CENTER: LIMITS
    # =========================
    # Overlay in the visual center so it stays centered
    center = tk.Frame(header, bg=BG)
    center.place(relx=0.63, rely=0.45, anchor="center")

    tk.Label(
        center,
        text="Limits:",
        bg=BG,
        fg="#FFD54A",
        font=info_font,
    ).pack(side="left", padx=(0, 6))

    app.limit_labels = {}
    for axis in ["X", "Y", "Z", "A", "B"]:
        lbl = tk.Label(
            center,
            text=axis,
            bg="#4A4A4A",
            fg="#FFFFFF",
            width=2,
            font=limits_font,
            relief="solid",
            bd=1,
            padx=1,
            pady=1,
        )
        lbl.pack(side="left", padx=2)
        app.limit_labels[axis] = lbl