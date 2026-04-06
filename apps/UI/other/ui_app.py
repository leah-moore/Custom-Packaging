import tkinter as tk
from tkinter import ttk

from Box.boxes import gen_RSC, gen_STE
from Cardboard.material import Material, Tooling
from render_preview import render_preview_figure

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class PackagingUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Custom Packaging")
        self.root.geometry("1100x650")

        self._build_layout()
        self._build_inputs()

        self.canvas = None

    # -------------------------------------------------
    # Layout
    # -------------------------------------------------
    def _build_layout(self):
        self.left = ttk.Frame(self.root, padding=12)
        self.left.pack(side="left", fill="y")

        self.right = ttk.Frame(self.root, padding=12)
        self.right.pack(side="right", fill="both", expand=True)

    # -------------------------------------------------
    # Inputs
    # -------------------------------------------------
    def _build_inputs(self):
        self.length = tk.DoubleVar(value=200)
        self.width = tk.DoubleVar(value=150)
        self.height = tk.DoubleVar(value=100)

        self.box_type = tk.StringVar(value="RSC")

        ttk.Label(self.left, text="Length (mm)").pack(anchor="w")
        ttk.Entry(self.left, textvariable=self.length).pack(fill="x")

        ttk.Label(self.left, text="Width (mm)").pack(anchor="w", pady=(8, 0))
        ttk.Entry(self.left, textvariable=self.width).pack(fill="x")

        ttk.Label(self.left, text="Height (mm)").pack(anchor="w", pady=(8, 0))
        ttk.Entry(self.left, textvariable=self.height).pack(fill="x")

        ttk.Label(self.left, text="Box Type").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            self.left,
            textvariable=self.box_type,
            values=["RSC", "STE"],
            state="readonly",
        ).pack(fill="x")

        ttk.Button(
            self.left,
            text="Generate Packaging",
            command=self.generate,
        ).pack(pady=15, fill="x")

    # -------------------------------------------------
    # Generate + Preview
    # -------------------------------------------------
    def generate(self):
        dim = dict(
            L=self.length.get(),
            W=self.width.get(),
            H=self.height.get(),
        )

        material = Material(thickness=0.5)
        tooling = Tooling()

        if self.box_type.get() == "STE":
            dl = gen_STE(dim=dim, material=material, tooling=tooling)
        else:
            dl = gen_RSC(dim=dim, material=material, tooling=tooling)

        fig = render_preview_figure(dl)

        if self.canvas:
            self.canvas.get_tk_widget().destroy()

        self.canvas = FigureCanvasTkAgg(fig, master=self.right)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)


if __name__ == "__main__":
    PackagingUI().root.mainloop()
