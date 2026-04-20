"""Cron-driven recurring archive scheduler."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from croniter import croniter

from . import jobs, log as _log, events_bus

logger = _log.get("scheduler")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts)


def compute_next(cron_expr: str, base: datetime | None = None) -> str:
    base = base or datetime.now(timezone.utc)
    it = croniter(cron_expr, base)
    return it.get_next(datetime).astimezone(timezone.utc).replace(microsecond=0).isoformat()


async def scheduler_loop(stop: asyncio.Event) -> None:
    tick = 0
    logger.debug("scheduler loop start interval=30s")
    while not stop.is_set():
        tick += 1
        now = datetime.now(timezone.utc)
        with jobs.connect() as c:
            due = c.execute(
                "SELECT * FROM schedules WHERE enabled=1 AND (next_run_at IS NULL OR next_run_at <= ?)",
                (now.replace(microsecond=0).isoformat(),),
            ).fetchall()
        logger.debug("scheduler tick=%d heartbeat now=%s due=%d",
                     tick, now.replace(microsecond=0).isoformat(), len(due))
        for s in due:
            flags = json.loads(s["flags_json"])
            logger.debug("scheduler tick=%d firing schedule=%d url=%s cron=%r "
                         "flags=%s",
                         tick, s["id"], s["target_url"], s["cron_expr"], flags)
            job_id = jobs.enqueue(s["target_url"], None, flags, schedule_id=s["id"])
            nxt = compute_next(s["cron_expr"], now)
            logger.info("schedule=%d url=%s -> job=%d next=%s",
                        s["id"], s["target_url"], job_id, nxt)
            events_bus.publish("jobs-changed")
            with jobs.connect() as c:
                c.execute(
                    "UPDATE schedules SET last_run_at=?, last_job_id=?, next_run_at=? WHERE id=?",
                    (jobs.now_iso(), job_id, nxt, s["id"]),
                )
        logger.debug("scheduler tick=%d sleeping 30s", tick)
        try:
            await asyncio.wait_for(stop.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
    logger.debug("scheduler loop exit after tick=%d", tick)
