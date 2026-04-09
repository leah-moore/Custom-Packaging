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
    panel_font = ("Arial", 8, "bold")
    button_font = ("Arial", 10, "bold")
    pos_font = ("Courier", 11, "bold")
    pos_axis_font = ("Arial", 8, "bold")
    mode_font = ("Arial", 9, "bold")

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=2, pady=2)

    content = tk.Frame(main, bg=BG)
    content.pack(fill="both", expand=True, pady=(6, 0))

    left = tk.Frame(content, bg=BG, width=290)
    left.pack(side="left", fill="both", padx=(0, 4))

    right = tk.Frame(content, bg=BG)
    right.pack(side="left", fill="both", expand=True)

    app.machine_buttons = []
    app.output_buttons = []

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
        pady=3,
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
        ).grid(row=row_idx, column=0, sticky="w", pady=(4, 2))

        row = tk.Frame(parent_box, bg=PANEL_BG, height=28)
        row.grid(row=row_idx + 1, column=0, sticky="w", padx=(3, 0), pady=(0, 4))
        row.grid_propagate(False)

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
                pady=2,
                highlightthickness=0,
                bd=0,
            ).pack(side="left", padx=4)

        return row_idx + 2

    row = 0

    row = make_radio_row(settings_box, row, "Jog Step (mm)", app.jog_step_var, ["0.5", "1", "10", "20"])
    row = make_radio_row(settings_box, row, "Jog Feed (mm/min)", app.jog_feed_var, ["100", "500", "1000", "2000"])
    row = make_radio_row(settings_box, row, "A Step (deg) - Creaser", app.a_rot_step_var, ["1", "5", "45", "90"])
    row = make_radio_row(settings_box, row, "B Step (deg) - Cutter", app.b_rot_step_var, ["1", "5", "45", "90"])
    row = make_radio_row(settings_box, row, "Roller Step (mm)", app.roller_step_var, ["1", "5", "10", "20"])
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
        pady=8,
        bd=2,
        relief="solid",
    )
    ctrl_box.pack(fill="x")

    btn_frame = tk.Frame(ctrl_box, bg=PANEL_BG)
    btn_frame.pack(fill="both", expand=True)

    machine_buttons = [
        ("Home", app._home, BTN_BLUE, BTN_BLUE_FG),
        ("Unlock", app._unlock, BTN_YELLOW, BTN_YELLOW_FG),
        ("Hold", app._hold, BTN_ORANGE, BTN_ORANGE_FG),
        ("Resume", app._resume, BTN_GREEN, BTN_GREEN_FG),
        ("Reset", app._reset, BTN_RED, BTN_RED_FG),
        ("Stop Jog", app._cancel_jog, BTN_ORANGE, BTN_ORANGE_FG),
    ]

    for idx, (label, fn, color, fgcolor) in enumerate(machine_buttons):
        row = idx // 2
        col = idx % 2

        btn = tk.Button(
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
            pady=2,
        )
        btn.grid(row=row, column=col, sticky="ew", padx=3, pady=2)
        app.machine_buttons.append(btn)

    btn_frame.grid_columnconfigure(0, weight=1)
    btn_frame.grid_columnconfigure(1, weight=1)

    estop_label = tk.Label(
        btn_frame,
        text="E-STOP",
        bg="#CC0000",
        fg="#FFFFFF",
        font=("Arial", 12, "bold"),
        pady=10,
        relief="raised",
        bd=3,
    )
    estop_label.grid(row=3, column=0, columnspan=2, sticky="ew", padx=3, pady=(4, 2))

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
            bd=2,
            relief="raised",
            padx=4,
            pady=1,
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
    # LIMIT INDICATORS (Lower Right of Jog Box)
    # =====================================================
    # We place these in row 2, under the A/B rotary buttons.
    # Row 2, Col 1 is occupied by Y-, so Col 8-9 is wide open.
    limit_container = tk.Frame(jog_box, bg=PANEL_BG)
    limit_container.grid(row=2, column=8, columnspan=2, sticky="se", padx=3, pady=6)

    tk.Label(
        limit_container,
        text="Limits:",
        bg=PANEL_BG,
        fg="#FFD54A",
        font=("Arial", 8, "bold"),
    ).pack(side="left", padx=(0, 4))

    app.limit_labels = {}
    for axis in ["X", "Y", "Z", "A", "B"]:
        lbl = tk.Label(
            limit_container,
            text=axis,
            bg="#333333",  # Darker gray for 'off' state
            fg="#777777",
            width=2,
            font=("Arial", 8, "bold"),
            relief="solid",
            bd=1,
        )
        lbl.pack(side="left", padx=1)
        app.limit_labels[axis] = lbl

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
        pady=2,
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
        # STOP any motion when switching modes
        if hasattr(app, "_cancel_jog"):
            app._cancel_jog(send_hold=False)
        if hasattr(app, "_stop_roller_jog"):
            app._stop_roller_jog()

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
        pady=5,
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
        pady=5,
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

    app.jog_status_var = tk.StringVar(value="JOG: IDLE")

    jog_status_label = tk.Label(
        text_col,
        textvariable=app.jog_status_var,
        bg=PANEL_BG,
        fg="#AAAAAA",
        font=("Arial", 9, "bold"),
        anchor="w",
    )
    jog_status_label.pack(anchor="w")

    tk.Label(
        text_col,
        text="STEP (tap) = step move   •   CONT (tap) = start/stop jog",
        bg=PANEL_BG,
        fg="#AAAAAA",
        font=default_font,
        anchor="w",
    ).pack(anchor="w")

    tk.Label(
        text_col,
        text="Roller is Pi-controlled (does not affect GRBL axes)",
        bg=PANEL_BG,
        fg="#777777",
        font=("Arial", 7),
        anchor="w",
    ).pack(anchor="w", pady=(2, 0))

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
        pady=2,
        bd=2,
        relief="solid",
        width=220,
    )
    outputs_box.pack(side="left", fill="y", padx=(0, 4))
    outputs_box.pack_propagate(False)

    outputs_box.grid_columnconfigure(0, weight=1)
    outputs_box.grid_columnconfigure(1, weight=1)

    btn = tk.Button(
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
    )
    btn.grid(row=0, column=0, padx=3, pady=(2, 1), sticky="ew")
    app.output_buttons.append(btn)

    btn = tk.Button(
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
    )
    btn.grid(row=0, column=1, padx=3, pady=(2, 1), sticky="ew")
    app.output_buttons.append(btn)

    outputs_box.grid_rowconfigure(1, minsize=4)

    tk.Label(
        outputs_box,
        text="Spindle Speed (RPM)",
        bg=PANEL_BG,
        fg=FG,
        font=default_font,
    ).grid(row=2, column=0, columnspan=2, padx=3, pady=(2, 0), sticky="w")

    speed_row = tk.Frame(outputs_box, bg=PANEL_BG, height=28)
    speed_row.grid(row=3, column=0, columnspan=2, padx=3, pady=(1, 3), sticky="w")
    speed_row.grid_propagate(False)

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
            pady=2,
            highlightthickness=0,
            bd=0,
        ).pack(side="left", padx=2)

    btn = tk.Button(
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
    )
    btn.grid(row=4, column=0, padx=3, pady=(2, 3), sticky="ew")
    app.output_buttons.append(btn)

    btn = tk.Button(
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
    )
    btn.grid(row=4, column=1, padx=3, pady=(2, 3), sticky="ew")
    app.output_buttons.append(btn)

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

    # ---- top area: DRO on left, WPos/MPos on right ----
    top_row = tk.Frame(pos_zero_box, bg=PANEL_BG)
    top_row.pack(fill="x", pady=(2, 4))

    top_row.grid_columnconfigure(0, weight=1)
    top_row.grid_columnconfigure(1, weight=0)

    left_col = tk.Frame(top_row, bg=PANEL_BG)
    left_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))

    right_col = tk.Frame(top_row, bg=PANEL_BG)
    right_col.grid(row=0, column=1, sticky="ne", padx=(4, 0))

    tk.Label(
        left_col,
        text="Current Position",
        bg=PANEL_BG,
        fg="#FFD54A",
        font=panel_font,
    ).pack(anchor="w", pady=(0, 2))

    dro_frame = tk.Frame(left_col, bg=PANEL_BG)
    dro_frame.pack(fill="x", expand=True)

    dro_axes = [
        ("X", app.work_pos_x_text, app.machine_pos_x_text),
        ("Y", app.work_pos_y_text, app.machine_pos_y_text),
        ("Z", app.work_pos_z_text, app.machine_pos_z_text),
        ("A", app.work_pos_a_text, app.machine_pos_a_text),
        ("B", app.work_pos_b_text, app.machine_pos_b_text),
    ]

    for idx, (axis_name, w_var, m_var) in enumerate(dro_axes):
        cell = tk.Frame(dro_frame, bg="#171717", padx=8, pady=6)
        cell.grid(row=0, column=idx, sticky="nsew", padx=2, pady=2)

        tk.Label(
            cell,
            text=axis_name,
            bg="#171717",
            fg="#AAAAAA",
            font=pos_axis_font,
            anchor="w",
        ).pack(anchor="w")

        # Work Position (Yellow)
        tk.Label(
            cell,
            textvariable=w_var,
            bg="#171717",
            fg="#FFD54A",
            font=("Courier", 9, "bold"), # Increased font size slightly for readability
            width=9,                     # INCREASED from 5 to 9
            anchor="e",                  # Keeps numbers right-justified
        ).pack(anchor="e", fill="x")     # Changed to anchor="e" to match the text flow

        # Machine Position (Grey)
        tk.Label(
            cell,
            textvariable=m_var,
            bg="#171717",
            fg="#777777",
            font=("Courier", 10),
            width=9,                     # INCREASED from 5 to 9
            anchor="e",                  # Keeps numbers right-justified
        ).pack(anchor="e", fill="x")     # Changed to anchor="e" to match the text flow

    for c in range(5):
        dro_frame.grid_columnconfigure(c, weight=1)

    # ---- zero buttons on right ----
    
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
        pady=1,
        width=12,
    ).grid(row=0, column=0, padx=8, pady=5, sticky="ew")

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
        pady=1,
        width=14,
    ).grid(row=1, column=0, padx=8, pady=5, sticky="ew")

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
        pady=1,
        width=14,
    ).grid(row=2, column=0, padx=8, pady=5, sticky="ew")

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
        pady=1,
        width=14,
    ).grid(row=0, column=1, padx=8, pady=5, sticky="ew")

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
        pady=1,
        width=14,
    ).grid(row=1, column=1, padx=8, pady=5, sticky="ew")

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
        pady=1,
        width=14,
    ).grid(row=2, column=1, padx=8, pady=5, sticky="ew")

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