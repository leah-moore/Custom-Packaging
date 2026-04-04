import matplotlib
matplotlib.use("TkAgg", force=True)
import matplotlib.pyplot as plt
plt.close("all")

import sys
from pathlib import Path

FILE_PATH = Path(__file__).resolve()
APPS_DIR = FILE_PATH.parents[2]          # .../Custom-Packaging/apps
PROJECT_ROOT = APPS_DIR.parent           # .../Custom-Packaging

sys.path.insert(0, str(APPS_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from Box.boxes import gen_RSC, gen_STE
from Cardboard.material import Material, Tooling
from render_preview import render_preview_figure

import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

# --- REAL IMPORTS ---
from Filler.grid_slats import (
    compute_worldgrid_from_stl,
    plot_geom_outline_3d,
    set_axes_equal,
)

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def mesh_dimensions(mesh):
    mins, maxs = mesh.bounds
    return {
        "L": maxs[0] - mins[0],
        "W": maxs[1] - mins[1],
        "H": maxs[2] - mins[2],
    }

def explode_geom(g):
    if hasattr(g, "geoms"):
        return g.geoms
    return [g]

# -------------------------------------------------
# Paths
# -------------------------------------------------

STL_PREPARED_DIR = Path("data/stl/prepared")
STL_INPUT_DIR = Path("data/stl/input")
DEFAULT_STL = Path("data/stl/prepared/Pitcher_scaled.stl")

# -------------------------------------------------
# UI
# -------------------------------------------------

class ProductPreviewUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Product + Grid Preview")
        self.root.geometry("1300x800")

        self.data = None
        self.canvas3d = None
        self.canvas2d = None
        
        self.n_xy = tk.IntVar(value=3)
        self.n_xz = tk.IntVar(value=3)


        self._build_layout()
        self._build_controls()

        if DEFAULT_STL.exists():
            self.load_stl(DEFAULT_STL)

    # -------------------------------------------------
    # Layout
    # -------------------------------------------------

    def _build_layout(self):
        self.left = ttk.Frame(self.root, padding=6)
        self.left.pack(side="left", fill="y")

        self.right = ttk.Frame(self.root, padding=6)
        self.right.pack(side="right", fill="both", expand=True)

        # --- Grid config: 2x2, all equal ---
        for c in range(2):
            self.right.columnconfigure(c, weight=1, uniform="cols")
        for r in range(2):
            self.right.rowconfigure(r, weight=1, uniform="rows")

        # ---- Top-left: 3D ----
        self.preview3d = ttk.Frame(self.right)
        self.preview3d.grid(row=0, column=0, sticky="nsew")

        # ---- Top-right: Dieline ----
        self.preview_dieline = ttk.Frame(self.right)
        self.preview_dieline.grid(row=0, column=1, sticky="nsew")

        # ---- Bottom-left: XY slats ----
        self.preview_xy = ttk.Frame(self.right)
        self.preview_xy.grid(row=1, column=0, sticky="nsew")

        # ---- Bottom-right: XZ slats ----
        self.preview_xz = ttk.Frame(self.right)
        self.preview_xz.grid(row=1, column=1, sticky="nsew")

        self.canvas3d = None
        self.canvas_dieline = None
        self.canvas_xy = None
        self.canvas_xz = None


    # -------------------------------------------------
    # Controls
    # -------------------------------------------------

    def _build_controls(self):
        ttk.Label(self.left, text="Prepared STL", font=("Helvetica", 10, "bold")).pack(anchor="w")

        self.stl_name = tk.StringVar()
        prepared = sorted(p.name for p in STL_PREPARED_DIR.glob("*.stl"))

        ttk.Combobox(
            self.left,
            textvariable=self.stl_name,
            values=prepared,
            state="readonly",
        ).pack(fill="x")

        ttk.Button(self.left, text="Load Prepared STL", command=self.load_prepared).pack(fill="x", pady=(6, 0))
        ttk.Button(self.left, text="Browse Raw STL…", command=self.browse_raw).pack(fill="x", pady=(10, 0))

        ttk.Separator(self.left).pack(fill="x", pady=12)

        ttk.Label(self.left, text="Object Dimensions (mm)", font=("Helvetica", 10, "bold")).pack(anchor="w")
        self.dim_label = ttk.Label(self.left, text="—")
        self.dim_label.pack(anchor="w", pady=(2, 8))

        ttk.Separator(self.left).pack(fill="x", pady=12)

        self.show_object = tk.BooleanVar(value=True)
        self.show_xy = tk.BooleanVar(value=True)
        self.show_xz = tk.BooleanVar(value=True)

        ttk.Checkbutton(self.left, text="Show Object", variable=self.show_object, command=self.update_view).pack(anchor="w")
        ttk.Checkbutton(self.left, text="Show XY Slats", variable=self.show_xy, command=self.update_view).pack(anchor="w")
        ttk.Checkbutton(self.left, text="Show XZ Slats", variable=self.show_xz, command=self.update_view).pack(anchor="w")

        ttk.Separator(self.left).pack(fill="x", pady=12)
        ttk.Label(self.left, text="Slat Count", font=("Helvetica", 10, "bold")).pack(anchor="w")

        # ---- XY slats ----
        row_xy = ttk.Frame(self.left)
        row_xy.pack(fill="x", pady=4)

        ttk.Label(row_xy, text="XY Slats").pack(side="left")

        ttk.Spinbox(
            row_xy,
            from_=1,
            to=20,
            textvariable=self.n_xy,
            width=6,
            command=self.update_view,
        ).pack(side="right")

        # ---- XZ slats ----
        row_xz = ttk.Frame(self.left)
        row_xz.pack(fill="x", pady=4)

        ttk.Label(row_xz, text="XZ Slats").pack(side="left")

        ttk.Spinbox(
            row_xz,
            from_=1,
            to=20,
            textvariable=self.n_xz,
            width=6,
            command=self.update_view,
        ).pack(side="right")

        ttk.Separator(self.left).pack(fill="x", pady=12)

        ttk.Label(self.left, text="Packaging", font=("Helvetica", 10, "bold")).pack(anchor="w")

        self.box_type = tk.StringVar(value="RSC")
        self.show_dieline = tk.BooleanVar(value=True)

        ttk.Combobox(
            self.left,
            textvariable=self.box_type,
            values=["RSC", "STE"],
            state="readonly",
        ).pack(fill="x", pady=(2, 6))

        ttk.Checkbutton(
            self.left,
            text="Show Dieline",
            variable=self.show_dieline,
            command=self.update_view,
        ).pack(anchor="w")

        ttk.Label(self.left, text="Box Dimensions (mm)", font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(10, 0))

        self.box_L = tk.DoubleVar(value=200)
        self.box_W = tk.DoubleVar(value=150)
        self.box_H = tk.DoubleVar(value=100)

        def box_entry(label, var):
            ttk.Label(self.left, text=label).pack(anchor="w")
            ttk.Entry(self.left, textvariable=var).pack(fill="x")

        box_entry("Length (L)", self.box_L)
        box_entry("Width (W)", self.box_W)
        box_entry("Height (H)", self.box_H)



    # -------------------------------------------------
    # STL loading
    # -------------------------------------------------

    def load_prepared(self):
        if self.stl_name.get():
            self.load_stl(STL_PREPARED_DIR / self.stl_name.get())

    def browse_raw(self):
        path = filedialog.askopenfilename(
            initialdir=STL_INPUT_DIR,
            filetypes=[("STL files", "*.stl")],
        )
        if path:
            self.load_stl(Path(path))

    def load_stl(self, path: Path):
        self.stl_path = path
        self._recompute()
        self.update_view()

    def _generate_dieline(self):
        dim = dict(
            L=self.box_L.get(),
            W=self.box_W.get(),
            H=self.box_H.get(),
        )

        material = Material(thickness=0.5)
        tooling = Tooling()

        if self.box_type.get() == "STE":
            return gen_STE(dim=dim, material=material, tooling=tooling)
        else:
            return gen_RSC(dim=dim, material=material, tooling=tooling)

    # -------------------------------------------------
    # Rendering
    # -------------------------------------------------

    def _recompute(self):
        self.data = compute_worldgrid_from_stl(
            self.stl_path,
            n_xy=self.n_xy.get(),
            n_xz=self.n_xz.get(),
        )

        dims = mesh_dimensions(self.data["mesh"])
        self.dim_label.config(
            text=f"L: {dims['L']:.1f} mm   "
                f"W: {dims['W']:.1f} mm   "
                f"H: {dims['H']:.1f} mm"
        )

    def update_view(self):
        if not hasattr(self, "stl_path"):
            return

        self._recompute()
        if self.data is None:
            return

        mesh     = self.data["mesh"]
        zLevels  = self.data["zLevels"]
        yLevels  = self.data["yLevels"]
        worldXY  = self.data["worldXY"]
        worldXZ  = self.data["worldXZ"]

        # =================================================
        # 3D VIEW
        # =================================================
        fig3d = plt.figure(figsize=(7.5, 6.5))
        ax3d = fig3d.add_subplot(111, projection="3d")
        ax3d.set_title("Object + Interlocking Grid")
        fig3d.subplots_adjust(top=0.88)  # LOWER = lower title


        if self.show_object.get():
            poly = Poly3DCollection(mesh.vertices[mesh.faces], alpha=0.25)
            poly.set_facecolor([0.3, 0.5, 1.0])
            ax3d.add_collection3d(poly)

        if self.show_xy.get():
            for z, geom in zip(zLevels, worldXY):
                if geom and not geom.is_empty:
                    plot_geom_outline_3d(
                        ax3d, geom,
                        fixed_value=float(z),
                        mode="xy",
                        color="red",
                        lw=1.6,
                    )

        if self.show_xz.get():
            for y, geom in zip(yLevels, worldXZ):
                if geom and not geom.is_empty:
                    plot_geom_outline_3d(
                        ax3d, geom,
                        fixed_value=float(y),
                        mode="xz",
                        color="blue",
                        lw=1.6,
                    )

        ax3d.view_init(25, 35)
        set_axes_equal(ax3d, mesh.vertices)
        # ---- clean 3D view (no axes, no grid, no panes) ----
        ax3d.set_axis_off()

        ax3d.xaxis.pane.set_visible(False)
        ax3d.yaxis.pane.set_visible(False)
        ax3d.zaxis.pane.set_visible(False)

        ax3d.xaxis._axinfo["grid"]["linewidth"] = 0
        ax3d.yaxis._axinfo["grid"]["linewidth"] = 0
        ax3d.zaxis._axinfo["grid"]["linewidth"] = 0

        fig3d.tight_layout()

        if self.canvas3d:
            self.canvas3d.get_tk_widget().destroy()

        self.canvas3d = FigureCanvasTkAgg(fig3d, master=self.preview3d)
        self.canvas3d.draw()
        self.canvas3d.get_tk_widget().pack(fill="both", expand=True)

        # =================================================
        # 2D XY SLATS (BOTTOM LEFT)
        # =================================================
        fig_xy, ax_xy = plt.subplots(figsize=(4, 4))

        def draw_layout(ax, geoms, color, title, y_label):
            ax.set_title(title)
            ax.set_aspect("equal", adjustable="box")
            ax.set_xlabel("X (mm)")
            ax.set_ylabel(y_label)
            ax.grid(True, alpha=0.25)

            offset = 0.0
            gap = 15.0

            for g in geoms:
                if g is None or g.is_empty:
                    continue

                bx0, _, bx1, _ = g.bounds
                width = bx1 - bx0

                parts = g.geoms if hasattr(g, "geoms") else [g]
                for p in parts:
                    x, y = p.exterior.xy
                    ax.plot(
                        [xx - bx0 + offset for xx in x],
                        y,
                        color=color,
                        lw=1.4,
                    )

                offset += width + gap


        if self.show_xy.get():
            draw_layout(ax_xy, worldXY, "red", "XY Slats (2D)", "Y (mm)")
        else:
            ax_xy.axis("off")

        fig_xy.tight_layout()

        if self.canvas_xy:
            self.canvas_xy.get_tk_widget().destroy()

        self.canvas_xy = FigureCanvasTkAgg(fig_xy, master=self.preview_xy)
        self.canvas_xy.draw()
        self.canvas_xy.get_tk_widget().pack(fill="both", expand=True)


        # =================================================
        # 2D XZ SLATS (BOTTOM RIGHT)
        # =================================================
        fig_xz, ax_xz = plt.subplots(figsize=(4, 4))

        if self.show_xz.get():
            draw_layout(ax_xz, worldXZ, "blue", "XZ Slats (2D)", "Z (mm)")
        else:
            ax_xz.axis("off")

        fig_xz.tight_layout()

        if self.canvas_xz:
            self.canvas_xz.get_tk_widget().destroy()

        self.canvas_xz = FigureCanvasTkAgg(fig_xz, master=self.preview_xz)
        self.canvas_xz.draw()
        self.canvas_xz.get_tk_widget().pack(fill="both", expand=True)



        # =========================
        # DIELINE PREVIEW (RIGHT)
        # =========================
        if self.show_dieline.get():
            dl = self._generate_dieline()
            if dl:
                fig_dl = render_preview_figure(dl)

                # Make the figure tall and readable
                fig_dl.set_size_inches(6, 10)
                fig_dl.tight_layout()

                if self.canvas_dieline:
                    self.canvas_dieline.get_tk_widget().destroy()

                self.canvas_dieline = FigureCanvasTkAgg(fig_dl, master=self.preview_dieline)
                self.canvas_dieline.draw()

                widget = self.canvas_dieline.get_tk_widget()
                widget.pack(fill="both", expand=True)
        else:
            if self.canvas_dieline:
                self.canvas_dieline.get_tk_widget().destroy()
                self.canvas_dieline = None


        dl = self._generate_dieline()
        print("DIELINE:", dl)

if __name__ == "__main__":
    ProductPreviewUI().root.mainloop()
