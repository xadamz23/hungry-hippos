from app.services.amounts import fmt, merge, parse_amount_text, scale


def test_merge_same_unit():
    assert merge([{"qty": 1, "unit": "lb"}], [{"qty": 2, "unit": "lb"}]) == [{"qty": 3, "unit": "lb"}]


def test_merge_diff_units():
    merged = merge([{"qty": 1, "unit": "lb"}], [{"qty": 8, "unit": "oz"}])
    assert fmt(merged) == "1 lb + 8 oz"


def test_merge_counts():
    assert merge([{"qty": 3, "unit": None}], [{"qty": 2, "unit": None}]) == [{"qty": 5, "unit": None}]


def test_merge_unknown_qty_kept():
    merged = merge([{"qty": None, "unit": None}], [{"qty": 2, "unit": None}])
    assert fmt(merged) == "2"


def test_fmt_fraction():
    assert fmt([{"qty": 1.5, "unit": "cup"}]) == "1½ cups"
    assert fmt([{"qty": 0.5, "unit": "cup"}]) == "½ cup"
    assert fmt([{"qty": 2, "unit": "can"}]) == "2 cans"
    assert fmt([{"qty": 1 / 3, "unit": "cup"}]) == "⅓ cup"
    assert fmt([{"qty": 2.4, "unit": "lb"}]) == "2.4 lb"


def test_fmt_empty():
    assert fmt([]) == ""
    assert fmt([{"qty": None, "unit": None}]) == ""


def test_scale():
    assert scale([{"qty": 1, "unit": "lb"}, {"qty": None, "unit": None}], 1.5) == [
        {"qty": 1.5, "unit": "lb"},
        {"qty": None, "unit": None},
    ]


def test_parse_amount_text():
    assert parse_amount_text("1 pack") == [{"qty": 1, "unit": "pkg"}]
    assert parse_amount_text("3") == [{"qty": 3, "unit": None}]
    assert parse_amount_text("") == []
    assert parse_amount_text("1 lb + 8 oz") == [{"qty": 1, "unit": "lb"}, {"qty": 8, "unit": "oz"}]
