import asyncio
import threading

from sqlalchemy import select

from app.models import ListItem, Meal, Staple
from app.services import shopping
from tests.factories import make_meal


def test_each_meal_keeps_its_own_rows(seeded):
    tacos = make_meal(seeded, "Tacos", "1 yellow onion\n1 lb ground beef")
    chili = make_meal(seeded, "Chili", "2 yellow onions, diced")
    shopping.add_meal(seeded, tacos)
    shopping.add_meal(seeded, chili)
    shopping.add_meal(seeded, tacos)
    onions = seeded.scalars(select(ListItem).where(ListItem.name_key == "yellow onion").order_by(ListItem.id)).all()
    assert [(o.sources[0].meal_name, o.amounts) for o in onions] == [
        ("Tacos", [{"qty": 2, "unit": None}]),
        ("Chili", [{"qty": 2, "unit": None}]),
    ]


def test_typed_items_and_meal_items_stay_apart(seeded):
    shopping.add_text(seeded, "1 yellow onion")
    shopping.add_meal(seeded, make_meal(seeded, "Tacos", "1 yellow onion"))
    shopping.add_text(seeded, "2 yellow onions")
    onions = seeded.scalars(select(ListItem).order_by(ListItem.id)).all()
    assert [(bool(o.sources), o.amounts) for o in onions] == [
        (False, [{"qty": 3, "unit": None}]),
        (True, [{"qty": 1, "unit": None}]),
    ]


def test_checked_not_merged(seeded):
    first = shopping.add_text(seeded, "2 bananas")
    shopping.toggle(seeded, first.id)
    shopping.add_text(seeded, "1 banana")
    assert len(seeded.scalars(select(ListItem)).all()) == 2


def test_quick_add_parses(seeded):
    item = shopping.add_text(seeded, "2 lb apples")
    assert item.name == "Apples"
    assert item.amounts == [{"qty": 2, "unit": "lb"}]
    assert item.section.name == "Produce"


def test_grouped_walk_order(seeded):
    shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "1 lb ground beef")
    shopping.add_text(seeded, "cilantro")
    done = shopping.add_text(seeded, "bananas")
    shopping.add_text(seeded, "garlic")
    shopping.toggle(seeded, done.id)
    groups = shopping.grouped(seeded)
    assert [s.name for s, _ in groups] == ["Produce", "Meat & Seafood", "Dairy & Eggs"]
    assert [i.name for i in groups[0][1]] == ["Cilantro", "Garlic", "Bananas"]


def test_meal_groups(seeded):
    shopping.add_text(seeded, "milk")
    shopping.add_meal(seeded, make_meal(seeded, "Chili", "1 lb ground beef\n1 cup sour cream\n1 yellow onion"))
    tacos = make_meal(seeded, "Tacos", "12 corn tortillas\n1 lime")
    shopping.add_meal(seeded, tacos)
    seeded.delete(tacos)
    seeded.commit()
    seeded.expire_all()
    groups = shopping.meal_groups(seeded)
    assert [(name, [i.name for i in items]) for name, items in groups] == [
        ("Chili", ["Yellow onion", "Ground beef", "Sour cream"]),
        ("Tacos", ["Lime", "Corn tortillas"]),
    ]
    assert [s.name for s, _ in shopping.grouped(seeded)] == ["Dairy & Eggs"]


def test_progress(seeded):
    a = shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "eggs")
    shopping.toggle(seeded, a.id)
    assert shopping.progress(seeded) == (1, 2)


def test_update_sets_amount_and_note(seeded):
    item = shopping.add_text(seeded, "tortillas")
    shopping.update(seeded, item.id, "2 pack", " soft taco size ")
    assert item.amounts == [{"qty": 2, "unit": "pkg"}]
    assert item.note == "soft taco size"
    shopping.update(seeded, item.id, "2 pack", "")
    assert item.note is None


