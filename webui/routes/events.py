"""SSE endpoint for htmax's hx-sse:connect."""
from __future__ import annotations
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import events_bus

router = APIRouter()

_HEARTBEAT_SEC = 25


@router.get("/events")
async def events(request: Request):
    q = events_bus.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                    yield f"event: {event}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            events_bus.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
