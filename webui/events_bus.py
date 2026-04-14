"""In-process asyncio fan-out bus for Server-Sent Events.

Subscribers (SSE clients) each get an asyncio.Queue; publishers call
`publish(event)` which pushes non-blocking to every queue. Queues that
fill up drop the oldest items so one stuck client can't starve others.
"""
from __future__ import annotations
import asyncio
from typing import Optional

_subscribers: set[asyncio.Queue] = set()
_MAX_QUEUE = 64


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(event: str, data: str = "1") -> None:
    """Fire-and-forget from sync or async code."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    payload = (event, data)
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop oldest to make room.
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(payload)
            except Exception:
                pass
