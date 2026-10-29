from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Section, Staple

# Typical Meijer walk order, each with a distinct header color dark enough for white text.
DEFAULT_SECTIONS: list[tuple[str, str]] = [
    ("Produce", "#2E7D32"),
    ("Meat & Seafood", "#C62828"),
    ("Bakery", "#A16207"),
    ("Deli", "#8E24AA"),
    ("Frozen", "#0E7490"),
    ("Alcohol", "#6A1B9A"),
    ("Pop & Gatorade", "#0277BD"),
    ("Pasta & Mexican", "#827717"),
    ("Rice & Asian", "#00796B"),
    ("Soup, Oil & Mayo", "#BF360C"),
    ("Bread & Condiments", "#8D6E00"),
    ("Cereal & Peanut Butter", "#AD1457"),
    ("Spices, Baking & Snacks", "#5D4037"),
    ("Dairy & Eggs", "#1565C0"),
    ("Paper & Laundry", "#455A64"),
    ("Yogurt, Butter & Ritz", "#DB2777"),
    ("Dish & Cleaning", "#3949AB"),
    ("Health & Personal Care", "#4D7C0F"),
    ("Other", "#757575"),
]

# (name, name_key, amounts, section)
DEFAULT_STAPLES: list[tuple[str, str, list[dict], str]] = [
    ("Milk", "milk", [{"qty": 1, "unit": "gal"}], "Dairy & Eggs"),
    ("Eggs", "egg", [{"qty": 1, "unit": "dozen"}], "Dairy & Eggs"),
    ("Bananas", "banana", [{"qty": 1, "unit": "bunch"}], "Produce"),
    ("Bread", "bread", [{"qty": 1, "unit": None}], "Bread & Condiments"),
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
