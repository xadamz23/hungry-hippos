from sqlalchemy import select

from app.models import ItemSectionMap, Section, Staple
from app.services import shopping
from app.services.sections import remember
from tests.factories import section


def test_more_index(client):
    html = client.get("/more").text
    for text in ["Section order", "Favorites", "Remembered sections", "History", "Clear checked items"]:
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
    assert len(seeded.scalars(select(Section)).all()) == 19


def test_add_staple_appears_as_chip(client, seeded):
    client.post("/more/staples", data={"text": "1 bag coffee"})
    staple = seeded.scalar(select(Staple).where(Staple.name == "Coffee"))
    assert staple.amounts == [{"qty": 1, "unit": "bag"}]
    assert staple.section.name == "Cereal & Peanut Butter"
    assert 'aria-label="Add Coffee"' in client.get("/list").text


def test_staples_page_has_filter(client, seeded):
    html = client.get("/more/staples").text
    assert 'id="staple-q"' in html
    assert 'data-name="Milk"' in html


def test_delete_staple(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    client.post(f"/more/staples/{milk.id}/delete")
    assert seeded.scalar(select(Staple).where(Staple.name == "Milk")) is None


def test_add_staple_keeps_descriptive_words(client, seeded):
    client.post("/more/staples", data={"text": "1 jar Minced garlic"})
    staple = seeded.scalar(select(Staple).where(Staple.name == "Minced garlic"))
    assert staple.amounts == [{"qty": 1, "unit": "jar"}]
    assert staple.name_key == "minced garlic"


def test_edit_staple_sheet(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    html = client.get(f"/more/staples/{milk.id}/edit").text
    assert 'value="Milk"' in html and "Dairy &amp; Eggs" in html and "Produce" in html


def test_edit_staple(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    bakery = section(seeded, "Bakery").id
    r = client.post(f"/more/staples/{milk.id}", data={"name": "Oat milks", "amount": "2 gal", "section_id": bakery})
    assert "close-sheet" in r.headers["HX-Trigger"]
    assert "Oat milks" in r.text
    seeded.expire_all()
    assert (milk.name, milk.name_key, milk.section_id) == ("Oat milks", "oat milk", bakery)
    assert milk.amounts == [{"qty": 2, "unit": "gal"}]


def test_edit_staple_blank_name_keeps_old(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    client.post(f"/more/staples/{milk.id}", data={"name": "  ", "amount": ""})
    seeded.expire_all()
    assert milk.name == "Milk" and milk.amounts == []


def test_edit_missing_staple_404(client):
    assert client.get("/more/staples/999999/edit").status_code == 404


def test_delete_remembered(client, seeded):
    remember(seeded, "tortilla", section(seeded, "Bakery").id)
    seeded.commit()
    assert "tortilla" in client.get("/more/remembered").text
    client.post("/more/remembered/delete", data={"key": "tortilla"})
    seeded.expire_all()
    assert seeded.scalars(select(ItemSectionMap)).all() == []



def test_changing_staple_section_remembers_it(client, seeded):
    from app.services.sections import guess_section

    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    frozen = section(seeded, "Frozen").id
    client.post(f"/more/staples/{milk.id}", data={"name": "Milk", "amount": "", "section_id": frozen})
    seeded.expire_all()
    # "milk" is a Dairy keyword; the explicit staple choice now wins for meals and typed list items too
    assert guess_section(seeded, "milk").id == frozen


def test_saving_staple_without_changing_section_remembers_nothing(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    client.post(f"/more/staples/{milk.id}", data={"name": "Milk", "amount": "", "section_id": milk.section_id})
    assert seeded.scalars(select(ItemSectionMap)).all() == []
