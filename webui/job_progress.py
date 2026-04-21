"""Parse upstream wayback_archive log tails for a live progress reading."""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional

from . import log as _log
logger = _log.get("job_progress")

_STEP_RE = re.compile(r"\[(\d+)(?:\s*\(limit:\s*\d+\))?\]")
_QUEUE_RE = re.compile(r"Queue:\s*(\d+)\s+files remaining")
_DONE_RE = re.compile(r"Download Complete!", re.IGNORECASE)
_HEADER_RE = re.compile(r"Wayback-Archive Downloader")
_TAIL_BYTES = 65536


def read_progress(log_path: str, max_files: Optional[int] = None) -> Optional[dict]:
    p = Path(log_path)
    if not p.is_file():
        logger.debug("read_progress miss (no file) path=%s", log_path)
        return None
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > _TAIL_BYTES:
                f.seek(-_TAIL_BYTES, os.SEEK_END)
            data = f.read()
    except OSError as e:
        logger.debug("read_progress read error path=%s err=%s", log_path, e)
        return None
    logger.debug("read_progress path=%s size=%d tail=%d max_files=%s",
                 log_path, size, len(data), max_files)
    text = data.decode("utf-8", errors="replace")

    # A job that was re-queued after a container restart will have multiple
    # "Wayback-Archive Downloader" banners and multiple [1]..[N] sequences in
    # the same log. Only count progress from the most recent run.
    headers = [m.start() for m in _HEADER_RE.finditer(text)]
    if headers:
        text = text[headers[-1]:]

    downloaded = max((int(m.group(1)) for m in _STEP_RE.finditer(text)), default=0)
    queue_matches = _QUEUE_RE.findall(text)
    queued = int(queue_matches[-1]) if queue_matches else 0
    done = bool(_DONE_RE.search(text))

    if max_files:
        total = max_files
    elif downloaded or queued:
        total = downloaded + queued
    else:
        total = 0
    if total <= 0:
        percent = 0
    else:
        percent = int(downloaded * 100 / total)
    if done:
        percent = 100
    elif percent >= 100:
        percent = 99
    # Surface the log's mtime as a "last activity" signal so the
    # dashboard can distinguish a healthily-slow job (upstream chewing
    # through failing URLs, each taking ~15 s) from a genuinely wedged
    # one (subprocess in unrecoverable sleep, no log writes for many
    # minutes). We return the mtime as a Unix timestamp; the UI
    # converts to relative ("12s ago" / "6m ago") and applies a
    # staleness threshold for the visual warning.
    try:
        last_activity = int(p.stat().st_mtime)
    except OSError:
        last_activity = 0
    result = {
        "done": done,
        "downloaded": downloaded,
        "queued": queued,
        "total": total,
        "percent": percent,
        "last_activity": last_activity,
    }
    logger.debug("read_progress parsed path=%s result=%s", log_path, result)
    return result
