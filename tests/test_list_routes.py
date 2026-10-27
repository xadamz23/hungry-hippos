import re

from sqlalchemy import select

from app.models import ListItem, Staple
from app.services import shopping


def test_list_page_renders_sections_without_counts(client, seeded):
    shopping.add_text(seeded, "2 yellow onions")
    html = client.get("/list").text
    assert "left</small>" not in html
    assert "Show checked items" in html
    assert "All checked off" not in html
    sign = re.search(r'<div class="sign"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert sign.strip() == "Produce"


def test_list_empty_state(client):
    html = client.get("/list").text
    assert "Your list is empty" in html


def test_add_route_returns_items_partial(client, seeded):
    r = client.post("/list/add", data={"text": "2 lb apples"})
    assert r.status_code == 200
    assert "apples" in r.text and "2 lb" in r.text
    assert "<html" not in r.text


def test_add_blank_is_ignored(client, seeded):
    client.post("/list/add", data={"text": "   "})
    assert seeded.scalars(select(ListItem)).all() == []


def test_toggle_route(client, seeded):
    item = shopping.add_text(seeded, "milk")
    r = client.post(f"/list/{item.id}/toggle")
    assert 'class="it done"' in r.text
    assert "All checked off" in r.text


def test_staple_route(client, seeded):
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    r = client.post(f"/list/staple/{milk.id}")
    assert "1 gal" in r.text


def test_typing_shows_staple_suggestions(client, seeded):
    html = client.get("/list").text
    assert 'x-data="quickAdd"' in html
    assert 'x-model="q"' in html and 'role="combobox"' in html and 'aria-controls="add-suggest"' in html
    suggest = re.search(r'<div id="add-suggest"[^>]*role="listbox".*?</div>\s*</div>', html, re.S).group(0)
    milk = seeded.scalar(select(Staple).where(Staple.name == "Milk"))
    assert 'data-name="Milk"' in suggest and f'hx-post="/list/staple/{milk.id}"' in suggest
    assert "1 gal" in suggest


def test_add_refreshes_staple_suggestions(client, seeded):
    r = client.post("/list/add", data={"text": "milk"})
    assert 'id="list-staples"' in r.text and 'hx-swap-oob="true"' in r.text
    assert 'data-name="Milk"' not in r.text


def test_edit_sheet_and_save_note(client, seeded):
    item = shopping.add_text(seeded, "tortillas")
    sheet = client.get(f"/list/{item.id}/edit").text
    assert 'name="section_id"' not in sheet and 'name="note"' in sheet

    r = client.post(f"/list/{item.id}", data={"amount": "2", "note": "  the big pack "})
    assert r.status_code == 200 and "#i-note" in r.text
    seeded.expire_all()
    saved = seeded.get(ListItem, item.id)
    assert saved.note == "the big pack" and saved.amounts
    assert "the big pack" in client.get(f"/list/{item.id}/edit").text

    r = client.post(f"/list/{item.id}", data={"amount": "2", "note": "  "})
    assert "#i-note" not in r.text
    seeded.expire_all()
    assert seeded.get(ListItem, item.id).note is None


def test_delete_route(client, seeded):
    item = shopping.add_text(seeded, "milk")
    client.post(f"/list/{item.id}/delete")
    assert seeded.scalars(select(ListItem)).all() == []


def test_missing_item_404(client):
    assert client.post("/list/9999/toggle").status_code == 404


def test_clear_routes(client, seeded):
    a = shopping.add_text(seeded, "milk")
    shopping.add_text(seeded, "eggs")
    shopping.toggle(seeded, a.id)
    client.post("/list/clear-checked")
    assert len(seeded.scalars(select(ListItem)).all()) == 1
    client.post("/list/clear-all")
    assert seeded.scalars(select(ListItem)).all() == []
