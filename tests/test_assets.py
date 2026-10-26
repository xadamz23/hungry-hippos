import re

import pytest

from app.assets import AssetManifest


def test_static_url_has_hash(tmp_path):
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "app.css").write_text("body{}")
    url = AssetManifest(tmp_path).url("css/app.css")
    assert re.fullmatch(r"/static/css/app\.css\?v=[0-9a-f]{10}", url)


def test_hash_changes_when_file_changes(tmp_path):
    f = tmp_path / "app.js"
    f.write_text("a")
    before = AssetManifest(tmp_path).url("app.js")
    f.write_text("b")
    assert AssetManifest(tmp_path).url("app.js") != before


def test_missing_file_raises(tmp_path):
    with pytest.raises(KeyError):
        AssetManifest(tmp_path).url("nope.css")


def test_versioned_static_is_immutable(client):
    from app.templating import static_url

    r = client.get(static_url("css/app.css"))
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_unversioned_static_not_immutable(client):
    r = client.get("/static/css/app.css")
    assert "immutable" not in r.headers.get("cache-control", "")


def test_manifest_served(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Hungry Hippos"
    assert data["display"] == "standalone"
    assert all("?v=" in icon["src"] for icon in data["icons"])


def test_sw_served_at_root(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert "javascript" in r.headers["content-type"]


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_pages_use_versioned_assets(client):
    html = client.get("/list").text
    assert re.search(r'/static/css/app\.css\?v=[0-9a-f]{10}', html)
    assert re.search(r'/static/vendor/htmx\.min\.js\?v=[0-9a-f]{10}', html)


def test_font_is_loaded_through_versioned_url(client):
    from app.templating import static_url

    html = client.get("/list").text
    css = client.get("/static/css/app.css").text
    assert "url(\"../fonts" not in css and "url(../fonts" not in css
    assert f'url("{static_url("fonts/figtree-latin.woff2")}")' in html