def test_staples_ordered_by_times_added(seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    bananas = seeded.scalar(select(Staple).where(Staple.name_key == "banana"))
    for _ in range(2):
        shopping.add_staple(seeded, bananas.id)
        shopping.clear_all(seeded)
    shopping.add_text(seeded, "1 gal milk")
    shopping.clear_all(seeded)
    seeded.expire_all()
    assert (bananas.add_count, milk.add_count) == (2, 1)
    staples = shopping.available_staples(seeded)
    assert staples[:2] == [bananas, milk]
    rest = staples[2:]
    assert rest == sorted(rest, key=lambda s: (s.position, s.id))


def test_meal_ingredients_do_not_count_as_staple_adds(seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    shopping.add_meal(seeded, make_meal(seeded, "Pancakes", "1 cup milk"))
    seeded.expire_all()
    assert milk.add_count == 0


def test_staple_chip_hidden_when_on_list(seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    assert milk in shopping.available_staples(seeded)
    shopping.add_staple(seeded, milk.id)
    assert milk not in shopping.available_staples(seeded)
    item = seeded.scalar(select(ListItem))
    assert (item.name, item.amounts, item.section.name) == ("Milk", [{"qty": 1, "unit": "gal"}], "Dairy & Eggs")


def test_clear_checked(seeded):
    a = shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "eggs")
    shopping.toggle(seeded, a.id)
    n, undo_id = shopping.clear_checked(seeded)
    assert n == 1 and undo_id is not None
    assert [i.name for i in seeded.scalars(select(ListItem))] == ["Eggs"]


def test_undo_clear_checked_puts_items_back_as_they_were(seeded):
    meal = make_meal(seeded, "Tacos", "1 lb ground beef")
    shopping.add_meal(seeded, meal)
    milk = shopping.add_text(seeded, "2 gal milk")
    shopping.update(seeded, milk.id, "2 gal", "the organic one")
    beef = next(i for i in seeded.scalars(select(ListItem)) if i.name == "Ground beef")
    for item in (milk, beef):
        shopping.toggle(seeded, item.id)
    before = sorted((i.name, i.amounts, i.section_id, i.note, i.checked, i.created_at) for i in seeded.scalars(select(ListItem)))
    _, undo_id = shopping.clear_checked(seeded)
    assert seeded.scalars(select(ListItem)).all() == []
    assert shopping.undo(seeded, undo_id) == 2
    seeded.expire_all()
    items = seeded.scalars(select(ListItem)).all()
    assert sorted((i.name, i.amounts, i.section_id, i.note, i.checked, i.created_at) for i in items) == before
    assert [s.meal_name for i in items for s in i.sources] == ["Tacos"]
    assert shopping.undo(seeded, undo_id) == 0  # only once


def test_undo_remove_after_its_meal_was_deleted(seeded):
    meal = make_meal(seeded, "Tacos", "1 lb ground beef")
    shopping.add_meal(seeded, meal)
    item = seeded.scalar(select(ListItem))
    undo_id = shopping.remove(seeded, item.id)
    seeded.delete(meal)
    seeded.commit()
    assert shopping.undo(seeded, undo_id) == 1
    source = seeded.scalar(select(ListItem)).sources[0]
    assert (source.meal_id, source.meal_name) == (None, "Tacos")


def test_undo_keeps_a_meals_place_in_the_list(seeded):
    from datetime import timedelta

    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    chili = make_meal(seeded, "Chili", "2 cans beans")
    shopping.add_meal(seeded, tacos)
    shopping.add_meal(seeded, chili)
    for item in seeded.scalars(select(ListItem)):  # one transaction stamps the same time; make the order explicit
        if item.sources[0].meal_name == "Chili":
            item.created_at += timedelta(seconds=1)
    seeded.commit()
    first = min(seeded.scalars(select(ListItem)), key=lambda i: i.id)
    shopping.undo(seeded, shopping.remove(seeded, first.id))
    seeded.expire_all()
    assert [name for name, _ in shopping.meal_groups(seeded)] == ["Tacos", "Chili"]


def test_clear_checked_with_nothing_checked_has_no_undo(seeded):
    shopping.add_text(seeded, "eggs")
    assert shopping.clear_checked(seeded) == (0, None)


def test_clear_all(seeded):
    shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "eggs")
    shopping.clear_all(seeded)
    assert seeded.scalars(select(ListItem)).all() == []


def test_meal_delete_keeps_list_item(seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    shopping.add_meal(seeded, tacos)
    seeded.delete(tacos)
    seeded.commit()
    seeded.expire_all()
    item = seeded.scalar(select(ListItem))
    assert item.name == "Ground beef"
    assert item.sources[0].meal_id is None and item.sources[0].meal_name == "Tacos"
    assert seeded.scalar(select(Meal)) is None


def test_add_meal_scaled(seeded):
    tacos = make_meal(seeded, "Tacos", "1 lb ground beef")
    assert shopping.add_meal(seeded, tacos, factor=2) == 1
    assert seeded.scalar(select(ListItem)).amounts == [{"qty": 2, "unit": "lb"}]


async def test_events_emits_on_write(seeded):
    from app.routers.events import event_stream

    stream = event_stream(keepalive=30)
    first = await asyncio.wait_for(anext(stream), 5)
    assert first.startswith("retry:")
    t = threading.Thread(target=lambda: shopping.add_text(seeded, "milk"))
    t.start()
    event = await asyncio.wait_for(anext(stream), 3)
    t.join()
    assert event == "event: list\ndata: changed\n\n"
    await stream.aclose()


async def test_events_keepalive(seeded):
    from app.routers.events import event_stream

    stream = event_stream(keepalive=0.2)
    await anext(stream)
    assert await asyncio.wait_for(anext(stream), 2) == ": ping\n\n"
    await stream.aclose()
