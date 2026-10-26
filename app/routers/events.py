"""Server-sent events: tell every open List page when the list changes."""

from collections.abc import AsyncIterator

import psycopg
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.services.shopping import CHANNEL

router = APIRouter()


def _dsn() -> str:
    return make_url(get_settings().database_url).set(drivername="postgresql").render_as_string(hide_password=False)


async def event_stream(keepalive: float = 15.0) -> AsyncIterator[str]:
    async with await psycopg.AsyncConnection.connect(_dsn(), autocommit=True) as conn:
        await conn.execute(f"LISTEN {CHANNEL}")
        yield "retry: 3000\n\n"
        while True:
            changed = False
            async for _ in conn.notifies(timeout=keepalive, stop_after=1):
                changed = True
            yield "event: list\ndata: changed\n\n" if changed else ": ping\n\n"


@router.get("/events")
async def events():
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
