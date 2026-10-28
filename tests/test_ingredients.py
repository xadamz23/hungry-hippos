import pytest

from app.services.ingredients import name_key, normalize_unit, parse_line


def test_parse_basic():
    p = parse_line("2 lb ground beef")
    assert (p.qty, p.unit, p.name) == (2, "lb", "Ground beef")


def test_parse_unicode_fraction():
    p = parse_line("½ cup milk")
    assert (p.qty, p.unit, p.name) == (0.5, "cup", "Milk")


def test_parse_mixed():
    p = parse_line("1 1/2 cups flour")
    assert (p.qty, p.unit, p.name) == (1.5, "cup", "Flour")


def test_parse_mixed_unicode():
    assert parse_line("1½ tablespoons olive oil").qty == 1.5
    assert parse_line("1½ tablespoons olive oil").unit == "tbsp"


def test_parse_range_takes_upper():
    assert parse_line("2-3 cloves garlic, minced").qty == 3
    assert parse_line("2-3 cloves garlic, minced").name == "Garlic"


def test_parse_paren_size():
    p = parse_line("1 (15 oz) can black beans, drained and rinsed")
    assert (p.qty, p.unit, p.name) == (1, "can", "Black beans")


def test_parse_prep_stripped():
    p = parse_line("1 yellow onion, diced")
    assert (p.qty, p.unit, p.name) == (1, None, "Yellow onion")
    assert parse_line("2 cloves fresh garlic, minced").name == "Garlic"
    assert parse_line("1 cup diced tomatoes").name == "Diced tomatoes"


def test_parse_to_taste():
    p = parse_line("salt and pepper to taste")
    assert p.qty is None and p.unit is None
    assert p.name == "Salt and pepper"


def test_parse_no_qty():
    p = parse_line("salt")
    assert (p.qty, p.unit, p.name) == (None, None, "Salt")


@pytest.mark.parametrize("line", ["½ cup", "", "   ", "2", "(optional)", "1 / 2"])
def test_parse_degenerate_lines_do_not_crash(line):
    parse_line(line)


def test_parse_keeps_raw():
    assert parse_line("  2 lb ground beef ").raw == "2 lb ground beef"


def test_parse_decimal():
    assert parse_line("0.5 lb shrimp").qty == 0.5


def test_normalize_unit():
    assert normalize_unit("Tablespoons") == "tbsp"
    assert normalize_unit("lbs") == "lb"
    assert normalize_unit("pound") == "lb"
    assert normalize_unit("package") == "pkg"
    assert normalize_unit("onion") is None


def test_name_key_plural():
    assert name_key("Yellow Onions") == name_key("yellow onion")
    assert name_key("tomatoes") == "tomato"
    assert name_key("berries") == "berry"
    assert name_key("glass") == "glass"
    assert name_key("Black-beans!") == "black bean"


def test_parse_capitalizes_first_letter_only():
    assert parse_line("1 gal milk").name == "Milk"
    assert parse_line("2 cans kraft mac and cheese").name == "Kraft mac and cheese"
    assert parse_line("1 bag BBQ chips").name == "BBQ chips"
