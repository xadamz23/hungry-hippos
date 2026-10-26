"""Server-sent events: tell every open List page when the list changes.

One LISTEN connection per process fans out to any number of open pages.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import psycopg
from fastapi import APIRouter
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

    async def _listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(_dsn(), autocommit=True) as conn:
                    self.connections_opened += 1
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.ready.set()
                    async for _ in conn.notifies():
                        for queue in list(self.subscribers):
                            if queue.empty():  # one pending "changed" is enough
                                queue.put_nowait(True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("list listener lost its connection; retrying")
                self.ready.clear()
                await asyncio.sleep(2)

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


async def event_stream(keepalive: float = 15.0) -> AsyncIterator[str]:
    queue = await broker.subscribe()
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                await asyncio.wait_for(queue.get(), keepalive)
                yield "event: list\ndata: changed\n\n"
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        broker.unsubscribe(queue)


@router.get("/events")
async def events():
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
