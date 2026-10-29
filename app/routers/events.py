"""Server-sent events: tell every open List page when the list changes.

One LISTEN connection per process fans out to any number of open pages.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.services.shopping import CHANNEL

log = logging.getLogger(__name__)
router = APIRouter()
MAX_SUBSCRIBERS = 50


def _dsn() -> str:
    return make_url(get_settings().database_url).set(drivername="postgresql").render_as_string(hide_password=False)


class Broker:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.ready = asyncio.Event()
        self.connections_opened = 0
        self.retry_delay = 2.0

    def _changed(self) -> None:
        for queue in list(self.subscribers):
            if queue.empty():  # one pending "changed" is enough
                queue.put_nowait(True)

    async def _listen(self) -> None:
        reconnecting = False
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(_dsn(), autocommit=True) as conn:
                    self.connections_opened += 1
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.ready.set()
                    if reconnecting:  # changes made while the connection was down were never heard
                        self._changed()
                    async for _ in conn.notifies():
                        self._changed()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("list listener lost its connection; retrying")
                self.ready.clear()
                await asyncio.sleep(self.retry_delay)
            reconnecting = True

    async def subscribe(self) -> asyncio.Queue:
        if len(self.subscribers) >= MAX_SUBSCRIBERS:
            raise RuntimeError("too many open list pages")
        loop = asyncio.get_running_loop()
        if self.task is None or self.task.done() or self.task.get_loop() is not loop:
            self.ready = asyncio.Event()
            self.subscribers = set()
            self.task = loop.create_task(self._listen())
        await asyncio.wait_for(self.ready.wait(), 10)
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await self.task
            self.task = None


broker = Broker()


async def event_stream(keepalive: float = 15.0, resumed: bool = False) -> AsyncIterator[str]:
    try:
        queue = await broker.subscribe()
    except (RuntimeError, TimeoutError):
        # Too many open pages, or the database isn't answering: end the stream and have the browser try later
        yield "retry: 10000\n\n"
        return
    try:
        # The id makes the browser send Last-Event-ID when it reconnects by itself (see events())
        yield "retry: 3000\nid: 0\n\n"
        if resumed:
            yield "event: list\ndata: changed\n\n"
        while True:
            try:
                await asyncio.wait_for(queue.get(), keepalive)
                yield "event: list\ndata: changed\n\n"
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        broker.unsubscribe(queue)


@router.get("/events")
async def events(request: Request):
    # A reconnect may have missed changes, so its stream starts by telling the page to refresh
    resumed = request.headers.get("last-event-id") is not None
    return StreamingResponse(
        event_stream(resumed=resumed),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
