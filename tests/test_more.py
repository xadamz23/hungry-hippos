from sqlalchemy import select

from app.models import ItemSectionMap, Section, Staple
from app.services import shopping
from app.services.sections import remember
from tests.factories import section


def test_more_index(client):
    html = client.get("/more").text
    for text in ["Section order", "Staples", "Remembered sections", "History", "Clear checked items"]:
        assert text in html
    assert "Backups" not in html


def test_more_shows_ai_status(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    assert "Off" in client.get("/more").text
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    assert ">On<" in client.get("/more").text


def test_reorder_sections_changes_list_order(client, seeded):
    shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "garlic")
    ids = [s.id for s in seeded.scalars(select(Section).order_by(Section.position))]
    dairy = section(seeded, "Dairy & Eggs").id
    new_order = [dairy] + [i for i in ids if i != dairy]
    r = client.post("/more/sections/order", data={"ids": new_order})
    assert r.status_code == 204
    seeded.expire_all()
    assert [s.name for s, _ in shopping.grouped(seeded)] == ["Dairy & Eggs", "Produce"]


def test_sections_page(client):
    html = client.get("/more/sections").text
    assert "Produce" in html and 'type="color"' in html


def test_edit_section(client, seeded):
    produce = section(seeded, "Produce")
    r = client.post(f"/more/sections/{produce.id}", data={"name": "Fruit & Veg", "color": "#123456"})
    assert r.status_code in (200, 204)
    seeded.expire_all()
    assert (seeded.get(Section, produce.id).name, seeded.get(Section, produce.id).color) == ("Fruit & Veg", "#123456")


def test_edit_section_rejects_bad_color(client, seeded):
    produce = section(seeded, "Produce")
    client.post(f"/more/sections/{produce.id}", data={"name": "Produce", "color": "red;}"})
    seeded.expire_all()
    assert seeded.get(Section, produce.id).color == "#2E7D32"


def test_add_section(client, seeded):
    client.post("/more/sections", data={"name": "Pharmacy"})
    names = [s.name for s in seeded.scalars(select(Section).order_by(Section.position))]
    assert names[-1] == "Pharmacy"


def test_add_duplicate_section_ignored(client, seeded):
    client.post("/more/sections", data={"name": "produce"})
    assert len(seeded.scalars(select(Section)).all()) == 14


def test_add_staple_appears_as_chip(client, seeded):
    client.post("/more/staples", data={"text": "1 bag coffee"})
    staple = seeded.scalar(select(Staple).where(Staple.name == "coffee"))
    assert staple.amounts == [{"qty": 1, "unit": "bag"}]
    assert staple.section.name == "Breakfast & Cereal"
    assert 'aria-label="Add coffee"' in client.get("/list").text


def test_delete_staple(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    client.post(f"/more/staples/{milk.id}/delete")
    assert seeded.scalar(select(Staple).where(Staple.name == "Milk")) is None


def test_delete_remembered(client, seeded):
    remember(seeded, "tortilla", section(seeded, "Bakery").id)
    seeded.commit()
    assert "tortilla" in client.get("/more/remembered").text
    client.post("/more/remembered/delete", data={"key": "tortilla"})
    seeded.expire_all()
    assert seeded.scalars(select(ItemSectionMap)).all() == []

