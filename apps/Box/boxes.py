import math
from Box.dieline import Dieline, polygon_edges
from Cardboard.material import thickness_compensation
from Box.edges import classify_edges


def rect(x1, x2, y1, y2):
    return [(x1, y1), (x1, y2), (x2, y2), (x2, y1), (x1, y1)]


def _taper_relief_flap(px1, px2, y_hinge, h, inset, relief_v=None, up=True):
    s = 1 if up else -1
    w = px2 - px1

    inset = min(inset, 0.20 * w)

    if relief_v is None:
        relief_v = inset
    relief_v = min(relief_v, 0.40 * h)

    return [
        (px1, y_hinge),
        (px1 + inset, y_hinge + s * relief_v),
        (px1 + inset, y_hinge + s * h),
        (px2 - inset, y_hinge + s * h),
        (px2 - inset, y_hinge + s * relief_v),
        (px2, y_hinge),
        (px1, y_hinge),
    ]


def _pt_key(p, ndigits=6):
    return (round(p[0], ndigits), round(p[1], ndigits))


def _edge_key_from_points(p, q, ndigits=6):
    a = _pt_key(p, ndigits)
    b = _pt_key(q, ndigits)
    return tuple(sorted((a, b)))


def rebuild_edges_and_reclassify(dl):
    """
    Rebuild edges from dl.cuts and classify by duplicate count.

    - knife_edges: segments that appear once
    - shared_edges: segments that appear more than once
    """
    dl.edges = []
    for poly in dl.cuts:
        dl.edges.extend(polygon_edges(poly))

    buckets = {}
    for e in dl.edges:
        p, q = e.p1, e.p2
        k = _edge_key_from_points(p, q)
        buckets.setdefault(k, []).append(e)

    knife = []
    shared = []

    for group in buckets.values():
        if len(group) == 1:
            knife.append(group[0])
        else:
            shared.extend(group)

    dl.debug["knife_edges"] = knife
    dl.debug["shared_edges"] = shared


