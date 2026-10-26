from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Section, Staple

# Typical Meijer walk order, each with a distinct header color.
DEFAULT_SECTIONS: list[tuple[str, str]] = [
    ("Produce", "#2E7D32"),
    ("Bakery", "#A16207"),
    ("Deli", "#8E24AA"),
    ("Meat & Seafood", "#C62828"),
    ("Canned & Soup", "#BF360C"),
    ("Pasta & Rice", "#827717"),
    ("International", "#00796B"),
    ("Baking & Spices", "#5D4037"),
    ("Breakfast & Cereal", "#AD1457"),
    ("Snacks & Drinks", "#FF8A65"),
    ("Household", "#455A64"),
    ("Dairy & Eggs", "#1565C0"),
    ("Frozen", "#4FC3F7"),
    ("Other", "#757575"),
]

# (name, name_key, amounts, section)
DEFAULT_STAPLES: list[tuple[str, str, list[dict], str]] = [
    ("Milk", "milk", [{"qty": 1, "unit": "gal"}], "Dairy & Eggs"),
    ("Eggs", "egg", [{"qty": 1, "unit": "dozen"}], "Dairy & Eggs"),
    ("Bananas", "banana", [{"qty": 1, "unit": "bunch"}], "Produce"),
    ("Bread", "bread", [{"qty": 1, "unit": None}], "Bakery"),
]


def ensure_seed(session: Session) -> None:
    if session.scalar(select(Section.id).limit(1)) is not None:
        return
    by_name = {}
    for pos, (name, color) in enumerate(DEFAULT_SECTIONS):
        section = Section(name=name, color=color, position=pos)
        session.add(section)
        by_name[name] = section
    session.flush()
    for pos, (name, key, amounts, section_name) in enumerate(DEFAULT_STAPLES):
        session.add(
            Staple(name=name, name_key=key, amounts=amounts, section_id=by_name[section_name].id, position=pos)
        )
    session.commit()
