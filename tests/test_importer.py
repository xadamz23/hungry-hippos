from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services import importer

FIX = Path(__file__).parent / "fixtures"
URL = "https://example.com/recipes/alfredo"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def resolve(host):
        return {"example.com": ["93.184.215.14"], "localhost": ["127.0.0.1"]}.get(host, [host])
    monkeypatch.setattr(importer, "_resolve_host", resolve)


def test_structured_fixture():
    r = importer.parse_structured((FIX / "recipe_jsonld.html").read_text(), URL)
    assert r.title == "Chicken Fettuccine Alfredo"
    assert len(r.ingredients) == 7
    assert r.steps == ["Cook the fettuccine.", "Sear the chicken.", "Make the sauce and toss."]
    assert r.servings == 4
    assert r.total_minutes == 35
    assert r.image_url == "https://example.com/alfredo.jpg"
    assert r.source_url == URL


def test_structured_returns_none_without_recipe():
    assert importer.parse_structured((FIX / "recipe_plain.html").read_text(), URL) is None


def test_page_text_strips_scripts_and_styles():
    text = importer.page_text((FIX / "recipe_plain.html").read_text())
    assert "var x" not in text and "body{}" not in text
    assert "2 lb ground beef" in text


class FakeClient:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.calls = []
        response = SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason)
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=lambda **kw: self.calls.append(kw) or response))


def test_plain_with_claude_mock():
    parsed = importer.RecipeExtraction(
        title="Sloppy Joes", ingredients=["2 lb ground beef", "1 onion"], steps=["Brown it"],
        servings=6, total_minutes=None, is_recipe=True,
    )
    client = FakeClient(parsed)
    r = importer.parse_with_claude((FIX / "recipe_plain.html").read_text(), URL, client=client)
    assert r.title == "Sloppy Joes" and r.servings == 6 and r.source_url == URL
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is importer.RecipeExtraction
    assert call["fallbacks"] == "default"
    assert "2 lb ground beef" in call["messages"][0]["content"]


def test_claude_says_not_a_recipe():
    parsed = importer.RecipeExtraction(title="", ingredients=[], steps=[], servings=None, total_minutes=None, is_recipe=False)
    with pytest.raises(importer.RecipeImportError, match="doesn’t look like a recipe"):
        importer.parse_with_claude("<p>hello</p>", URL, client=FakeClient(parsed))


def test_claude_refusal_is_readable():
    with pytest.raises(importer.RecipeImportError):
        importer.parse_with_claude("<p>x</p>", URL, client=FakeClient(None, stop_reason="refusal"))


def test_plain_without_key_errors(monkeypatch):
    monkeypatch.setattr(importer, "fetch_html", lambda url: (FIX / "recipe_plain.html").read_text())
    monkeypatch.setattr(importer, "ai_enabled", lambda: False)
    with pytest.raises(importer.RecipeImportError, match="Add it by hand"):
        importer.import_url(URL)


def test_import_url_prefers_structured(monkeypatch):
    monkeypatch.setattr(importer, "fetch_html", lambda url: (FIX / "recipe_jsonld.html").read_text())
    monkeypatch.setattr(importer, "parse_with_claude", lambda *a, **k: pytest.fail("should not call Claude"))
    assert importer.import_url(URL).title == "Chicken Fettuccine Alfredo"


def _transport(status=200, body="", exc=None):
    def handler(request):
        if exc:
            raise exc
        return httpx.Response(status, text=body)
    return httpx.MockTransport(handler)


def test_fetch_404_message():
    with pytest.raises(importer.RecipeImportError, match="HTTP 404"):
        importer.fetch_html(URL, transport=_transport(404))


def test_fetch_timeout_message():
    with pytest.raises(importer.RecipeImportError, match="took too long"):
        importer.fetch_html(URL, transport=_transport(exc=httpx.ReadTimeout("slow")))


@pytest.mark.parametrize("bad", ["notaurl", "ftp://example.com/x", "http://localhost/x", "http://127.0.0.1/x", "http://10.0.0.5/x", "http://[::1]/x"])
def test_fetch_rejects_bad_or_private_urls(bad):
    with pytest.raises(importer.RecipeImportError):
        importer.fetch_html(bad, transport=_transport(200, "ok"))


def test_import_route_review_shows_sections(client, monkeypatch):
    monkeypatch.setattr(importer, "fetch_html", lambda url: (FIX / "recipe_jsonld.html").read_text())
    html = client.post("/meals/import", data={"url": URL}).text
    assert "Check the sections" in html
    assert "Chicken Fettuccine Alfredo" in html
    assert 'name="section_0"' in html and 'name="section_6"' in html
    assert html.count("Not sure, pick one") == 1  # only za'atar is unknown


def test_import_route_error_shown(client, monkeypatch):
    def boom(url):
        raise importer.RecipeImportError("Couldn’t load that page (HTTP 404).")
    monkeypatch.setattr(importer, "fetch_html", boom)
    r = client.post("/meals/import", data={"url": URL})
    assert r.status_code == 200
    assert "Couldn’t load that page (HTTP 404)." in r.text


def test_save_from_review_learns_sections(client, seeded):
    from sqlalchemy import select

    from app.models import Meal
    from tests.factories import section

    deli = section(seeded, "Deli")
    r = client.post("/meals", data={"name": "Alfredo", "ingredients": "1 cup grated parmesan\n12 oz fettuccine",
                                    "section_0": deli.id, "source_url": URL, "image_url": "https://example.com/a.jpg"},
                    follow_redirects=False)
    assert r.status_code == 303
    meal = seeded.scalar(select(Meal))
    assert meal.source_url == URL and meal.ingredients[0].section_id == deli.id


def test_unchanged_guess_is_not_remembered(client, seeded):
    from sqlalchemy import select

    from app.models import ItemSectionMap
    from tests.factories import section

    dairy = section(seeded, "Dairy & Eggs").id
    client.post("/meals", data={"name": "A", "ingredient_lines": ["2 cups heavy cream"], "section_0": dairy, "guess_0": dairy})
    assert seeded.scalars(select(ItemSectionMap)).all() == []


def test_fetch_rejects_large_content_length(monkeypatch):
    monkeypatch.setattr(importer, "MAX_BYTES", 100)
    t = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-length": "5000"}, content=b"x" * 5000))
    with pytest.raises(importer.RecipeImportError, match="too big"):
        importer.fetch_html(URL, transport=t)


def test_fetch_stops_reading_past_cap(monkeypatch):
    monkeypatch.setattr(importer, "MAX_BYTES", 100)

    def chunks():
        for _ in range(50):
            yield b"x" * 64

    t = httpx.MockTransport(lambda r: httpx.Response(200, content=chunks()))
    with pytest.raises(importer.RecipeImportError, match="too big"):
        importer.fetch_html(URL, transport=t)


class _Stream:
    def __init__(self, ip):
        self.ip = ip

    def get_extra_info(self, name):
        return (self.ip, 443) if name == "server_addr" else None


def test_fetch_rejects_private_peer_after_connect():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text="<p>hi</p>", extensions={"network_stream": _Stream("10.1.2.3")}))
    with pytest.raises(importer.RecipeImportError, match="private address"):
        importer.fetch_html(URL, transport=t)


def test_fetch_allows_public_peer():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text="<p>hi</p>", extensions={"network_stream": _Stream("93.184.215.14")}))
    assert importer.fetch_html(URL, transport=t) == "<p>hi</p>"
