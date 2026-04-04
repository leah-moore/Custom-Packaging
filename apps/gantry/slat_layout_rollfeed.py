from shapely.affinity import translate, rotate

def pack_slats_roll_feed(
    slats,
    gantry_width_x,
    feed_window_y,
    gap_x=5.0,
    gap_y=5.0,
    margin=5.0,
    allow_rotate_90=True,
):
    def max_dim(g):
        bx0, by0, bx1, by1 = g.bounds
        return max(bx1 - bx0, by1 - by0)

    slats = sorted(slats, key=max_dim, reverse=True)

    packed = []

    x_cursor = margin
    y_cursor = margin
    row_height = 0.0

    usable_width = gantry_width_x - 2 * margin
    usable_height = feed_window_y - 2 * margin

    for g in slats:
        bx0, by0, bx1, by1 = g.bounds
        g0 = translate(g, -bx0, -by0)

        w0 = bx1 - bx0
        h0 = by1 - by0

        candidates = []

        # original orientation
        if w0 <= usable_width:
            if h0 > usable_height:
                print(
                    f"[roll-feed] Tall slat ({w0:.1f} × {h0:.1f}) "
                    f"— will cut across feeds"
                )
            candidates.append((g0, w0, h0))

        # rotated
        if allow_rotate_90:
            g90 = rotate(g0, 90, origin=(0, 0), use_radians=False)

            rb0, rb1, rb2, rb3 = g90.bounds
            g90 = translate(g90, -rb0, -rb1)

            w90 = rb2 - rb0
            h90 = rb3 - rb1

            if w90 <= usable_width:
                if h90 > usable_height:
                    print(
                        f"[roll-feed] Tall slat rotated ({w90:.1f} × {h90:.1f}) "
                        f"— will cut across feeds"
                    )
                candidates.append((g90, w90, h90))

        if not candidates:
            raise ValueError(
                f"Part too wide for gantry "
                f"(size {w0:.1f} × {h0:.1f} mm)"
            )

        # choose narrowest
        geom, w, h = min(candidates, key=lambda c: c[1])

        # wrap row
        if x_cursor + w > margin + usable_width:
            x_cursor = margin
            y_cursor += row_height + gap_y
            row_height = 0.0

        # place in positive packing space first
        placed = translate(geom, x_cursor, y_cursor)
        packed.append(placed)

        x_cursor += w + gap_x
        row_height = max(row_height, h)

    return packed


def normalize_to_machine_center(geoms):
    if not geoms:
        raise RuntimeError("No slats were packed — layout returned empty list")

    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)

    cx = 0.5 * (minx + maxx)
    cy = 0.5 * (miny + maxy)

    return [translate(g, -cx, -cy) for g in geoms]