"""Sanitized path construction for anything under OUTPUT_DIR.

CodeQL's path-injection taint tracking recognizes `Path.is_relative_to(base)`
after a `Path.resolve()` as a barrier; returning a Path built this way stops
the taint at this function's boundary. Every downstream consumer that takes a
Path argument (audit, cleanup, index helpers) sees pre-sanitized input.
"""
from __future__ import annotations
from pathlib import Path

from . import jobs


def safe_output_child(host: str, ts: str = "") -> Path:
    """Return the resolved OUTPUT_DIR/<host>[/<ts>] path, raising ValueError
    if it would escape OUTPUT_DIR. Callers that expect a 404-on-escape should
    catch ValueError and translate; most call from routes that have already
    regex-validated host/ts, so this is defense-in-depth."""
    base = jobs.OUTPUT_ROOT.resolve()
    p = (jobs.OUTPUT_ROOT / host).resolve()
    if not p.is_relative_to(base):
        raise ValueError("path escape")
    if ts:
        p = (p / ts).resolve()
        if not p.is_relative_to(base):
            raise ValueError("path escape")
    return p
