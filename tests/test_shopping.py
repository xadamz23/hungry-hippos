import asyncio
import threading

from sqlalchemy import select

from app.models import ListItem, Meal, Staple
from app.services import shopping
from tests.factories import make_meal, section


def test_merge_on_add(seeded):
    tacos = make_meal(seeded, "Tacos", "1 yellow onion\n1 lb ground beef")
    chili = make_meal(seeded, "Chili", "2 yellow onions, diced\n2 lb ground beef")
    shopping.add_meal(seeded, tacos)
    shopping.add_meal(seeded, chili)
    items = seeded.scalars(select(ListItem).order_by(ListItem.id)).all()
    assert len(items) == 2
    onion = items[0]
    assert onion.amounts == [{"qty": 3, "unit": None}]
    assert [s.meal_name for s in onion.sources] == ["Tacos", "Chili"]
    assert items[1].amounts == [{"qty": 3, "unit": "lb"}]


def test_checked_not_merged(seeded):
    first = shopping.add_text(seeded, "2 bananas")
    shopping.toggle(seeded, first.id)
    shopping.add_text(seeded, "1 banana")
    assert len(seeded.scalars(select(ListItem)).all()) == 2


def test_quick_add_parses(seeded):
    item = shopping.add_text(seeded, "2 lb apples")
    assert item.name == "apples"
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
    assert [i.name for i in groups[0][1]] == ["cilantro", "garlic", "bananas"]


def test_progress(seeded):
    a = shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "eggs")
    shopping.toggle(seeded, a.id)
    assert shopping.progress(seeded) == (1, 2)


def test_update_remember_learns(seeded):
    item = shopping.add_text(seeded, "tortillas")
    bakery = section(seeded, "Bakery")
    shopping.update(seeded, item.id, "2 pack", bakery.id, remember=True)
    assert item.amounts == [{"qty": 2, "unit": "pkg"}]
    shopping.remove(seeded, item.id)
    assert shopping.add_text(seeded, "tortilla").section.name == "Bakery"


def test_update_without_remember_does_not_learn(seeded):
    item = shopping.add_text(seeded, "tortillas")
    shopping.update(seeded, item.id, "", section(seeded, "Bakery").id, remember=False)
    shopping.remove(seeded, item.id)
    assert shopping.add_text(seeded, "tortilla").section.name == "International"


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
    assert shopping.clear_checked(seeded) == 1
    assert [i.name for i in seeded.scalars(select(ListItem))] == ["eggs"]


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
    assert item.name == "ground beef"
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
