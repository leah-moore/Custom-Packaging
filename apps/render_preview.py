import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.lines import Line2D


# -------------------------------------------------
# DIMENSION HELPER
# -------------------------------------------------
def draw_dimension(ax, p1, p2, offset=(0, 0), text="", color="black"):
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = offset

    # normalize arrow direction
    xs = [x1, x2]
    ys = [y1, y2]

    x_start, x_end = min(xs), max(xs)
    y_start, y_end = min(ys), max(ys)

    ax.annotate(
        "",
        xy=(x_start + dx, y_start + dy),
        xytext=(x_end + dx, y_end + dy),
        arrowprops=dict(
            arrowstyle="<->",
            lw=1.5,
            color=color,
            shrinkA=0,
            shrinkB=0,
        ),
    )

    ax.text(
        (x_start + x_end) / 2 + dx,
        (y_start + y_end) / 2 + dy,
        text,
        ha="center",
        va="bottom",
        fontsize=11,
        weight="bold",
        color=color,
        backgroundcolor="white",
    )


# -------------------------------------------------
# CORE PREVIEW RENDERER (RETURNS FIGURE)
# -------------------------------------------------

# -------------------------------------------------
# CORE PREVIEW RENDERER (RETURNS FIGURE)
# -------------------------------------------------
def render_preview_figure(dl):
    fig, ax = plt.subplots(figsize=(14, 7))

    # -------------------------------------------------
    # PANEL / FLAP FILLS
    # -------------------------------------------------
    for poly in dl.cuts:
        patch = MplPolygon(
            poly,
            closed=True,
            facecolor="#e9edff",
            edgecolor="none",
            alpha=0.65,
        )
        ax.add_patch(patch)

    # -------------------------------------------------
    # CUT LINES (Knife)
    # -------------------------------------------------
    for e in dl.debug.get("knife_edges", []):
        p, q = e.p1, e.p2
        ax.plot(
            [p[0], q[0]],
            [p[1], q[1]],
            color="#0047ff",
            linewidth=2.2,
        )

    # -------------------------------------------------
    # CREASE LINES (Score)
    # -------------------------------------------------
    for (a, b) in dl.creases:
        ax.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            color="#ff3b30",
            linewidth=2.0,
        )

    # -------------------------------------------------
    # DIMENSIONS (PREVIEW ONLY)
    # -------------------------------------------------
    panel_roles = dl.debug.get("panel_roles", {})
    panels = dl.debug.get("panels", {})
    
    # Check for Design Intent (the "Inner" clean dimensions)
    intent = dl.debug.get("design_intent", {})

    if panels:
        # --- L Dimension (Length) ---
        if "front" in panels:
            front = panels["front"]
            # Robustly find min/max to avoid index-order issues
            xs = [p[0] for p in front]
            ys = [p[1] for p in front]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            y_mid = (y1 + y2) / 2

            # Use intent if available, otherwise fallback to measured int
            text_L = f"{intent.get('L', int(abs(x2 - x1)))} mm"
            text_H = f"{intent.get('H', int(abs(y2 - y1)))} mm"

            draw_dimension(
                ax, (x1, y_mid), (x2, y_mid),
                offset=(0, 35),
                text=text_L,
                color="#0047ff",
            )

            draw_dimension(
                ax, (x1, y1), (x1, y2),
                offset=(-35, 0),
                text=text_H,
                color="#0047ff",
            )

        # --- W Dimension (Width) ---
        # Loop through panels to find side widths
        for name, role in panel_roles.items():
            if role == "W" and name in panels:
                poly = panels[name]
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                x1, x2 = min(xs), max(xs)
                y1, y2 = min(ys), max(ys)
                y_mid = (y1 + y2) / 2

                text_W = f"{intent.get('W', int(abs(x2 - x1)))} mm"

                draw_dimension(
                    ax, (x1, y_mid), (x2, y_mid),
                    offset=(0, -45),
                    text=text_W,
                    color="#0047ff",
                )
                # Removed 'break' so all Width panels can be labeled if needed
                # but breaking here keeps the UI clean with just one label.
                break

    # -------------------------------------------------
    # FORMATTING
    # -------------------------------------------------
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("2D Dieline (Compensated Geometry)", fontsize=12, weight="bold")

    legend_elements = [
        Line2D([0], [0], color="#0047ff", lw=2.5, label="CUT (Knife Line)"),
        Line2D([0], [0], color="#ff3b30", lw=2.5, label="CREASE (Score Line)"),
    ]

    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=2,
        frameon=True
    )

    fig.tight_layout()
    return fig

# -------------------------------------------------
# SCRIPT / DEBUG WRAPPER (BACKWARD COMPATIBLE)
# -------------------------------------------------
def render_preview(dl, filename="preview.png"):
    fig = render_preview_figure(dl)
    fig.savefig(filename, dpi=200)
    plt.show()
