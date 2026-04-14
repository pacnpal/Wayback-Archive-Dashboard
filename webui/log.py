"""Centralised Python logging setup. Writes to stdout so docker logs
captures everything; LOG_LEVEL env (default INFO) controls verbosity."""
from __future__ import annotations
import logging
import os
import sys


def configure() -> logging.Logger:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_wayback", False)
               for h in root.handlers):
        h = logging.StreamHandler(sys.stdout)
        h._wayback = True  # type: ignore[attr-defined]
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ))
        root.addHandler(h)
    root.setLevel(level)
    for n in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(n).setLevel(level)
    return logging.getLogger("wayback")


def get(module: str) -> logging.Logger:
    return logging.getLogger(f"wayback.{module}")
