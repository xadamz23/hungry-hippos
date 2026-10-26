import pytest

from app.services.ingredients import name_key
from app.services.sections import guess_section, remember, text_color


@pytest.mark.parametrize(
    "name,section",
    [
        ("yellow onions", "Produce"),
        ("ground beef", "Meat & Seafood"),
        ("tomato sauce", "Canned & Soup"),
        ("sour cream", "Dairy & Eggs"),
        ("flour tortillas", "International"),
        ("frozen peas", "Frozen"),
        ("all-purpose flour", "Baking & Spices"),
        ("spaghetti", "Pasta & Rice"),
        ("shredded cheddar cheese", "Dairy & Eggs"),
        ("paper towels", "Household"),
        ("hamburger buns", "Bakery"),
        ("garlic", "Produce"),
        ("chicken breasts", "Meat & Seafood"),
        ("chicken broth", "Canned & Soup"),
        ("salt and pepper", "Baking & Spices"),
        ("red pepper flakes", "Baking & Spices"),
    ],
)
def test_keyword_guess(seeded, name, section):
    assert guess_section(seeded, name_key(name)).name == section


def test_unknown_is_other(seeded):
    assert guess_section(seeded, name_key("zorblax")).name == "Other"


def test_learned_wins(seeded):
    bakery = next(s for s in _sections(seeded) if s.name == "Bakery")
    remember(seeded, name_key("flour tortillas"), bakery.id)
    assert guess_section(seeded, name_key("flour tortilla")).name == "Bakery"


def test_remember_updates_existing(seeded):
    secs = {s.name: s for s in _sections(seeded)}
    remember(seeded, "tortilla", secs["Bakery"].id)
    remember(seeded, "tortilla", secs["Deli"].id)
    assert guess_section(seeded, "tortilla").name == "Deli"


def test_text_color():
    assert text_color("#2E7D32") == "#fff"
    assert text_color("#4FC3F7") == "#10291C"
    assert text_color("#FF8A65") == "#10291C"


def _sections(session):
    from sqlalchemy import select

    from app.models import Section

    return session.scalars(select(Section)).all()
