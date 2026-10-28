"""Parse free-text ingredient lines like "1 (15 oz) can black beans, drained"."""

import re
from dataclasses import dataclass

UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅙": "1/6",
}

UNIT_ALIASES = {
    "tsp": ["t", "tsp", "tsps", "teaspoon", "teaspoons"],
    "tbsp": ["T", "tbs", "tbsp", "tbsps", "tablespoon", "tablespoons"],
    "cup": ["c", "cup", "cups"],
    "oz": ["oz", "ounce", "ounces"],
    "fl oz": ["floz"],
    "lb": ["lb", "lbs", "pound", "pounds"],
    "g": ["g", "gram", "grams"],
    "kg": ["kg", "kilogram", "kilograms"],
    "ml": ["ml", "milliliter", "milliliters"],
    "l": ["l", "liter", "liters", "litre", "litres"],
    "clove": ["clove", "cloves"],
    "can": ["can", "cans"],
    "jar": ["jar", "jars"],
    "pkg": ["pkg", "pkgs", "package", "packages", "pack", "packs", "packet", "packets", "envelope", "envelopes"],
    "bunch": ["bunch", "bunches"],
    "head": ["head", "heads"],
    "slice": ["slice", "slices"],
    "pinch": ["pinch", "pinches"],
    "gal": ["gal", "gallon", "gallons"],
    "qt": ["qt", "quart", "quarts"],
    "pt": ["pt", "pint", "pints"],
    "stick": ["stick", "sticks"],
    "bag": ["bag", "bags"],
    "box": ["box", "boxes"],
    "bottle": ["bottle", "bottles"],
    "dozen": ["dozen"],
}
_UNIT_LOOKUP = {alias.lower(): unit for unit, aliases in UNIT_ALIASES.items() for alias in aliases if alias != "T"}

PREP_WORDS = {
    "fresh", "freshly", "minced", "chopped", "sliced", "large", "medium", "small", "finely",
    "roughly", "thinly", "peeled", "packed", "softened", "melted", "boneless", "skinless",
}
TRAILING_PHRASES = re.compile(r"\b(to taste|or to taste|as needed|for serving|for garnish|optional)\b.*$", re.I)

_NUM = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?"
_QTY_RE = re.compile(rf"^({_NUM})(?:\s*(?:-|–|to)\s*({_NUM}))?\s*")


@dataclass
class ParsedIngredient:
    raw: str
    name: str
    name_key: str
    qty: float | None
    unit: str | None


def to_float(text: str) -> float | None:
    text = text.strip()
    try:
        if " " in text:
            whole, frac = text.split(None, 1)
            return float(whole) + to_float(frac)
        if "/" in text:
            num, den = text.split("/")
            return float(num) / float(den) if float(den) else None
        return float(text)
    except (ValueError, TypeError):
        return None


def expand_fractions(s: str) -> str:
    for char, frac in UNICODE_FRACTIONS.items():
        s = re.sub(rf"(\d){char}", rf"\1 {frac}", s)
        s = s.replace(char, frac)
    return s


def normalize_unit(token: str) -> str | None:
    token = token.strip().rstrip(".")
    if token == "T":
        return "tbsp"
    return _UNIT_LOOKUP.get(token.lower())


def unit_words() -> list[str]:
    """Every word normalize_unit recognizes, lowercase, for splitting amounts off lines in the browser."""
    return sorted(_UNIT_LOOKUP)


def name_key(name: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    out = []
    for w in words:
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("oes") and len(w) > 4:
            w = w[:-2]
        elif w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 2:
            w = w[:-1]
        out.append(w)
    return " ".join(out)


def parse_line(line: str, *, strip_prep: bool = True) -> ParsedIngredient:
    raw = " ".join(line.split())
    s = expand_fractions(raw)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = " ".join(s.split())

    qty = None
    m = _QTY_RE.match(s)
    if m:
        qty = to_float(m.group(2) or m.group(1))
        s = s[m.end():]

    unit = None
    first, _, rest = s.partition(" ")
    if first and (u := normalize_unit(first)):
        unit = u
        s = rest

    name = s.split(",", 1)[0]
    name = TRAILING_PHRASES.sub("", name)
    name = re.sub(r"^of\s+", "", name.strip(), flags=re.I)
    words = name.split()
    while strip_prep and words and words[0].lower() in PREP_WORDS:
        words.pop(0)
    name = " ".join(words).strip(" .;:-/")
    return ParsedIngredient(raw=raw, name=name, name_key=name_key(name), qty=qty, unit=unit)
