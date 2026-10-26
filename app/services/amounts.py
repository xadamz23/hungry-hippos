"""Amounts are lists of {"qty": float|None, "unit": str|None}, one entry per distinct unit."""

import re

from app.services.ingredients import expand_fractions, to_float, normalize_unit

Amount = dict

NICE_FRACTIONS = {0.125: "⅛", 0.25: "¼", 1 / 3: "⅓", 0.5: "½", 2 / 3: "⅔", 0.75: "¾"}
PLURAL_UNITS = {"cup": "cups", "can": "cans", "clove": "cloves", "jar": "jars", "bunch": "bunches",
                "head": "heads", "slice": "slices", "stick": "sticks", "bag": "bags", "box": "boxes",
                "bottle": "bottles"}


def merge(a: list[Amount], b: list[Amount]) -> list[Amount]:
    out = [dict(x) for x in a]
    for item in b:
        match = next((x for x in out if x["unit"] == item["unit"]), None)
        if match is None:
            out.append(dict(item))
        elif item["qty"] is not None:
            match["qty"] = item["qty"] if match["qty"] is None else match["qty"] + item["qty"]
    return out


def scale(amounts: list[Amount], factor: float) -> list[Amount]:
    return [{"qty": None if a["qty"] is None else a["qty"] * factor, "unit": a["unit"]} for a in amounts]


def _fmt_qty(q: float) -> str:
    whole = int(q)
    frac = q - whole
    if abs(frac) < 0.01:
        return str(whole)
    for value, glyph in NICE_FRACTIONS.items():
        if abs(frac - value) < 0.01:
            return f"{whole}{glyph}" if whole else glyph
    return f"{q:.2f}".rstrip("0").rstrip(".")


def fmt(amounts: list[Amount]) -> str:
    parts = []
    for a in amounts:
        if a["qty"] is None:
            continue
        unit = a["unit"]
        if unit and a["qty"] > 1 + 0.01:
            unit = PLURAL_UNITS.get(unit, unit)
        parts.append(f"{_fmt_qty(a['qty'])} {unit}" if unit else _fmt_qty(a["qty"]))
    return " + ".join(parts)


def parse_amount_text(text: str) -> list[Amount]:
    out: list[Amount] = []
    for part in text.split("+"):
        part = expand_fractions(part.strip())
        if not part:
            continue
        m = re.match(r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(.*)$", part)
        if not m:
            continue
        unit_text = m.group(2).strip()
        unit = normalize_unit(unit_text) if unit_text else None
        out.append({"qty": to_float(m.group(1)), "unit": unit or (unit_text or None)})
    return out
