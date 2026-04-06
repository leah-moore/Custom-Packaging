import tkinter as tk

from ..theme import (
    BG,
    PANEL_BG,
    FG,
    BTN_NEUTRAL,
    BTN_NEUTRAL_FG,
    BTN_BLUE,
    BTN_BLUE_FG,
    BTN_RED,
    BTN_RED_FG,
    BTN_PRESSED,
)


def build_diagnostics_tab(app, parent):
    default_font = ("Arial", 8, "bold")
    title_font = ("Arial", 9, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True)

    # =========================
    # CONNECTION / STATUS
    # =========================
    status_box = tk.LabelFrame(
        main,
        text="Connection / Machine Status",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    status_box.pack(fill="x", pady=(0, 8))

    row = tk.Frame(status_box, bg=PANEL_BG)
    row.pack(fill="x")

    tk.Button(
        row,
        text="Connect",
        command=app._connect,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4)

    tk.Button(
        row,
        text="Disconnect",
        command=app._disconnect,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4)

    tk.Button(
        row,
        text="Refresh Status",
        command=app._request_status,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=14,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4)

    app.connection_status_var = tk.StringVar(value="Disconnected")

    tk.Label(
        row,
        textvariable=app.connection_status_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=("Arial", 10, "bold"),
        anchor="e",
    ).pack(side="right", padx=6)

    # =========================
    # MACHINE INFO
    # =========================
    info_box = tk.LabelFrame(
        main,
        text="Machine Info",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    info_box.pack(fill="x", pady=(0, 8))

    app.machine_status_var = tk.StringVar(value="No data")

    tk.Label(
        info_box,
        textvariable=app.machine_status_var,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=default_font,
        anchor="w",
        justify="left",
    ).pack(fill="x")

    # =========================
    # RAW COMMANDS
    # =========================
    raw_box = tk.LabelFrame(
        main,
        text="Manual Commands",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    raw_box.pack(fill="x", pady=(0, 8))

    row = tk.Frame(raw_box, bg=PANEL_BG)
    row.pack(fill="x")

    app.raw_cmd_var = tk.StringVar()

    tk.Entry(row, textvariable=app.raw_cmd_var).pack(side="left", fill="x", expand=True, padx=4)

    tk.Button(
        row,
        text="Send",
        command=app._send_raw_command,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left", padx=4)

    # =========================
    # LOG OUTPUT
    # =========================
    log_box = tk.LabelFrame(
        main,
        text="Machine Log",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    log_box.pack(fill="both", expand=True)

    app.diagnostics_log = tk.Text(
        log_box,
        bg="#111111",
        fg="#F5F5F5",
        insertbackground="#FFFFFF",
        font=("Courier New", 10),
        wrap="word",
        bd=2,
        relief="solid",
    )
    app.diagnostics_log.pack(fill="both", expand=True)

    tk.Button(
        log_box,
        text="Clear Log",
        command=lambda: app.diagnostics_log.delete("1.0", tk.END),
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=12,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(anchor="w", pady=(6, 0))