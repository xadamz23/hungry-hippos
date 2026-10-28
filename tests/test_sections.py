import pytest

from app.services.ingredients import name_key
from app.services.sections import guess_section, remember, text_color


@pytest.mark.parametrize(
    "name,section",
    [
        ("yellow onions", "Produce"),
        ("ground beef", "Meat & Seafood"),
        ("tomato sauce", "Pasta & Mexican"),
        ("sour cream", "Dairy & Eggs"),
        ("flour tortillas", "Pasta & Mexican"),
        ("frozen peas", "Frozen"),
        ("all-purpose flour", "Spices, Baking & Snacks"),
        ("spaghetti", "Pasta & Mexican"),
        ("shredded cheddar cheese", "Deli"),
        ("paper towels", "Paper & Laundry"),
        ("hamburger buns", "Bread & Condiments"),
        ("garlic", "Produce"),
        ("chicken breasts", "Meat & Seafood"),
        ("chicken broth", "Soup, Oil & Mayo"),
        ("salt and pepper", "Spices, Baking & Snacks"),
        ("red pepper flakes", "Spices, Baking & Snacks"),
        ("greek yogurt", "Yogurt, Butter & Ritz"),
        ("peanut butter", "Cereal & Peanut Butter"),
        ("diet coke", "Pop & Gatorade"),
        ("dawn dish soap", "Dish & Cleaning"),
        ("cottage cheese", "Dairy & Eggs"),
    ],
)
def test_keyword_guess(seeded, name, section):
    assert guess_section(seeded, name_key(name)).name == section


def test_keyword_sections_are_default_sections():
    from app.seed import DEFAULT_SECTIONS
    from app.services.sections import KEYWORDS

    assert set(KEYWORDS) <= {name for name, _ in DEFAULT_SECTIONS}
    words = [w for ws in KEYWORDS.values() for w in ws]
    assert len(words) == len(set(words))


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


def _staple(session, name, section_name):
    from app.models import Staple
    from tests.factories import section

    staple = Staple(name=name, name_key=name_key(name), section_id=section(session, section_name).id)
    session.add(staple)
    session.commit()
    return staple


def test_staple_section_beats_keywords(seeded):
    # "hamburger meat" has no keyword, so it would land in Other without the staple
    _staple(seeded, "Hamburger meat", "Meat & Seafood")
    assert guess_section(seeded, name_key("hamburger meat")).name == "Meat & Seafood"


def test_staple_matches_without_its_parenthetical(seeded):
    from app.services.ingredients import parse_line

    _staple(seeded, "Hamburger meat (family pack)", "Meat & Seafood")
    # Picking the staple on the meal form saves "Hamburger meat (family pack)", which parses to "hamburger meat"
    assert guess_section(seeded, parse_line("Hamburger meat (family pack)").name_key).name == "Meat & Seafood"


def test_remembered_section_beats_staple(seeded):
    from tests.factories import section

    _staple(seeded, "Hamburger meat", "Meat & Seafood")
    remember(seeded, "hamburger meat", section(seeded, "Frozen").id)
    assert guess_section(seeded, "hamburger meat").name == "Frozen"


def test_meal_ingredient_follows_staple_section(seeded):
    from tests.factories import make_meal

    _staple(seeded, "Hamburger meat (family pack)", "Meat & Seafood")
    meal = make_meal(seeded, "Tacos", "Hamburger meat (family pack)\nSalsa")
    assert [i.section.name for i in meal.ingredients] == ["Meat & Seafood", "Pasta & Mexican"]