def rotate_90_dieline(dl, clockwise=False):
    """
    Rotate EVERYTHING in the dieline by 90° around the dieline center.
    Use this to align a box strip to machine feed orientation.

    clockwise=False  -> +90°
    clockwise=True   -> -90°
    """
    pts = []

    for poly in dl.cuts:
        pts.extend(poly)

    for a, b in dl.creases:
        pts.append(a)
        pts.append(b)

    if not pts:
        return dl

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    cx = 0.5 * (xmin + xmax)
    cy = 0.5 * (ymin + ymax)

    def rot(p):
        x, y = p
        dx = x - cx
        dy = y - cy

        if clockwise:
            return (cx + dy, cy - dx)
        else:
            return (cx - dy, cy + dx)

    dl.cuts = [[rot(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(rot(a), rot(b)) for (a, b) in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {
            k: [rot(p) for p in poly]
            for k, poly in dl.debug["panels"].items()
        }

    rebuild_edges_and_reclassify(dl)
    return dl


def orient_dieline_for_x_feed(dl):
    """
    Machine convention:
    - X = feed direction
    - Y = gantry width
    - box strip progression should live in Y

    Since generator currently lays strip progression in X,
    rotate 90° to align for machine execution.
    """
    return rotate_90_dieline(dl, clockwise=False)


def gen_RSC(dim, material, tooling):
    dl = Dieline()

    T = material.thickness
    NA = T * 0.5

    W = dim["W"]
    L = dim["L"]
    Hc = dim["H"]

    dl.debug["design_intent"] = {"L": L, "W": W, "H": Hc}

    panel_w = [
        W + 2 * NA,
        L + 2 * NA,
        W + 2 * NA,
        L + 2 * NA,
    ]

    names = ["side1", "front", "side2", "back"]

    dl.debug["panel_roles"] = {
        "front": "L",
        "back": "L",
        "side1": "W",
        "side2": "W",
    }

    x = [0]
    for w in panel_w:
        x.append(x[-1] + w)

    panels = {}
    for i, n in enumerate(names):
        poly = rect(x[i], x[i + 1], 0, Hc)
        panels[n] = poly
        dl.cuts.append(poly)

    h_compensated = (W + 2 * NA) / 2
    flap_h = [h_compensated] * 4

    inset = material.thickness / 2.0
    relief_v = material.thickness

    for i in range(4):
        px1, px2 = x[i], x[i + 1]
        h = flap_h[i]

        top = _taper_relief_flap(
            px1, px2,
            y_hinge=Hc,
            h=h,
            inset=inset,
            relief_v=relief_v,
            up=True
        )
        dl.cuts.append(top)

        bot = _taper_relief_flap(
            px1, px2,
            y_hinge=0,
            h=h,
            inset=inset,
            relief_v=relief_v,
            up=False
        )
        dl.cuts.append(bot)

    GLUE_W = 18
    ch = 3
    glue_flap = [
        (x[0] - GLUE_W, ch),
        (x[0] - GLUE_W, Hc - ch),
        (x[0], Hc),
        (x[0], 0),
        (x[0] - GLUE_W, ch),
    ]
    dl.cuts.append(glue_flap)

    for xi in x[1:-1]:
        dl.creases.append(((xi, 0), (xi, Hc)))

    dl.creases.append(((x[0], 0), (x[0], Hc)))
    dl.creases.append(((x[0], 0), (x[-1], 0)))
    dl.creases.append(((x[0], Hc), (x[-1], Hc)))

    dl.debug["panels"] = panels
    rebuild_edges_and_reclassify(dl)

    print(f"RSC Generated: Total Width {x[-1]:.1f}mm | Flap Height {h_compensated:.1f}mm")
    return dl


def rotate_180_dieline(dl):
    """
    Rotate EVERYTHING in the dieline by 180° around the dieline center.
    """
    pts = []

    for poly in dl.cuts:
        for p in poly:
            pts.append(p)

    for a, b in dl.creases:
        pts.append(a)
        pts.append(b)

    if not pts:
        return dl

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    cx = (xmin + xmax) * 0.5
    cy = (ymin + ymax) * 0.5

    def rot(p):
        x, y = p
        return (2 * cx - x, 2 * cy - y)

    dl.cuts = [[rot(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(rot(a), rot(b)) for (a, b) in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {
            k: [rot(p) for p in poly]
            for k, poly in dl.debug["panels"].items()
        }

    rebuild_edges_and_reclassify(dl)
    return dl


def normalize_to_origin(dl):
    pts = []

    for poly in dl.cuts:
        pts.extend(poly)
    for a, b in dl.creases:
        pts.append(a)
        pts.append(b)

    min_x = min(p[0] for p in pts)
    min_y = min(p[1] for p in pts)

    dx = -min_x if min_x < 0 else 0
    dy = -min_y if min_y < 0 else 0

    if dx == 0 and dy == 0:
        return

    def shift(p):
        return (p[0] + dx, p[1] + dy)

    dl.cuts = [[shift(p) for p in poly] for poly in dl.cuts]
    dl.creases = [(shift(a), shift(b)) for a, b in dl.creases]

    if "panels" in dl.debug:
        dl.debug["panels"] = {
            k: [shift(p) for p in poly]
            for k, poly in dl.debug["panels"].items()
        }

    rebuild_edges_and_reclassify(dl)


def _rounded_tuck(px1, px2, y, h, r=9.0, up=True, steps=12):
    s = 1 if up else -1
    y2 = y + s * h

    xL, xR = px1, px2
    r = min(r, (xR - xL) * 0.495, h * 0.99)

    pts = []

    pts.append((xL, y))
    pts.append((xL, y2 - s * r))

    cxL = xL + r
    cy = y2 - s * r
    a0, a1 = (math.pi, math.pi / 2) if up else (math.pi, 3 * math.pi / 2)
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        pts.append((cxL + r * math.cos(a), cy + r * math.sin(a)))

    pts.append((xR - r, y2))

    cxR = xR - r
    a0, a1 = (math.pi / 2, 0) if up else (3 * math.pi / 2, 2 * math.pi)
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        pts.append((cxR + r * math.cos(a), cy + r * math.sin(a)))

    pts.append((xR, y2 - s * r))
    pts.append((xR, y))

    return pts


def _panel_crown_tuck(px1, px2, y_hinge, W, up=True, steps=64, ry_frac=0.42, shoulder_frac=0.10):
    s = 1 if up else -1

    panel_w = px2 - px1
    cx = 0.5 * (px1 + px2)

    rx = 0.5 * panel_w
    ry = ry_frac * W
    shoulder = shoulder_frac * W

    cy = y_hinge + s * (shoulder + ry)

    a0, a1 = (math.pi, 0) if up else (math.pi, 2 * math.pi)

    pts = [(px1, y_hinge), (px1, y_hinge + s * shoulder)]
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    pts += [(px2, y_hinge + s * shoulder), (px2, y_hinge)]

    return pts


def _ste_dust_flap(
    px1, px2, y, h,
    relief_edge="left",
    relief_h=None,
    relief_run=3.0,
    shoulder_w=6.0,
    top_frac=0.55,
    up=True
):
    s = 1 if up else -1
    hinge_y = y
    base_y = hinge_y

    top_y = y + s * h
    w = px2 - px1

    if relief_h is None:
        relief_h = h * 0.30

    relief_h = min(relief_h, h * 0.45)
    relief_run = min(relief_run, w * 0.15)

    shoulder_w = max(shoulder_w, relief_run * 1.5)

    top_w = w * top_frac
    top_w = min(top_w, w - relief_run - shoulder_w)
    top_w = max(top_w, w * 0.35)

    rise = relief_run * 0.75

    if relief_edge == "left":
        x0, x1 = px1, px2
        return [
            (x0, base_y),
            (x0, base_y + s * relief_h),
            (x0 + relief_run, base_y + s * (relief_h + rise)),
            (x0 + relief_run + shoulder_w, top_y),
            (x0 + relief_run + shoulder_w + top_w, top_y),
            (x1, base_y),
            (x0, base_y),
        ]

    else:
        x0, x1 = px2, px1
        return [
            (x0, base_y),
            (x0, base_y + s * relief_h),
            (x0 - relief_run, base_y + s * (relief_h + rise)),
            (x0 - relief_run - shoulder_w, top_y),
            (x0 - relief_run - shoulder_w - top_w, top_y),
            (x1, base_y),
            (x0, base_y),
        ]


def _edge_endpoints(e):
    for a, b in (("a", "b"), ("p1", "p2"), ("u", "v"), ("start", "end")):
        if hasattr(e, a) and hasattr(e, b):
            return getattr(e, a), getattr(e, b)
    raise AttributeError(f"Edge object has unknown endpoint attributes: {type(e)}")


def _drop_knife_edges_on_line(
    edges,
    y=None,
    x=None,
    panel_span=None,
    frac=0.5,
    tol=1e-6
):
    assert panel_span is not None, "panel_span is required for proportional filtering"

    kept = []
    cutoff = panel_span * frac

    for e in edges:
        p, q = _edge_endpoints(e)

        on_y = y is not None and abs(p[1] - y) < tol and abs(q[1] - y) < tol
        on_x = x is not None and abs(p[0] - x) < tol and abs(q[0] - x) < tol

        if (on_y or on_x) and e.length() >= cutoff:
            continue

        kept.append(e)

    return kept


def add_tuck_turn_in(
    dl,
    xL, xR,
    y_top,
    turn_in=18.0,
    r=9.0,
    up=True,
    slit_clear=0.0
):
    s = 1 if up else -1

    y_fold = y_top - s * turn_in

    x_end_L = xL + r + slit_clear
    x_end_R = xR - r - slit_clear

    if x_end_R <= x_end_L:
        mid = 0.5 * (xL + xR)
        x_end_L = mid - 1.0
        x_end_R = mid + 1.0

    dl.creases.append(((x_end_L, y_fold), (x_end_R, y_fold)))

    cut_L = [(xL, y_fold), (x_end_L, y_fold)]
    cut_R = [(x_end_R, y_fold), (xR, y_fold)]

    dl.cuts.append(cut_L)
    dl.cuts.append(cut_R)


def gen_STE(dim, material, tooling, glue_side="right"):
    assert glue_side in ("left", "right")

    dl = Dieline()

    T = material.thickness
    NA = T * 0.5

    L = dim["L"]
    W = dim["W"]
    H = dim["H"]

    TURN_IN = 18.0
    R_TUCK = 9.0

    tuck_h = max(W * 0.45, TURN_IN + 25.0)
    dust_h = W * 0.38

    GLUE_W = 16
    CHAMFER = 3

    RELIEF_H = 5
    SHOULDER_W = 6.0
    TOP_FRAC = 0.9
    RELIEF_RUN = 3

    panel_w = [
        W + 2 * NA,
        L + 2 * NA,
        W + 2 * NA,
        L + 2 * NA,
    ]

    names = ["back", "sideL", "front", "sideR"]
    roles = {"front": "tuck", "sideL": "dust", "sideR": "dust", "back": "plain"}

    x = [0]
    for w in panel_w:
        x.append(x[-1] + w)

    panels = {}
    for i, n in enumerate(names):
        poly = rect(x[i], x[i + 1], 0, H)
        panels[n] = poly
        dl.cuts.append(poly)

    dl.debug["panel_roles"] = {
        "front": "L",
        "back": "L",
        "sideL": "W",
        "sideR": "W",
    }
    dl.debug["panels"] = panels

    back_i = names.index("back")
    fold_x = x[back_i]

    glue = [
        (fold_x - GLUE_W, CHAMFER),
        (fold_x - GLUE_W, H - CHAMFER),
        (fold_x, H),
        (fold_x, 0),
        (fold_x - GLUE_W, CHAMFER),
    ]
    dl.cuts.append(glue)

    for i, n in enumerate(names):
        px1, px2 = x[i], x[i + 1]

        if roles[n] == "tuck":
            for up in (True, False):
                y_hinge = H if up else 0
                xL = px1
                xR = px2

                flap = _rounded_tuck(xL, xR, y_hinge, tuck_h, r=R_TUCK, up=up)
                dl.cuts.append(flap)

                y_top = y_hinge + (tuck_h if up else -tuck_h)

                add_tuck_turn_in(
                    dl,
                    xL=xL,
                    xR=xR,
                    y_top=y_top,
                    turn_in=TURN_IN,
                    r=R_TUCK,
                    up=up,
                    slit_clear=0.0
                )

        elif roles[n] == "dust":
            relief_edge = "left" if n == "sideL" else "right"

            for up in (True, False):
                flap = _ste_dust_flap(
                    px1, px2,
                    H if up else 0,
                    dust_h,
                    relief_edge=relief_edge,
                    relief_h=RELIEF_H,
                    relief_run=RELIEF_RUN,
                    shoulder_w=SHOULDER_W,
                    top_frac=TOP_FRAC,
                    up=up
                )
                dl.cuts.append(flap)

    for xi in x[1:-1]:
        dl.creases.append(((xi, 0), (xi, H)))

    dl.creases.append(((fold_x, 0), (fold_x, H)))
    dl.creases.append(((x[0], H), (x[-1], H)))
    dl.creases.append(((x[0], 0), (x[-1], 0)))

    rebuild_edges_and_reclassify(dl)

    knife = dl.debug["knife_edges"]
    shared = dl.debug["shared_edges"]

    panel_span = x[-1] - x[0]
    knife = _drop_knife_edges_on_line(knife, y=H, panel_span=panel_span, frac=0.95)
    knife = _drop_knife_edges_on_line(knife, y=0, panel_span=panel_span, frac=0.95)

    dl.debug["knife_edges"] = knife
    dl.debug["shared_edges"] = shared
    dl.debug["roles"] = roles

    print("STE edges:", len(dl.edges), "knife:", len(knife), "shared:", len(shared))

    if glue_side == "right":
        rotate_180_dieline(dl)

        knife = dl.debug["knife_edges"]
        shared = dl.debug["shared_edges"]

        panel_span = x[-1] - x[0]
        knife = _drop_knife_edges_on_line(knife, y=H, panel_span=panel_span, frac=0.95)
        knife = _drop_knife_edges_on_line(knife, y=0, panel_span=panel_span, frac=0.95)

        dl.debug["knife_edges"] = knife
        dl.debug["shared_edges"] = shared

    return dl


def gen_OTE(dim, material, tooling):
    """
    Overlap Tuck End (OTE) — arc overlap lids (your reference)

    BODY STRIP (left -> right):  front(L), side1(W), back(L), side2(W)
    FLAPS (total 9):
      - front: 2 tuck (top/bot) + 1 side dust (left)  => 3
      - side1: 2 dust (top/bot)                       => 2
      - back:  2 tuck (top/bot)                       => 2
      - side2: 2 dust (top/bot) with relief           => 2
    """
    dl = Dieline()

    EX = tooling.EX
    L = dim["L"]
    W = dim["W"]
    H = dim["H"]

    tuck_h = max(0.55 * W, 25.0)
    overlap = max(min(0.18 * W, 20.0), 8.0)
    tuck_other_h = max(tuck_h - overlap, 10.0)
    dust_h = min(0.35 * W, 0.80 * tuck_other_h)

    R_TUCK_MAIN = min(max(0.45 * tuck_h, 18.0), 0.48 * L)
    R_TUCK_OTHER = min(max(0.35 * tuck_other_h, 8.0), 0.45 * L, 26.0)

    front_side_dust_w = dust_h

    RELIEF_H = max(0.08 * W, 4.0)
    RELIEF_RUN = max(0.05 * W, 3.0)
    SHOULDER_W = max(2.0 * RELIEF_RUN, 6.0)
    TOP_FRAC = 0.90

    panel_w = [L, W, L, W]
    names = ["front", "side1", "back", "side2"]

    dl.debug["panel_roles"] = {
        "front": "L",
        "back": "L",
        "side1": "W",
        "side2": "W",
    }

    x = [0.0]
    for w in panel_w:
        x.append(x[-1] + w)

    panels = {}
    for i, n in enumerate(names):
        poly = rect(x[i], x[i + 1], 0, H)
        panels[n] = poly
        dl.cuts.append(poly)

    dl.debug["panels"] = panels

    for i, n in enumerate(names):
        px1, px2 = x[i], x[i + 1]

        if n == "front":
            for up in (True, False):
                flap = _panel_crown_tuck(
                    px1, px2,
                    y_hinge=H if up else 0,
                    W=W,
                    up=up,
                    ry_frac=0.42,
                    shoulder_frac=0.10
                )
                dl.cuts.append(flap)

        elif n == "back":
            for up in (True, False):
                y_hinge = H if up else 0
                flap = _rounded_tuck(px1, px2, y_hinge, tuck_other_h, r=R_TUCK_OTHER, up=up)
                dl.cuts.append(flap)

        elif n == "side1":
            for up in (True, False):
                y0 = H if up else 0
                s = 1 if up else -1
                y1 = y0 + s * dust_h
                flap = [
                    (px1 + EX, y0),
                    (px1 + EX, y1),
                    (px2 - EX, y1),
                    (px2 - EX, y0),
                    (px1 + EX, y0),
                ]
                dl.cuts.append(flap)

        elif n == "side2":
            for up in (True, False):
                flap = _ste_dust_flap(
                    px1 + EX, px2 - EX,
                    H if up else 0,
                    dust_h,
                    relief_edge="right",
                    relief_h=RELIEF_H,
                    relief_run=RELIEF_RUN,
                    shoulder_w=SHOULDER_W,
                    top_frac=TOP_FRAC,
                    up=up
                )
                dl.cuts.append(flap)

    front_left_x = x[names.index("front")]
    x0 = front_left_x - front_side_dust_w
    x1 = front_left_x

    side_dust = rect(x0, x1, 0, H)
    dl.cuts.append(side_dust)

    for xi in x[1:-1]:
        dl.creases.append(((xi, 0), (xi, H)))

    dl.creases.append(((x[0], H), (x[-1], H)))
    dl.creases.append(((x[0], 0), (x[-1], 0)))
    dl.creases.append(((front_left_x, 0), (front_left_x, H)))

    normalize_to_origin(dl)
    rebuild_edges_and_reclassify(dl)

    return dl