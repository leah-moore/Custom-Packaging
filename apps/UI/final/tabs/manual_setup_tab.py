import tkinter as tk

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
    BTN_YELLOW,
    BTN_YELLOW_FG,
    BTN_ORANGE,
    BTN_ORANGE_FG,
    BTN_RED,
    BTN_RED_FG,
    BTN_PRESSED,
)


def build_manual_setup_tab(app, parent) -> None:
    default_font = ("Arial", 9, "bold")
    panel_font = ("Arial", 10, "bold")
    button_font = ("Arial", 10, "bold")
    pos_font = ("Courier", 11, "bold")
    pos_axis_font = ("Arial", 8, "bold")
    mode_font = ("Arial", 9, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=2, pady=2)

    content = tk.Frame(main, bg=BG)
    content.pack(fill="both", expand=True, pady=(6, 0))

    left = tk.Frame(content, bg=BG, width=290)
    left.pack(side="left", fill="y", padx=(0, 4))

    right = tk.Frame(content, bg=BG)
    right.pack(side="left", fill="both", expand=True)

    # =====================================================
    # LEFT: JOG SETTINGS
    # =====================================================
    settings_box = tk.LabelFrame(
        left,
        text="Jog Settings",
        bg=PANEL_BG,
        fg=FG,
        font=panel_font,
        padx=5,
        pady=4,
        bd=2,
        relief="solid",
    )
   
    settings_box.pack(fill="x", pady=(0, 4))

    settings_box.grid_rowconfigure(999, weight=1)

    def make_radio_row(parent_box, row_idx, label_text, variable, values):
        tk.Label(
            parent_box,
            text=label_text,
            bg=PANEL_BG,
            fg=FG,
            font=default_font,
        ).grid(row=row_idx, column=0, sticky="w", pady=(4, 1))

        row = tk.Frame(parent_box, bg=PANEL_BG)
        row.grid(row=row_idx + 1, column=0, sticky="w", padx=(3, 0), pady=(0, 2))

        for val in values:
            tk.Radiobutton(
                row,
                text=str(val),
                variable=variable,
                value=str(val),
                bg=PANEL_BG,
                fg=FG,
                selectcolor=BTN_BLUE,
                font=default_font,
                activebackground=PANEL_BG,
                activeforeground=FG,
                pady=0,
                highlightthickness=0,
                bd=0,
            ).pack(side="left", padx=4)

        return row_idx + 2  # <-- THIS IS THE FIX

    row = 0

    row = make_radio_row(settings_box, row, "Jog Step (mm)", app.jog_step_var, ["0.1", "1", "10", "20"])
    row = make_radio_row(settings_box, row, "Jog Feed (mm/min)", app.jog_feed_var, ["100", "500", "1000", "2000"])
    row = make_radio_row(settings_box, row, "A Step (deg) - Creaser", app.a_rot_step_var, ["1", "5", "10", "45"])
    row = make_radio_row(settings_box, row, "B Step (deg) - Cutter", app.b_rot_step_var, ["1", "5", "10", "45"])
    row = make_radio_row(settings_box, row, "Roller Step (mm)", app.roller_step_var, ["0.5", "1", "5", "10"])
    row = make_radio_row(settings_box, row, "Roller Feed (mm/min)", app.roller_feed_var, ["100", "300", "600", "1200"])

    # =====================================================
    # LEFT: MACHINE CONTROL
    # =====================================================
    ctrl_box = tk.LabelFrame(
        left,
        text="Machine Control",
        bg=PANEL_BG,
        fg=FG,
        font=panel_font,
        padx=5,
        pady=3,
        bd=2,
        relief="solid",
    )
    ctrl_box.pack(fill="x")

    btn_frame = tk.Frame(ctrl_box, bg=PANEL_BG)
    btn_frame.pack(fill="x")

    machine_buttons = [
        ("Home", app._home, BTN_BLUE, BTN_BLUE_FG),
        ("Unlock", app._unlock, BTN_YELLOW, BTN_YELLOW_FG),
        ("Hold", app._hold, BTN_ORANGE, BTN_ORANGE_FG),
        ("Resume", app._resume, BTN_GREEN, BTN_GREEN_FG),
        ("Reset", app._reset, BTN_RED, BTN_RED_FG),
    ]

    for i, (label, fn, color, fgcolor) in enumerate(machine_buttons):
        tk.Button(
            btn_frame,
            text=label,
            command=fn,
            bg=color,
            fg=fgcolor,
            activebackground=BTN_PRESSED,
            activeforeground="#000000",
            font=default_font,
            bd=1,
            relief="raised",
            pady=1,
        ).grid(row=i, column=0, sticky="ew", pady=1)

    btn_frame.grid_columnconfigure(0, weight=1)

    estop_label = tk.Label(
        ctrl_box,
        text="E-STOP",
        bg="#CC0000",
        fg="#FFFFFF",
        font=("Arial", 12, "bold"),
        pady=7,
        relief="raised",
        bd=3,
    )
    estop_label.pack(fill="x", pady=(3, 1))

    def estop_press(event=None):
        estop_label.config(bg="#990000", relief="sunken")
        ctrl_box.after(100, lambda: estop_label.config(bg="#CC0000", relief="raised"))
        app._force_stop()

    estop_label.bind("<Button-1>", estop_press)
    estop_label.config(cursor="hand2")

    # =====================================================
    # RIGHT: JOG CONTROLS
    # =====================================================
    jog_box = tk.LabelFrame(
        right,
        text="Jog Controls",
        bg=PANEL_BG,
        fg=FG,
        font=panel_font,
        padx=4,
        pady=2,
        bd=2,
        relief="solid",
    )
    jog_box.pack(fill="x", pady=(0, 2))

    app.jog_buttons = []

    def make_jog_button(parent_widget, text, axis_moves, row, col, width=3):
        btn = tk.Button(
            parent_widget,
            text=text,
            font=button_font,
            width=width,
            height=1,
            bg=BTN_NEUTRAL,
            fg=BTN_NEUTRAL_FG,
            activebackground=BTN_PRESSED,
            activeforeground="#000000",
            bd=3,
            relief="raised",
            padx=4,
            pady=2,
        )
        btn.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
        btn.bind("<ButtonPress-1>", lambda _e, a=axis_moves, b=btn: app._on_jog_press(a, b))
        btn.bind("<ButtonRelease-1>", lambda _e, b=btn: app._on_jog_release(b))
        app.jog_buttons.append(btn)
        return btn

    for c in range(10):
        if c in (3, 5, 7):
            jog_box.grid_columnconfigure(c, weight=0, minsize=12)
        else:
            jog_box.grid_columnconfigure(c, weight=1, minsize=56)

    for r in range(3):
        jog_box.grid_rowconfigure(r, weight=1, minsize=42)

    # XY cluster
    make_jog_button(jog_box, "Y+", {"Y": 1}, 0, 1)
    make_jog_button(jog_box, "X-", {"X": -1}, 1, 0)
    make_jog_button(jog_box, "X+", {"X": 1}, 1, 2)
    make_jog_button(jog_box, "Y-", {"Y": -1}, 2, 1)

    # Z cluster
    make_jog_button(jog_box, "Z+", {"Z": 1}, 0, 4)
    make_jog_button(jog_box, "Z-", {"Z": -1}, 1, 4)

    # Roller cluster
    make_jog_button(jog_box, "Roller +", {"ROLLER": 1}, 0, 6, width=4)
    make_jog_button(jog_box, "Roller -", {"ROLLER": -1}, 1, 6, width=4)

    # Rotary cluster
    make_jog_button(jog_box, "A+", {"A": 1}, 0, 8)
    make_jog_button(jog_box, "A-", {"A": -1}, 1, 8)
    make_jog_button(jog_box, "B+", {"B": 1}, 0, 9)
    make_jog_button(jog_box, "B-", {"B": -1}, 1, 9)


    # =====================================================
    # RIGHT: JOG MODE
    # =====================================================
    mode_box = tk.LabelFrame(
        right,
        text="Jog Mode",
        bg=PANEL_BG,
        fg=FG,
        font=panel_font,
        padx=6,
        pady=6,
        bd=2,
        relief="solid",
    )
    mode_box.pack(fill="x", pady=(0, 2))

    mode_row = tk.Frame(mode_box, bg=PANEL_BG)
    mode_row.pack(fill="x")

    # segmented toggle container
    toggle_wrap = tk.Frame(
        mode_row,
        bg="#101010",
        bd=2,
        relief="sunken",
        padx=2,
        pady=2,
    )
    toggle_wrap.pack(side="left", padx=(0, 10))

    def update_jog_mode(mode):
        app.jog_mode_var.set(mode)

        if mode == "step":
            step_btn.config(
                bg=BTN_BLUE,
                fg=BTN_BLUE_FG,
                relief="sunken",
                bd=2,
                activebackground=BTN_BLUE,
                activeforeground=BTN_BLUE_FG,
            )
            cont_btn.config(
                bg="#2A2A2A",
                fg="#BBBBBB",
                relief="flat",
                bd=1,
                activebackground="#3A3A3A",
                activeforeground="#FFFFFF",
            )
            mode_status.config(text="STEP MODE ACTIVE", fg="#7EC8FF")
        else:
            cont_btn.config(
                bg=BTN_ORANGE,
                fg=BTN_ORANGE_FG,
                relief="sunken",
                bd=2,
                activebackground=BTN_ORANGE,
                activeforeground=BTN_ORANGE_FG,
            )
            step_btn.config(
                bg="#2A2A2A",
                fg="#BBBBBB",
                relief="flat",
                bd=1,
                activebackground="#3A3A3A",
                activeforeground="#FFFFFF",
            )
            mode_status.config(text="CONTINUOUS MODE ACTIVE", fg="#FFBE6B")

    step_btn = tk.Button(
        toggle_wrap,
        text="STEP",
        font=("Arial", 10, "bold"),
        width=10,
        bg=BTN_BLUE,
        fg=BTN_BLUE_FG,
        bd=2,
        relief="sunken",
        padx=12,
        pady=6,
        highlightthickness=0,
        command=lambda: update_jog_mode("step"),
    )
    step_btn.pack(side="left")

    cont_btn = tk.Button(
        toggle_wrap,
        text="CONT",
        font=("Arial", 10, "bold"),
        width=10,
        bg="#2A2A2A",
        fg="#BBBBBB",
        bd=1,
        relief="flat",
        padx=12,
        pady=6,
        highlightthickness=0,
        command=lambda: update_jog_mode("continuous"),
    )
    cont_btn.pack(side="left", padx=(2, 0))

    text_col = tk.Frame(mode_row, bg=PANEL_BG)
    text_col.pack(side="left", fill="x", expand=True)

    mode_status = tk.Label(
        text_col,
        text="STEP MODE ACTIVE",
        bg=PANEL_BG,
        fg="#7EC8FF",
        font=("Arial", 9, "bold"),
        anchor="w",
    )
    mode_status.pack(anchor="w")

    tk.Label(
        text_col,
        text="STEP = selected step   •   CONT = continuous jog",
        bg=PANEL_BG,
        fg="#AAAAAA",
        font=default_font,
        anchor="w",
    ).pack(anchor="w")

    # =====================================================
    # RIGHT: ROLLER HINT
    # =====================================================
    hint_row = tk.Frame(right, bg=BG)
    hint_row.pack(fill="x", pady=(0, 2))

    tk.Label(
        hint_row,
        text="Roller is Pi-controlled and does not change GRBL axis position",
        bg=BG,
        fg="#888888",
        font=("Arial", 7, "bold"),
        anchor="e",
    ).pack(side="right")

    # =====================================================
    # RIGHT: MID ROW (OUTPUTS + POSITION/ZERO)
    # =====================================================
    mid_row = tk.Frame(right, bg=BG)
    mid_row.pack(fill="x", pady=(0, 2))

    outputs_box = tk.LabelFrame(
        mid_row,
        text="Outputs",
        bg=PANEL_BG,
        fg=BTN_YELLOW,
        font=panel_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
        width=220,
    )
    outputs_box.pack(side="left", fill="y", padx=(0, 4))
    outputs_box.pack_propagate(False)

    outputs_box.grid_columnconfigure(0, weight=1)
    outputs_box.grid_columnconfigure(1, weight=1)

    tk.Button(
        outputs_box,
        text="Light ON",
        command=app._light_on,
        bg=BTN_YELLOW,
        fg=BTN_YELLOW_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=1,
    ).grid(row=0, column=0, padx=3, pady=(2, 1), sticky="ew")

    tk.Button(
        outputs_box,
        text="Light OFF",
        command=app._light_off,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=1,
    ).grid(row=0, column=1, padx=3, pady=(2, 1), sticky="ew")

    outputs_box.grid_rowconfigure(1, minsize=4)

    tk.Label(
        outputs_box,
        text="Spindle Speed (RPM)",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
    ).grid(row=2, column=0, columnspan=2, padx=3, pady=(2, 0), sticky="w")

    speed_row = tk.Frame(outputs_box, bg=PANEL_BG)
    speed_row.grid(row=3, column=0, columnspan=2, padx=3, pady=(2, 6), sticky="w")

    for rpm in ["1000", "2000", "3000", "4000"]:
        tk.Radiobutton(
            speed_row,
            text=rpm,
            variable=app.spindle_speed_var,
            value=rpm,
            bg=PANEL_BG,
            fg=FG,
            selectcolor=BTN_BLUE,
            font=default_font,
            activebackground=PANEL_BG,
            activeforeground=FG,
            pady=0,
            highlightthickness=0,
            bd=0,
        ).pack(side="left", padx=2)

    tk.Button(
        outputs_box,
        text="Spindle ON",
        command=app._spindle_on,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=1,
    ).grid(row=4, column=0, padx=3, pady=(2, 3), sticky="ew")

    tk.Button(
        outputs_box,
        text="Spindle OFF",
        command=app._spindle_off,
        bg=BTN_RED,
        fg=BTN_RED_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=1,
    ).grid(row=4, column=1, padx=3, pady=(2, 3), sticky="ew")

    tk.Label(
        outputs_box,
        textvariable=app.spindle_status_var,
        bg=PANEL_BG,
        fg="#AAAAAA",
        font=default_font,
    ).grid(row=5, column=0, columnspan=2, padx=3, pady=(1, 2), sticky="w")

    pos_zero_box = tk.LabelFrame(
        mid_row,
        text="Position & Zero",
        bg=PANEL_BG,
        fg=FG,
        font=panel_font,
        padx=4,
        pady=2,
        bd=2,
        relief="solid",
    )
    pos_zero_box.pack(side="left", fill="both", expand=True)

    left_col = tk.Frame(pos_zero_box, bg=PANEL_BG)
    left_col.pack(side="left", fill="both", expand=True, padx=(0, 6))

    tk.Label(
        left_col,
        text="Current Position",
        bg=PANEL_BG,
        fg="#FFD54A",
        font=panel_font,
    ).pack(anchor="w", pady=(0, 2))

    dro_frame = tk.Frame(left_col, bg="#171717", bd=1, relief="solid")
    dro_frame.pack(fill="x", padx=(0, 1), pady=(0, 3))

    dro_axes = [
        ("X", app.machine_pos_x_text),
        ("Y", app.machine_pos_y_text),
        ("Z", app.machine_pos_z_text),
        ("A", app.machine_pos_a_text),
        ("B", app.machine_pos_b_text),
    ]

    for idx, (axis_name, pos_var) in enumerate(dro_axes):
        row = idx // 3
        col = idx % 3

        cell = tk.Frame(dro_frame, bg="#171717", padx=5, pady=2)
        cell.grid(row=row, column=col, sticky="nsew")

        tk.Label(
            cell,
            text=axis_name,
            bg="#171717",
            fg="#AAAAAA",
            font=pos_axis_font,
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            cell,
            textvariable=pos_var,
            bg="#171717",
            fg="#FFD54A",
            font=pos_font,
            width=4,
            anchor="w",
        ).pack(anchor="w")

    for c in range(3):
        dro_frame.grid_columnconfigure(c, weight=1)

    right_col = tk.Frame(pos_zero_box, bg=PANEL_BG)
    right_col.pack(side="left", fill="both", expand=True, padx=(6, 0))

    tk.Label(
        right_col,
        text="Set Work Zero",
        bg=PANEL_BG,
        fg="#FFD54A",
        font=panel_font,
    ).pack(anchor="w", pady=(0, 2))

    zero_frame = tk.Frame(right_col, bg=PANEL_BG)
    zero_frame.pack(fill="x")

    zero_frame.grid_columnconfigure(0, weight=1)
    zero_frame.grid_columnconfigure(1, weight=1)

    def set_work_zero_x():
        app._send_line("G10 L20 P1 X0")
        app.after(50, lambda: app.ctrl.send_realtime(b"?"))

    def set_work_zero_y():
        app._send_line("G10 L20 P1 Y0")
        app.after(50, lambda: app.ctrl.send_realtime(b"?"))

    def set_work_zero_z():
        app._send_line("G10 L20 P1 Z0")
        app.after(50, lambda: app.ctrl.send_realtime(b"?"))

    def set_work_zero_a():
        app._send_line("G10 L20 P1 A0")
        app.after(50, lambda: app.ctrl.send_realtime(b"?"))

    def set_work_zero_b():
        app._send_line("G10 L20 P1 B0")
        app.after(50, lambda: app.ctrl.send_realtime(b"?"))

    def set_work_zero_all():
        app._send_line("G10 L20 P1 X0 Y0 Z0 A0 B0")
        app.after(50, lambda: app.ctrl.send_realtime(b"?"))

    tk.Button(
        zero_frame,
        text="Set X Zero",
        command=set_work_zero_x,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=0,
    ).grid(row=0, column=0, padx=2, pady=2, sticky="ew")

    tk.Button(
        zero_frame,
        text="Set Y Zero",
        command=set_work_zero_y,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=0,
    ).grid(row=1, column=0, padx=2, pady=2, sticky="ew")

    tk.Button(
        zero_frame,
        text="Set Z Zero",
        command=set_work_zero_z,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=0,
    ).grid(row=2, column=0, padx=2, pady=2, sticky="ew")

    tk.Button(
        zero_frame,
        text="Set A Zero",
        command=set_work_zero_a,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=0,
    ).grid(row=0, column=1, padx=2, pady=2, sticky="ew")

    tk.Button(
        zero_frame,
        text="Set B Zero",
        command=set_work_zero_b,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=0,
    ).grid(row=1, column=1, padx=2, pady=2, sticky="ew")

    zero_frame.grid_rowconfigure(2, minsize=1)

    tk.Button(
        zero_frame,
        text="Set All Zero",
        command=set_work_zero_all,
        bg=BTN_YELLOW,
        fg=BTN_YELLOW_FG,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        font=default_font,
        bd=1,
        relief="raised",
        pady=0,
    ).grid(row=2, column=1, padx=2, pady=2, sticky="ew")

    # =====================================================
    # RIGHT: HOME AXIS
    # =====================================================
    home_box = tk.LabelFrame(
        right,
        text="Home Axis",
        bg=PANEL_BG,
        fg=FG,
        font=panel_font,
        padx=4,
        pady=4,
        bd=2,
        relief="solid",
    )
    home_box.pack(fill="x", pady=(4, 0))

    home_frame = tk.Frame(home_box, bg=PANEL_BG)
    home_frame.pack(fill="x")

    home_buttons = [
        ("Home X", "$HX"),
        ("Home Y", "$HY"),
        ("Home Z", "$HZ"),
        ("Home A", "$HA"),
        ("Home B", "$HB"),
    ]

    for col, (label, cmd) in enumerate(home_buttons):
        tk.Button(
            home_frame,
            text=label,
            command=lambda c=cmd: app._send_line(c),
            bg=BTN_BLUE,
            fg=BTN_BLUE_FG,
            activebackground=BTN_PRESSED,
            activeforeground="#000000",
            font=default_font,
            height=1,
            bd=1,
            relief="raised",
            pady=0,
        ).grid(row=0, column=col, padx=1, pady=(1,4), sticky="ew")

    for col in range(5):
        home_frame.grid_columnconfigure(col, weight=1)