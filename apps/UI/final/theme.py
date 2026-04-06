from tkinter import ttk

# =========================
# COLORS
# =========================
BG = "#1E1E1E"
PANEL_BG = "#2A2A2A"
FG = "#F5F5F5"

ENTRY_BG = "#F2F2F2"
ENTRY_FG = "#111111"

CONSOLE_BG = "#111111"
CONSOLE_FG = "#F5F5F5"

BTN_NEUTRAL = "#D9D9D9"
BTN_NEUTRAL_FG = "#111111"
BTN_BLUE = "#4EA1FF"
BTN_BLUE_FG = "#111111"
BTN_GREEN = "#5FD16F"
BTN_GREEN_FG = "#111111"
BTN_YELLOW = "#FFD54A"
BTN_YELLOW_FG = "#111111"
BTN_ORANGE = "#FFB347"
BTN_ORANGE_FG = "#111111"
BTN_RED = "#FF6B6B"
BTN_RED_FG = "#111111"

BTN_PRESSED = "#666666"

# =========================
# THEME SETUP
# =========================
def apply_theme(root):
    style = ttk.Style(root)

    # Use consistent cross-platform theme
    style.theme_use("clam")

    default_font = ("Arial", 8, "bold")

    # -------------------------
    # Base widgets
    # -------------------------
    style.configure(
        "TLabel",
        font=default_font,
        background=BG,
        foreground=FG,
    )

    style.configure(
        "TButton",
        font=default_font,
        padding=3,
    )

    style.configure(
        "TEntry",
        font=default_font,
        fieldbackground=ENTRY_BG,
        foreground=ENTRY_FG,
    )

    style.configure(
        "TCombobox",
        font=default_font,
        fieldbackground=ENTRY_BG,
        background=ENTRY_BG,
        foreground=ENTRY_FG,
    )

    style.configure(
        "TCheckbutton",
        background=BG,
        foreground=FG,
        font=default_font,
    )

    # -------------------------
    # NOTEBOOK (tabs)
    # -------------------------
    style.configure(
        "TNotebook",
        background=BG,
        borderwidth=0,
    )

    style.configure(
        "TNotebook.Tab",
        padding=(8, 3),
        font=default_font,
    )

    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", PANEL_BG),
            ("!selected", BTN_NEUTRAL),
        ],
        foreground=[
            ("selected", FG),
            ("!selected", "#111111"),
        ],
    )