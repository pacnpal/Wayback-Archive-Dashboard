"""Centralised Python logging setup. Writes to stdout so docker logs
captures everything; LOG_LEVEL env (default INFO) controls verbosity.

At DEBUG, the format widens to include thread name + source location so
heartbeat/probe/worker-loop trace lines are easier to correlate across
the four background tasks."""
from __future__ import annotations
import logging
import os
import sys

# Cached — read once at configure() time so hot-path code can branch
# without re-parsing env on every tick.
_DEBUG = False


def is_debug() -> bool:
    return _DEBUG


def configure() -> logging.Logger:
    global _DEBUG
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    _DEBUG = (level == "DEBUG")
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_wayback", False)
               for h in root.handlers):
        h = logging.StreamHandler(sys.stdout)
        h._wayback = True  # type: ignore[attr-defined]
        if _DEBUG:
            fmt = ("%(asctime)s %(levelname)-7s [%(threadName)s] "
                   "%(name)s %(filename)s:%(lineno)d: %(message)s")
        else:
            fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        h.setFormatter(logging.Formatter(
            fmt,
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ))
        root.addHandler(h)
    root.setLevel(level)
    for n in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(n).setLevel(level)
    # At DEBUG, also crank the noisy third-party loggers so HTTP traffic
    # from urllib3/httpx/httpcore and asyncio internals show through.
    if _DEBUG:
        for n in ("asyncio", "urllib3", "urllib3.connectionpool",
                  "httpcore", "httpx", "sqlite3"):
            logging.getLogger(n).setLevel("DEBUG")
    lg = logging.getLogger("wayback")
    if _DEBUG:
        lg.debug(
            "LOG_LEVEL=DEBUG — extreme verbosity on: probe heartbeats, "
            "worker-loop ticks, SSE pings, event-bus publishes, "
            "subprocess env, CDX requests and DB deferrals will all "
            "be traced. Expect high log volume."
        )
    return lg


def get(module: str) -> logging.Logger:
    return logging.getLogger(f"wayback.{module}")
