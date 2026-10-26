import asyncio

from app.services import shopping


def test_item_sheet_does_not_inline_values_into_js(client, seeded):
    import html as htmllib

    from tests.factories import section

    item = shopping.add_text(seeded, "sauce")
    produce = section(seeded, "Produce")
    produce.name = "Pro'+alert(1)+'duce"
    seeded.commit()
    shopping.update(seeded, item.id, "2 x');alert(2);//", produce.id, remember=False)
    page = client.get(f"/list/{item.id}/edit").text
    js_attrs = [htmllib.unescape(a) for a in __import__("re").findall(r'(?:x-data|@change|@click|x-text)="([^"]*)"', page)]
    assert js_attrs, "sheet should still use Alpine"
    assert not any("alert" in a for a in js_attrs)


def test_cross_site_post_rejected(client, seeded):
    r = client.post("/list/clear-all", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_cross_site_fetch_metadata_rejected(client, seeded):
    r = client.post("/list/clear-all", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_post_allowed(client, seeded):
    r = client.post("/list/add", data={"text": "milk"}, headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


async def test_events_share_one_listener(seeded):
    from app.routers.events import broker, event_stream

    a, b = event_stream(keepalive=30), event_stream(keepalive=30)
    await asyncio.wait_for(anext(a), 5)
    await asyncio.wait_for(anext(b), 5)
    assert broker.connections_opened == 1
    await a.aclose()
    await b.aclose()


def test_same_origin_allowed_when_proxy_rewrites_host(client, seeded):
    r = client.post("/list/add", data={"text": "milk"},
                    headers={"Origin": "https://hippos.example.com", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_origin_matching_forwarded_host_allowed(client, seeded):
    r = client.post("/list/add", data={"text": "milk"},
                    headers={"Origin": "https://hippos.example.com", "X-Forwarded-Host": "hippos.example.com"})
    assert r.status_code == 200
