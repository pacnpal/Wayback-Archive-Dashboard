"""SSE endpoint for htmax's hx-sse:connect."""
from __future__ import annotations
import asyncio
import itertools

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import events_bus, log as _log

router = APIRouter()
logger = _log.get("sse")

_HEARTBEAT_SEC = 25
_client_id = itertools.count(1)


@router.get("/events")
async def events(request: Request):
    cid = next(_client_id)
    peer = request.client.host if request.client else "?"
    q = events_bus.subscribe()
    logger.debug("SSE connect cid=%d peer=%s heartbeat=%ds", cid, peer, _HEARTBEAT_SEC)

    async def gen():
        pings = 0
        delivered = 0
        try:
            yield ": connected\n\n"
            logger.debug("SSE cid=%d sent ': connected' preamble", cid)
            while True:
                if await request.is_disconnected():
                    logger.debug("SSE cid=%d peer=%s disconnected — "
                                 "delivered=%d pings=%d",
                                 cid, peer, delivered, pings)
                    return
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                    delivered += 1
                    logger.debug("SSE cid=%d deliver event=%s data=%r (#%d)",
                                 cid, event, data, delivered)
                    yield f"event: {event}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    pings += 1
                    logger.debug("SSE cid=%d heartbeat ping #%d (%.0fs idle)",
                                 cid, pings, float(_HEARTBEAT_SEC))
                    yield ": ping\n\n"
        finally:
            events_bus.unsubscribe(q)
            logger.debug("SSE cleanup cid=%d unsubscribed", cid)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
