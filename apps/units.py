# units.py
def parse_mm(value):
    from re import match

    s = value.strip().lower()
    m = match(r"([\d.]+)\s*(mm|cm|in)?", s)
    if not m:
        raise ValueError(f"Invalid dimension: {value}")

    v = float(m.group(1))
    u = m.group(2) or "mm"

    if u == "mm":
        return v
    if u == "cm":
        return v * 10
    if u == "in":
        return v * 25.4

    raise ValueError(u)
