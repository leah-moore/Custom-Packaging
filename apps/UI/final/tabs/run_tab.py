import tkinter as tk
from tkinter import ttk

from ..theme import (
    BG,
    PANEL_BG,
    FG,
    CONSOLE_BG,
    CONSOLE_FG,
    BTN_NEUTRAL,
    BTN_NEUTRAL_FG,
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


def build_run_tab(app, parent) -> None:
    default_font = ("Arial", 10, "bold")
    mono_font = ("Courier New", 12)
    small_font = ("Courier", 14)

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=0, pady=0)

    job_box = tk.LabelFrame(
        main,
        text="G-code Job",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
        padx=2,
        pady=1,
        bd=2,
        relief="solid",
    )
    job_box.pack(fill="x", pady=(0, 8))

    tk.Label(
        job_box,
        textvariable=app.file_text,
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
        anchor="w",
        justify="left",
        wraplength=800,
    ).pack(fill="x", pady=(0, 6))

    job_btns = tk.Frame(job_box, bg=PANEL_BG)
    job_btns.pack(fill="x")

    tk.Button(
        job_btns,
        text="Load File",
        command=app._load_gcode_file,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=0, padx=4, pady=4)

    tk.Button(
        job_btns,
        text="Load Current Window",
        command=getattr(
            app,
            "_load_current_window_gcode",
            lambda: None
        ),
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=18,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=1, padx=4, pady=4)


    tk.Button(
        job_btns,
        text="Run G-code",
        command=app._start_gcode_job,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=2, padx=4, pady=4)

    tk.Button(
        job_btns,
        text="Run Slats Job",
        command=app._start_slats_job,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=12,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=3, padx=4, pady=4)

    tk.Button(
        job_btns,
        text="Pause",
        command=app._pause_gcode_job,
        bg=BTN_ORANGE,
        fg=BTN_ORANGE_FG,
        font=default_font,
        width=8,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=4, padx=4, pady=4)

    tk.Button(
        job_btns,
        text="Resume",
        command=app._resume_gcode_job,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=8,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=5, padx=4, pady=4)

    tk.Button(
        job_btns,
        text="Stop",
        command=app._stop_gcode_job,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        font=default_font,
        width=8,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).grid(row=0, column=6, padx=4, pady=4)

    # =========================
    # TRUE 2-COLUMN G-CODE TABLE
    # =========================
    table_outer = tk.Frame(job_box, bg="#2a2a2a", bd=1)
    table_outer.pack(fill="both", expand=True, pady=(6, 4))

    # header row
    header = tk.Frame(table_outer, bg="#2a2a2a")
    header.pack(fill="x")

    header_status = tk.Label(
        header,
        text="OK",
        bg="#2a2a2a",
        fg="#ffffff",
        font=default_font,
        bd=1,
        relief="solid",
        width=8,
        anchor="center",
    )
    header_status.pack(side="left", fill="y")

    header_gcode = tk.Label(
        header,
        text="G-code",
        bg="#2a2a2a",
        fg="#ffffff",
        font=default_font,
        bd=1,
        relief="solid",
        anchor="center",
    )
    header_gcode.pack(side="left", fill="x", expand=True)

    # scrollable body
    body_outer = tk.Frame(table_outer, bg="#2a2a2a")
    body_outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(
        body_outer,
        bg="#1e1e1e",
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(body_outer, orient="vertical", command=canvas.yview)
    scrollbar.pack(side="right", fill="y")

    canvas.configure(yscrollcommand=scrollbar.set)

    rows_frame = tk.Frame(canvas, bg="#1e1e1e")
    canvas_window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")

    def _on_rows_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event):
        canvas.itemconfigure(canvas_window, width=event.width)

    rows_frame.bind("<Configure>", _on_rows_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    # attach to app for population/updating from app.py
    app.gcode_table_canvas = canvas
    app.gcode_table_rows_frame = rows_frame
    app.gcode_row_frames = []
    app.gcode_row_status_labels = []
    app.gcode_row_code_labels = []

    mdi_box = tk.LabelFrame(
        main,
        text="MDI / Console",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
        padx=2,
        pady=1,
        bd=2,
        relief="solid",
    )
    mdi_box.pack(fill="both", expand=True)

    mdi_top = tk.Frame(mdi_box, bg=PANEL_BG)
    mdi_top.pack(fill="x", pady=(0, 8))

    ttk.Entry(mdi_top, textvariable=app.mdi_var).pack(
        side="left",
        fill="x",
        expand=True,
        padx=(0, 6),
    )

    tk.Button(
        mdi_top,
        text="Send",
        command=app._send_mdi,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        font=default_font,
        width=8,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(side="left")

    app.console = tk.Text(
        mdi_box,
        font=small_font,
        bg=CONSOLE_BG,
        fg=CONSOLE_FG,
        insertbackground=FG,
        wrap="word",
        bd=2,
        relief="solid",
    )
    app.console.pack(fill="both", expand=True)

    tk.Button(
        mdi_box,
        text="Clear Console",
        command=app._clear_console,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=12,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=3,
        relief="raised",
    ).pack(anchor="w", pady=(8, 0))