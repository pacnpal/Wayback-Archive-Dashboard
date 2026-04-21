"""On-disk metadata cache for per-host snapshot directories.

CodeQL's path-injection taint tracker only recognizes the
``resolve() → is_relative_to(base)`` barrier when both operations
appear in the same scope as the filesystem sink. Helper functions
that take or return ``Path`` objects break that pattern: the analyzer
sees tainted data cross the function boundary and re-flags each sink.

Every filesystem operation in this module therefore inlines the
barrier immediately before the sink — no helper indirection, no
``Path`` parameters passed between functions. Callers supply raw
``host`` / ``ts`` strings; each function resolves, checks the
barrier, then acts. It's repetitive but CodeQL-clean.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import jobs, log as _log

logger = _log.get("sites_index")


INDEX_NAME = ".index.json"

# Stamped on every cache entry. Bump when _measure semantics change so the
# lazy refresh in get_index() recomputes pre-existing rows. Missing/older
# `v` values also trigger a recompute, which retires entries written by
# pre-staleness-check builds (those numbers froze at the snapshot's first
# measurement and never tracked subsequent file additions).
SNAPSHOT_VERSION = 2

_TS_RE = re.compile(r"^\d{14}$")


def is_snapshot_ts(name: str) -> bool:
    """Snapshot dir names are always `YYYYMMDDHHMMSS` (14 digits).
    Anything else under `<host>/` is archived site content, not a snapshot."""
    return bool(_TS_RE.match(name))


def _load(host: str) -> dict:
    # Inline barrier: resolve + is_relative_to in the same scope as the
    # read sink so CodeQL sees the guard.
    base = jobs.OUTPUT_ROOT.resolve()
    try:
        p = (jobs.OUTPUT_ROOT / host / INDEX_NAME).resolve()
    except OSError:
        return {}
    if not p.is_relative_to(base):
        return {}
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _atomic_write(host: str, data: dict) -> None:
    base = jobs.OUTPUT_ROOT.resolve()
    try:
        d = (jobs.OUTPUT_ROOT / host).resolve()
    except OSError:
        return
    if not d.is_relative_to(base):
        return
    if not d.is_dir():
        return
    fd, tmp_raw = tempfile.mkstemp(prefix=".index.", dir=str(d))
    # mkstemp constructs its own filename from its tainted ``dir=``
    # input, so re-verify inline before using the returned path as a
    # write sink.
    try:
        tmp = Path(tmp_raw).resolve()
    except OSError:
        os.close(fd)
        return
    if not tmp.is_relative_to(base):
        os.close(fd)
        return
    target = d / INDEX_NAME
    # Defense in depth: target is derived from ``d`` which we just
    # barrier-checked, but compute the check in the same scope as
    # the ``os.replace`` sink so CodeQL sees it.
    if not target.resolve().is_relative_to(base):
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(str(tmp), str(target))
    except Exception:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass


def _measure_host_snapshot(host: str, ts: str) -> dict:
    """Walk the snapshot dir for `host/ts`; return {size_bytes, file_count,
    mtime, v}. Empty dict on escape or missing dir. A subdir vanishing
    mid-walk is tolerated — partial counts are returned instead of zero."""
    import time as _time
    t0 = _time.monotonic()
    base = jobs.OUTPUT_ROOT.resolve()
    try:
        snapshot_dir = (jobs.OUTPUT_ROOT / host / ts).resolve()
    except OSError:
        return {}
    if not snapshot_dir.is_relative_to(base):
        return {}
    if not snapshot_dir.is_dir():
        logger.debug("measure skip (not a dir) dir=%s", snapshot_dir)
        return {}
    logger.debug("measure start dir=%s", snapshot_dir)
    size = 0
    files = 0
    stack: list[Path] = [snapshot_dir]
    while stack:
        cur = stack.pop()
        # Every iteration: re-assert the scanned directory stays
        # inside OUTPUT_ROOT. Even though we pushed from the tree we
        # already barrier-checked at entry, a symlink could point
        # outward and CodeQL doesn't know that.
        try:
            cur_resolved = cur.resolve()
        except OSError:
            continue
        if not cur_resolved.is_relative_to(base):
            continue
        try:
            with os.scandir(str(cur_resolved)) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        files += 1
                        try:
                            size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
        except FileNotFoundError:
            continue
    try:
        mtime = snapshot_dir.stat().st_mtime
        mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        mtime_iso = None
    dur_ms = (_time.monotonic() - t0) * 1000
    logger.debug("measure done dir=%s files=%d size=%d mtime=%s duration=%.1fms",
                 snapshot_dir, files, size, mtime_iso, dur_ms)
    return {"size_bytes": size, "file_count": files, "mtime": mtime_iso,
            "v": SNAPSHOT_VERSION}


def _list_snapshot_ts(host: str) -> list[str]:
    """Enumerate valid snapshot timestamps under ``host``. Barrier is
    inline so CodeQL sees the check at the iterdir sink."""
    base = jobs.OUTPUT_ROOT.resolve()
    try:
        host_dir = (jobs.OUTPUT_ROOT / host).resolve()
    except OSError:
        return []
    if not host_dir.is_relative_to(base):
        return []
    if not host_dir.is_dir():
        return []
    out: list[str] = []
    for p in host_dir.iterdir():
        if p.is_dir() and is_snapshot_ts(p.name):
            out.append(p.name)
    return out


def _snapshot_mtime_iso(host: str, ts: str) -> Optional[str]:
    """Barrier-checked mtime lookup for a specific snapshot dir."""
    base = jobs.OUTPUT_ROOT.resolve()
    try:
        sd = (jobs.OUTPUT_ROOT / host / ts).resolve()
    except OSError:
        return None
    if not sd.is_relative_to(base):
        return None
    try:
        return datetime.fromtimestamp(
            sd.stat().st_mtime, tz=timezone.utc,
        ).replace(microsecond=0).isoformat()
    except OSError:
        return None


def _snapshot_is_dir(host: str, ts: str) -> bool:
    base = jobs.OUTPUT_ROOT.resolve()
    try:
        sd = (jobs.OUTPUT_ROOT / host / ts).resolve()
    except OSError:
        return False
    if not sd.is_relative_to(base):
        return False
    return sd.is_dir()


def refresh_index(host: str, timestamps: Optional[list[str]] = None) -> dict:
    """Refresh index entries for `timestamps` (or all snapshots if None)."""
    logger.debug("refresh_index host=%s timestamps=%s",
                 host, timestamps if timestamps else "<all>")
    snaps = timestamps if timestamps is not None else _list_snapshot_ts(host)
    if timestamps is None and not snaps:
        # Empty host dir or escape — don't touch the index.
        return {}
    idx = _load(host)
    changed = False
    for ts in snaps:
        if not _snapshot_is_dir(host, ts):
            if ts in idx:
                del idx[ts]
                changed = True
            continue
        m = _measure_host_snapshot(host, ts)
        if m and idx.get(ts) != m:
            idx[ts] = m
            changed = True
    if changed:
        _atomic_write(host, idx)
        logger.debug("refresh_index host=%s wrote %d entries", host, len(idx))
    else:
        logger.debug("refresh_index host=%s no changes", host)
    return idx


def get_index(host: str) -> dict:
    """Return cached index, lazily refreshing entries whose dir mtime moved
    or whose cache predates SNAPSHOT_VERSION."""
    on_disk = set(_list_snapshot_ts(host))
    if not on_disk:
        # Host dir missing or escape — still return cache contents if
        # any, minus entries that no longer resolve.
        idx = _load(host)
        if not idx:
            return {}
    else:
        idx = _load(host)
    dirty = False
    # Drop index entries whose dir was removed.
    for ts in list(idx.keys()):
        if ts not in on_disk:
            del idx[ts]
            dirty = True
    for ts in on_disk:
        if not _snapshot_is_dir(host, ts):
            continue
        cached = idx.get(ts)
        if cached and cached.get("v") == SNAPSHOT_VERSION:
            cur_mtime = _snapshot_mtime_iso(host, ts)
            if cur_mtime == cached.get("mtime"):
                continue
        m = _measure_host_snapshot(host, ts)
        if m and idx.get(ts) != m:
            idx[ts] = m
            dirty = True
    if dirty:
        _atomic_write(host, idx)
    return idx


def drop_entry(host: str, timestamp: str) -> None:
    idx = _load(host)
    if timestamp in idx:
        del idx[timestamp]
        _atomic_write(host, idx)
