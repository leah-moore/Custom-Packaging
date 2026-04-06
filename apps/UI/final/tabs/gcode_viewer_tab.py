import tkinter as tk
from tkinter import ttk

from ..theme import (
    BG,
    FG,
    CONSOLE_BG,
    CONSOLE_FG,
    BTN_NEUTRAL,
    BTN_NEUTRAL_FG,
    BTN_PRESSED,
)


def build_gcode_viewer_tab(app, parent) -> None:
    default_font = ("Arial", 8, "bold")
    mono_font = ("Courier New", 11)

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=0, pady=0)

    top = tk.Frame(main, bg=BG)
    top.pack(fill="x", pady=(0, 8))

    tk.Label(
        top,
        text="G-code File",
        bg=BG,
        fg=FG,
        font=default_font,
    ).pack(side="left", padx=(0, 8))

    tk.Label(
        top,
        textvariable=app.file_text,
        bg=BG,
        fg=FG,
        font=default_font,
    ).pack(side="left", padx=8)

    tk.Button(
        top,
        text="Load File",
        command=app._load_gcode_file,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        width=12,
        bd=3,
        relief="raised",
    ).pack(side="right", padx=(8, 0))

    frame = tk.Frame(main, bg=BG)
    frame.pack(fill="both", expand=True)

    scrollbar = ttk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")

    app.gcode_viewer = tk.Text(
        frame,
        font=mono_font,
        bg=CONSOLE_BG,
        fg=CONSOLE_FG,
        insertbackground=FG,
        wrap="none",
        yscrollcommand=scrollbar.set,
        bd=2,
        relief="solid",
    )
    app.gcode_viewer.pack(side="left", fill="both", expand=True)

    scrollbar.config(command=app.gcode_viewer.yview)