import asyncio

from app.services import shopping


def test_item_sheet_does_not_inline_values_into_js(client, seeded):
    import html as htmllib

    from tests.factories import section

    item = shopping.add_text(seeded, "sauce")
    produce = section(seeded, "Produce")
    produce.name = "Pro'+alert(1)+'duce"
    item.section_id = produce.id
    seeded.commit()
    shopping.update(seeded, item.id, "2 x');alert(2);//", "');alert(3);//")
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


def test_source_url_must_be_http(client, seeded):
    from sqlalchemy import select

    from app.models import Meal

    client.post("/meals", data={"name": "X", "ingredients": "salt", "source_url": "javascript:alert(1)"})
    meal = seeded.scalar(select(Meal))
    assert meal.source_url is None
    assert "javascript:" not in client.get(f"/meals/{meal.id}").text


def test_image_url_must_be_http(client, seeded):
    from sqlalchemy import select

    from app.models import Meal

    client.post("/meals", data={"name": "X", "ingredients": "salt", "image_url": "data:text/html,hi"})
    assert seeded.scalar(select(Meal)).image_url is None


async def test_resumed_stream_tells_the_page_to_refresh(seeded):
    from app.routers.events import event_stream

    stream = event_stream(keepalive=30, resumed=True)
    first = await asyncio.wait_for(anext(stream), 5)
    second = await asyncio.wait_for(anext(stream), 5)
    assert "id: 0" in first and second.startswith("event: list")
    await stream.aclose()


async def test_new_stream_does_not_refresh_right_away(seeded):
    from app.routers.events import event_stream

    stream = event_stream(keepalive=0.2)
    first = await asyncio.wait_for(anext(stream), 5)
    second = await asyncio.wait_for(anext(stream), 5)
    assert "id: 0" in first and second == ": ping\n\n"
    await stream.aclose()


async def test_full_broker_ends_stream_with_a_retry(seeded, monkeypatch):
    from app.routers import events

    first = events.event_stream(keepalive=30)
    await asyncio.wait_for(anext(first), 5)  # start the listener
    monkeypatch.setattr(events, "MAX_SUBSCRIBERS", len(events.broker.subscribers))
    chunks = [c async for c in events.event_stream(keepalive=30)]
    assert chunks == ["retry: 10000\n\n"]
    await first.aclose()


async def test_listener_reconnect_refreshes_open_pages(seeded, monkeypatch):
    from sqlalchemy import text

    from app.routers.events import broker

    monkeypatch.setattr(broker, "retry_delay", 0.05)
    queue = await broker.subscribe()
    try:
        before = broker.connections_opened
        # Drop the listener's connection the way a database restart would
        seeded.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE 'LISTEN %'"))
        seeded.commit()
        await asyncio.wait_for(queue.get(), 5)
        assert broker.connections_opened == before + 1
    finally:
        broker.unsubscribe(queue)
