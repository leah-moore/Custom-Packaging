import os
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from ..theme import (
    BG,
    PANEL_BG,
    FG,
    BTN_NEUTRAL,
    BTN_NEUTRAL_FG,
    BTN_GREEN,
    BTN_GREEN_FG,
    BTN_PRESSED,
    BTN_BLUE,
    BTN_BLUE_FG,
)
from ..components.slats_cam_logic import draw_library_preview

from apps.Filler.grid_slats import compute_worldgrid_from_stl, explode_polys


def build_slats_tab(app, parent) -> None:
    default_font = ("Arial", 8, "bold")
    title_font = ("Arial", 9, "bold")
    info_font = ("Arial", 8, "bold")
    switch_font = ("Arial", 9, "bold")

    for child in parent.winfo_children():
        child.destroy()

    if not hasattr(app, "n_xy_var"):
        app.n_xy_var = tk.StringVar(value="5")
    if not hasattr(app, "n_xz_var"):
        app.n_xz_var = tk.StringVar(value="5")
    if not hasattr(app, "slat_info_text"):
        app.slat_info_text = tk.StringVar(value="Mesh: (none) | Total: 0")
    if not hasattr(app, "slats_view_var"):
        app.slats_view_var = tk.StringVar(value="gallery")
    if not hasattr(app, "slats_side_var"):
        app.slats_side_var = tk.StringVar(value="both")
    if not hasattr(app, "slats_labels_var"):
        app.slats_labels_var = tk.BooleanVar(value=True)

    # storage dedicated to this tab
    app.slats_data = getattr(app, "slats_data", None)
    app.slats_gallery_records = []
    app.slats_assembly_records = []

    def _set_view():
        mode = app.slats_view_var.get()
        if mode == "gallery":
            gallery_frame.lift()
        else:
            grid_frame.lift()

    def _collect_gallery_records(data: dict):
        out = []
        out.extend(data.get("xy_right_records", []))
        out.extend(data.get("xy_left_records", []))
        out.extend(data.get("xz_right_records", []))
        out.extend(data.get("xz_left_records", []))
        return out

    def _filter_by_side(records):
        mode = app.slats_side_var.get()
        if mode == "both":
            return list(records)
        return [r for r in records if str(getattr(r, "side", "")).lower() == mode]

    def _refresh_info():
        data = app.slats_data or {}

        mesh_name = "(none)"
        if getattr(app, "scan_mesh_path", None):
            mesh_name = os.path.basename(str(app.scan_mesh_path))

        xy_right = list(data.get("xy_right_records", [])) if isinstance(data, dict) else []
        xy_left = list(data.get("xy_left_records", [])) if isinstance(data, dict) else []
        xz_right = list(data.get("xz_right_records", [])) if isinstance(data, dict) else []
        xz_left = list(data.get("xz_left_records", [])) if isinstance(data, dict) else []

        mode = app.slats_side_var.get()

        if mode == "right":
            xy_r, xy_l = len(xy_right), 0
            xz_r, xz_l = len(xz_right), 0
        elif mode == "left":
            xy_r, xy_l = 0, len(xy_left)
            xz_r, xz_l = 0, len(xz_left)
        else:
            xy_r, xy_l = len(xy_right), len(xy_left)
            xz_r, xz_l = len(xz_right), len(xz_left)

        # ✅ SAFE filtered records
        records = list(getattr(app, "slats_gallery_records", []) or [])
        filtered_records = _filter_by_side(records)

        # ✅ EMPTY STATE (prevents crashes + looks clean)
        if not filtered_records:
            app.slat_info_text.set(f"Mesh: {mesh_name}  |  No slats generated")
            return

        # ✅ MAIN DISPLAY
        app.slat_info_text.set(
            f"Mesh: {mesh_name}  |  View: {app.slats_view_var.get().title()}  |  "
            f"Side: {app.slats_side_var.get().title()}  |  "
            f"Total: {len(filtered_records)}  |  XY R/L {xy_r}/{xy_l}  |  XZ R/L {xz_r}/{xz_l}"
        )

    def _clear_gallery_tiles():
        for child in gallery_inner.winfo_children():
            child.destroy()

    def _draw_gallery():
        _clear_gallery_tiles()

        records = _filter_by_side(list(app.slats_gallery_records or []))
        if not records:
            empty = tk.Label(
                gallery_inner,
                text="No slats generated",
                bg="#101010",
                fg="#CCCCCC",
                font=("Arial", 18, "bold"),
            )
            empty.pack(expand=True, fill="both", pady=40)
            return

        cols = 3

        for idx, rec in enumerate(records):
            row = idx // cols
            col = idx % cols

            tile = tk.Frame(
                gallery_inner,
                bg="#101010",
                bd=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground="#2A2A2A",
            )
            tile.grid(row=row, column=col, padx=10, pady=10, sticky="n")

            canvas = tk.Canvas(
                tile,
                width=260,
                height=190,
                bg="#101010",
                highlightthickness=0,
            )

            canvas.create_text(
                252, 182,
                text=_assembly_label(rec),
                fill="#B8B8B8",
                font=("Arial", 8, "bold"),
                anchor="se",
            )
            canvas.pack(padx=8, pady=8)

            draw_library_preview(canvas, rec)

        for c in range(cols):
            gallery_inner.grid_columnconfigure(c, weight=1)

        gallery_canvas.update_idletasks()
        gallery_canvas.configure(scrollregion=gallery_canvas.bbox("all"))

    def _assembly_label(rec):
        fam = str(getattr(rec, "family", "UNK")).upper()
        idx = int(getattr(rec, "index", 0)) + 1
        side = str(getattr(rec, "side", "")).lower()

        if side == "right":
            return f"{fam}-{idx}R"
        if side == "left":
            return f"{fam}-{idx}L"
        return f"{fam}-{idx}"

    def _plot_geom_outline_3d(ax, rec, fixed_value, mode, color, lw=1.4):
        geom = getattr(rec, "geom", None)
        if geom is None or getattr(geom, "is_empty", True):
            return

        side_mode = app.slats_side_var.get()
        rec_side = str(getattr(rec, "side", "")).lower()

        bx0, _, bx1, _ = geom.bounds
        cx = 0.5 * (bx0 + bx1)

        for poly in explode_polys(geom):
            x, y = poly.exterior.xy
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)

            # Presentation flips:
            # - in LEFT mode, flip left slats so they face us
            # - in RIGHT mode, flip right slats so they face us
            # - in BOTH mode, leave real positions alone so the box forms correctly
            if side_mode == "left" and rec_side == "left":
                x = (2.0 * cx) - x
            elif side_mode == "right" and rec_side == "right":
                x = (2.0 * cx) - x

            if mode == "xy":
                ax.plot(x, y, np.full_like(x, fixed_value), color=color, lw=lw)
            else:  # xz
                ax.plot(x, np.full_like(x, fixed_value), y, color=color, lw=lw)

    def _label_geom_3d(ax, rec):
        geom = getattr(rec, "geom", None)
        if geom is None or getattr(geom, "is_empty", True):
            return

        bx0, by0, bx1, by1 = geom.bounds
        cx = 0.5 * (bx0 + bx1)
        cy = 0.5 * (by0 + by1)
        plane_value = float(getattr(rec, "plane_value", 0.0))
        axis = str(getattr(rec, "plane_axis", "")).upper()

        text = _assembly_label(rec)

        if axis == "Z":
            ax.text(cx, cy, plane_value + 2.0, text, color="#E8E8E8", fontsize=7, ha="center")
        elif axis == "Y":
            ax.text(cx, plane_value + 2.0, cy, text, color="#E8E8E8", fontsize=7, ha="center")

    def _set_axes_equal(ax, verts):
        verts = np.asarray(verts, dtype=float)
        mins = verts.min(axis=0)
        maxs = verts.max(axis=0)
        center = 0.5 * (mins + maxs)
        span = max(maxs - mins)
        if span <= 0:
            span = 1.0
        span *= 0.42

        ax.set_xlim(center[0] - span, center[0] + span)
        ax.set_ylim(center[1] - span, center[1] + span)
        ax.set_zlim(center[2] - span, center[2] + span)
        ax.set_box_aspect([1, 1, 1])

    def _draw_grid():
        ax = app.slats_grid_ax
        fig = app.slats_grid_figure

        ax.clear()
        ax.set_facecolor("#111111")
        fig.patch.set_facecolor("#111111")
        fig.subplots_adjust(left=0.00, right=1.00, bottom=0.00, top=1.00)

        data = app.slats_data or {}
        if not data:
            ax.text2D(
                0.5, 0.5,
                "No slats generated",
                transform=ax.transAxes,
                color="#CCCCCC",
                ha="center",
                va="center",
                fontsize=14,
            )
            ax.set_axis_off()
            app.slats_grid_canvas.draw_idle()
            return

        xy_right = _filter_by_side(data.get("xy_right_records", []))
        xy_left = _filter_by_side(data.get("xy_left_records", []))
        xz_right = _filter_by_side(data.get("xz_right_records", []))
        xz_left = _filter_by_side(data.get("xz_left_records", []))

        verts_accum = []

        for rec in xy_right:
            _plot_geom_outline_3d(ax, rec, float(rec.plane_value), "xy", "#66CCFF", lw=1.8)
            if app.slats_labels_var.get():
                _label_geom_3d(ax, rec)
            for poly in explode_polys(rec.geom):
                pts = np.asarray(poly.exterior.coords)
                verts_accum.append(
                    np.column_stack([pts[:, 0], pts[:, 1], np.full(len(pts), float(rec.plane_value))])
                )

        for rec in xy_left:
            _plot_geom_outline_3d(ax, rec, float(rec.plane_value), "xy", "#2FA4FF", lw=1.2)
            if app.slats_labels_var.get():
                _label_geom_3d(ax, rec)
            for poly in explode_polys(rec.geom):
                pts = np.asarray(poly.exterior.coords)
                verts_accum.append(
                    np.column_stack([pts[:, 0], pts[:, 1], np.full(len(pts), float(rec.plane_value))])
                )

        for rec in xz_right:
            _plot_geom_outline_3d(ax, rec, float(rec.plane_value), "xz", "#FFAA33", lw=1.8)
            if app.slats_labels_var.get():
                _label_geom_3d(ax, rec)
            for poly in explode_polys(rec.geom):
                pts = np.asarray(poly.exterior.coords)
                verts_accum.append(
                    np.column_stack([pts[:, 0], np.full(len(pts), float(rec.plane_value)), pts[:, 1]])
                )

        for rec in xz_left:
            _plot_geom_outline_3d(ax, rec, float(rec.plane_value), "xz", "#FF8833", lw=1.2)
            if app.slats_labels_var.get():
                _label_geom_3d(ax, rec)
            for poly in explode_polys(rec.geom):
                pts = np.asarray(poly.exterior.coords)
                verts_accum.append(
                    np.column_stack([pts[:, 0], np.full(len(pts), float(rec.plane_value)), pts[:, 1]])
                )

        if verts_accum:
            all_verts = np.vstack(verts_accum)
            _set_axes_equal(ax, all_verts)

        ax.view_init(elev=20, azim=-45)
        ax.grid(False)

        try:
            ax.xaxis.pane.fill = False
            ax.yaxis.pane.fill = False
            ax.zaxis.pane.fill = False
            ax.set_axis_off()
        except Exception:
            pass

        app.slats_grid_canvas.draw_idle()

    def _redraw_current_view():
        _refresh_info()
        _draw_gallery()
        _draw_grid()

    def _use_mesh():
        mesh_path = None

        if getattr(app, "photogrammetry_mesh_path", None):
            mesh_path = app.photogrammetry_mesh_path
        elif getattr(app, "scan_mesh_path", None):
            mesh_path = app.scan_mesh_path

        if not mesh_path:
            messagebox.showerror("Slats", "No mesh loaded. Load or save a mesh first.")
            return

        mesh_path = Path(mesh_path)
        app.scan_mesh_path = str(mesh_path)
        _refresh_info()

    def _generate():
        if not getattr(app, "scan_mesh_path", None):
            messagebox.showerror("Slats", "No mesh selected. Click 'Use Mesh' first.")
            return

        try:
            n_xy = int(float(app.n_xy_var.get()))
            n_xz = int(float(app.n_xz_var.get()))
        except Exception:
            messagebox.showerror("Slats", "Invalid XY/XZ counts.")
            return

        if n_xy <= 0 or n_xz <= 0:
            messagebox.showerror("Slats", "Counts must be greater than zero.")
            return

        try:
            data = compute_worldgrid_from_stl(
                app.scan_mesh_path,
                n_xy=n_xy,
                n_xz=n_xz,
            )
        except Exception as exc:
            messagebox.showerror("Slats", f"Failed to generate slats:\n{exc}")
            return

        app.slats_data = data
        app.slats_gallery_records = _collect_gallery_records(data)
        app.slats_assembly_records = app.slats_gallery_records[:]

        _redraw_current_view()

    def _clear():
        app.slats_data = None
        app.slats_gallery_records = []
        app.slats_assembly_records = []
        _redraw_current_view()

    def _on_gallery_configure(_event=None):
        gallery_canvas.configure(scrollregion=gallery_canvas.bbox("all"))
        try:
            gallery_canvas.itemconfigure(gallery_window, width=gallery_canvas.winfo_width())
        except Exception:
            pass

    def _on_gallery_mousewheel(event):
        try:
            gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    main = tk.Frame(parent, bg=BG)
    main.pack(fill="both", expand=True, padx=4, pady=4)

    top_bar = tk.LabelFrame(
        main,
        text="Slats",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        padx=6,
        pady=4,
        bd=2,
        relief="solid",
    )
    top_bar.pack(fill="x", pady=(0, 6))

    left_controls = tk.Frame(top_bar, bg=PANEL_BG)
    left_controls.pack(side="left")

    tk.Button(
        left_controls,
        text="Use Mesh",
        command=_use_mesh,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(0, 6), pady=2)

    tk.Button(
        left_controls,
        text="Generate",
        command=_generate,
        bg=BTN_GREEN,
        fg=BTN_GREEN_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(0, 6), pady=2)

    tk.Button(
        left_controls,
        text="Clear",
        command=_clear,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        font=default_font,
        width=10,
        activebackground=BTN_PRESSED,
        activeforeground="#000000",
        bd=2,
        relief="raised",
    ).pack(side="left", padx=(0, 10), pady=2)

    tk.Label(left_controls, text="XY:", bg=PANEL_BG, fg=FG, font=default_font).pack(side="left", padx=(0, 3))
    ttk.Combobox(
        left_controls,
        textvariable=app.n_xy_var,
        values=[str(i) for i in range(1, 13)],
        state="readonly",
        width=4,
    ).pack(side="left", padx=(0, 8))

    tk.Label(left_controls, text="XZ:", bg=PANEL_BG, fg=FG, font=default_font).pack(side="left", padx=(0, 3))
    ttk.Combobox(
        left_controls,
        textvariable=app.n_xz_var,
        values=[str(i) for i in range(1, 13)],
        state="readonly",
        width=4,
    ).pack(side="left", padx=(0, 10))

    tk.Radiobutton(
        left_controls,
        text="Gallery",
        variable=app.slats_view_var,
        value="gallery",
        indicatoron=0,
        command=_set_view,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=switch_font,
        width=10,
        padx=8,
        pady=2,
    ).pack(side="left", padx=(0, 4))

    tk.Radiobutton(
        left_controls,
        text="3D Grid",
        variable=app.slats_view_var,
        value="grid",
        indicatoron=0,
        command=_set_view,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=switch_font,
        width=10,
        padx=8,
        pady=2,
    ).pack(side="left", padx=(0, 10))

    tk.Radiobutton(
        left_controls,
        text="Both",
        variable=app.slats_side_var,
        value="both",
        indicatoron=0,
        command=_redraw_current_view,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=switch_font,
        width=6,
        padx=6,
        pady=2,
    ).pack(side="left", padx=(0, 2))

    tk.Radiobutton(
        left_controls,
        text="Right",
        variable=app.slats_side_var,
        value="right",
        indicatoron=0,
        command=_redraw_current_view,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=switch_font,
        width=6,
        padx=6,
        pady=2,
    ).pack(side="left", padx=2)

    tk.Radiobutton(
        left_controls,
        text="Left",
        variable=app.slats_side_var,
        value="left",
        indicatoron=0,
        command=_redraw_current_view,
        bg=BTN_NEUTRAL,
        fg=BTN_NEUTRAL_FG,
        selectcolor=BTN_BLUE,
        font=switch_font,
        width=6,
        padx=6,
        pady=2,
    ).pack(side="left", padx=2)

    tk.Checkbutton(
        left_controls,
        text="Labels",
        variable=app.slats_labels_var,
        command=_draw_grid,
        bg=PANEL_BG,
        fg=FG,
        activebackground=PANEL_BG,
        activeforeground=FG,
        selectcolor="#101010",
        font=default_font,
        bd=0,
        highlightthickness=0,
    ).pack(side="left", padx=(10, 0))

    
    right_info = tk.Frame(top_bar, bg=PANEL_BG)
    right_info.pack(side="right", fill="x", expand=True)

    tk.Label(
        right_info,
        textvariable=app.slat_info_text,
        bg=PANEL_BG,
        fg="#CCCCCC",
        font=info_font,
        anchor="e",
        justify="right",
    ).pack(side="right", padx=(8, 0), pady=2)

    view_host = tk.Frame(main, bg=BG)
    view_host.pack(fill="both", expand=True)

    # Gallery frame
    gallery_frame = tk.LabelFrame(
        view_host,
        text="Gallery",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        bd=2,
        relief="solid",
    )
    gallery_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

    gallery_canvas = tk.Canvas(
        gallery_frame,
        bg="#101010",
        highlightthickness=0,
    )
    gallery_canvas.pack(side="left", fill="both", expand=True)

    gallery_scroll = tk.Scrollbar(
        gallery_frame,
        orient="vertical",
        command=gallery_canvas.yview,
    )
    gallery_scroll.pack(side="right", fill="y")

    gallery_canvas.configure(yscrollcommand=gallery_scroll.set)

    gallery_inner = tk.Frame(gallery_canvas, bg="#101010")
    gallery_window = gallery_canvas.create_window((0, 0), window=gallery_inner, anchor="nw")

    gallery_inner.bind("<Configure>", _on_gallery_configure)
    gallery_canvas.bind("<Configure>", _on_gallery_configure)
    gallery_canvas.bind_all("<MouseWheel>", _on_gallery_mousewheel, add="+")

    # 3D grid frame
    grid_frame = tk.LabelFrame(
        view_host,
        text="3D Grid",
        bg=PANEL_BG,
        fg=FG,
        font=title_font,
        bd=2,
        relief="solid",
    )
    grid_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

    app.slats_grid_figure = Figure(figsize=(8, 6), dpi=100)
    app.slats_grid_figure.patch.set_facecolor("#111111")
    app.slats_grid_ax = app.slats_grid_figure.add_subplot(111, projection="3d")
    app.slats_grid_ax.set_facecolor("#111111")

    app.slats_grid_canvas = FigureCanvasTkAgg(app.slats_grid_figure, master=grid_frame)
    app.slats_grid_canvas.get_tk_widget().pack(fill="both", expand=True)

    _set_view()
    _redraw_current_view()