import svgwrite
import os
import webbrowser


def render(dl, filename="preview.svg"):
    pts = []

    for poly in dl.cuts:
        pts.extend(poly)

    for a, b in dl.creases:
        pts.extend([a, b])

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    w = max_x - min_x
    h = max_y - min_y

    dwg = svgwrite.Drawing(
        filename,
        size=(f"{w}mm", f"{h}mm"),
        viewBox=f"{min_x} {min_y} {w} {h}",
    )

    # ----------------------------
    # STYLE DEFINITIONS
    # ----------------------------
    CUT = {
        "stroke": "black",
        "stroke_width": 1.2,
        "fill": "none"
    }

    CREASE = {
    "stroke": "#0066ff",          # strong blue
    "stroke_width": 1.5,          # thicker than cuts
    "stroke_dasharray": "10,6",   # long dash
    "stroke_opacity": 0.9,
    "fill": "none"
}


    # ----------------------------
    # DRAW CUTS FIRST
    # ----------------------------
    for poly in dl.cuts:
        dwg.add(dwg.polyline(poly, **CUT))

    # ----------------------------
    # DRAW CREASES ON TOP
    # ----------------------------
    for a, b in dl.creases:
        dwg.add(dwg.line(a, b, **CREASE))

    dwg.save()
    webbrowser.open(f"file://{os.path.abspath(filename)}")
