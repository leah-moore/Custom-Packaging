import cv2
import numpy as np
import ezdxf
from shapely.geometry import Polygon
from shapely.ops import unary_union

class DxfGenerator:
    def __init__(self, img, x_margin, y_margin):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        _, binary = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)

        coords = cv2.findNonZero(binary)

        x, y, w, h = cv2.boundingRect(coords)

        self.img = img[y+y_margin:y+h-y_margin, x+x_margin:x+w-x_margin]

        self.gray = cv2.cvtColor(self.img, cv2.COLOR_BGR2GRAY)

        self.height, self.width = self.gray.shape[:2]
    
    def get_contours(self, min_area=5000):
        blurred = cv2.medianBlur(self.gray, 5)
        blurred = cv2.GaussianBlur(blurred, (81,81), 1)

        _, thresh = cv2.threshold(blurred,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)

        edges = cv2.Canny(thresh, 100, 170)

        kernel = np.ones((7,7), np.uint8)
        edges_closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            edges_closed,
            cv2.RETR_TREE,
            cv2.CHAIN_APPROX_NONE
        )

        epsilon = 1.0  # adjust for precision

        outline = max(contours, key=cv2.contourArea)
        self.outline = cv2.approxPolyDP(outline, epsilon, True)

        big_contours = [
            c for c in contours
            if cv2.contourArea(c) > min_area
        ]

        big_contours_sorted = sorted(big_contours, key=cv2.contourArea, reverse=True)
        self.big_contours = [cv2.approxPolyDP(c, epsilon, True) for c in big_contours_sorted]
    
    def plot_contours(self):
        self.img_contours = self.img

        cv2.drawContours(
            self.img_contours,
            self.big_contours,  # list of contours
            -1,
            (0, 0, 255),           # red (BGR)
            2                      # thickness
        )
    
    def contours_to_merged_dxf(self, output_path, scale=1.0):
        """
        Merge overlapping contours using Shapely union, then export to DXF and plot.

        Args:
            contours:     List of OpenCV contours (each shape (N, 1, 2))
            output_path:  Path to save the .dxf file
            scale:        Pixels → real world units (e.g. mm)
            image_height: Height of ROI image in pixels (for Y-flip)
        """

        # ── 1. Convert contours → Shapely Polygons ──────────────────────────────
        polygons = []
        for contour in self.big_contours:
            pts = contour.squeeze()
            if pts.ndim < 2 or len(pts) < 3:
                continue  # skip degenerate contours
            poly = Polygon(pts)
            if poly.is_valid:
                polygons.append(poly)
            else:
                polygons.append(poly.buffer(0))  # fix self-intersections

        # ── 2. Merge all overlapping polygons ───────────────────────────────────
        merged = unary_union(polygons)  # returns Polygon or MultiPolygon

        # Normalise to a list of polygons
        if merged.geom_type == "Polygon":
            merged_polys = [merged]
        else:
            merged_polys = list(merged.geoms)  # MultiPolygon

        print(f"Contours before merge: {len(polygons)}")
        print(f"Contours after merge:  {len(merged_polys)}")

        # ── 3. Export to DXF ────────────────────────────────────────────────────
        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()

        def transform(x, y):
            """Pixel coords → DXF coords with Y-flip."""
            dxf_x = x * scale
            dxf_y = (self.height - y) * scale if self.height else y * scale
            return dxf_x, dxf_y

        for i, poly in enumerate(merged_polys):
            # Exterior ring
            pts = [transform(x, y) for x, y in poly.exterior.coords]
            msp.add_lwpolyline(pts, dxfattribs={"closed": True, "layer": "CONTOUR"})

            # Holes (interior rings), if any
            for interior in poly.interiors:
                pts = [transform(x, y) for x, y in interior.coords]
                msp.add_lwpolyline(pts, dxfattribs={"closed": True, "layer": "HOLES"})

        doc.saveas(output_path)


