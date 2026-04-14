"""Entry point that wraps upstream wayback_archive.cli.main with a disk
cache on `download_file`, enabling job-level resume: any file that already
exists on disk under the configured OUTPUT_DIR is served from disk instead
of being re-downloaded from Wayback.

Usage (from webui.jobs): python -m webui.wayback_resume_shim
"""
from __future__ import annotations
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


def _setup_logger() -> logging.Logger:
    """Child-process logger: writes to stderr (captured in the per-job .log
    because jobs.py merges stderr into it) AND to /proc/1/fd/1 so lines
    reach docker logs even though stdout is redirected to a file."""
    lg = logging.getLogger("wayback.shim")
    if lg.handlers:
        return lg
    lg.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s wayback.shim: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    # stderr handler — ends up in the per-job .log (jobs.py merges stderr).
    h1 = logging.StreamHandler(sys.stderr)
    h1.setFormatter(fmt)
    lg.addHandler(h1)
    # docker logs handler — write to init's stdout inside the container.
    try:
        f = open("/proc/1/fd/1", "w", buffering=1)
        h2 = logging.StreamHandler(f)
        h2.setFormatter(fmt)
        lg.addHandler(h2)
    except Exception:
        pass
    return lg


log = _setup_logger()
_cache_hits = 0


def _patch() -> None:
    from wayback_archive import downloader as d

    _orig_download_file = d.WaybackDownloader.download_file

    def cached_download_file(self, url: str):
        # Mirror download()'s normalisation so the cache key matches
        # whatever the loop later calls _get_local_path with.
        try:
            parsed = urlparse(url)
            netloc = (parsed.netloc or "").lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            normalized = parsed._replace(
                netloc=netloc, fragment="", query=""
            ).geturl()
            local_path = self._get_local_path(normalized)
            if local_path.is_file() and local_path.stat().st_size > 0:
                global _cache_hits
                _cache_hits += 1
                log.debug("cache-hit %s", local_path)
                print(
                    f"         [resumed from disk] {local_path}",
                    flush=True,
                )
                return local_path.read_bytes()
        except Exception:
            pass
        return _orig_download_file(self, url)

    d.WaybackDownloader.download_file = cached_download_file


_STEP_LINE_RE = re.compile(r"\[\d+[^\]]*\]\s+Downloading\s+\S+:\s+(.+?)\s*$")
_OUTCOME_RE = re.compile(r"✓ Downloaded|Failed to download|\[resumed from disk\]")


def _purge_partial_last_file() -> None:
    """If the last 'Downloading X:' line in the log has no matching
    '✓ Downloaded' / 'Failed' / 'resumed from disk' outcome below it, the
    process was killed mid-write. Delete that one file so the upcoming run
    re-fetches it instead of serving a truncated copy from the disk cache."""
    out_dir = os.environ.get("OUTPUT_DIR")
    if not out_dir:
        return
    log_path = Path(out_dir) / ".log"
    if not log_path.is_file():
        return
    try:
        with log_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 32768))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return
    lines = tail.splitlines()
    last_idx = -1
    last_url = None
    for i, line in enumerate(lines):
        m = _STEP_LINE_RE.search(line)
        if m:
            last_idx = i
            last_url = m.group(1).strip()
    if last_idx < 0 or not last_url:
        return
    if _OUTCOME_RE.search("\n".join(lines[last_idx + 1:])):
        return  # the last download line did complete
    # Suspected in-flight file — drop it so the cache shim refetches.
    try:
        from wayback_archive.config import Config
        from wayback_archive.downloader import WaybackDownloader
        cfg = Config()
        if not cfg.wayback_url:
            return
        d = WaybackDownloader(cfg)
        parsed = urlparse(last_url)
        netloc = (parsed.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        normalized = parsed._replace(netloc=netloc, fragment="", query="").geturl()
        local_path = d._get_local_path(normalized)
        if local_path.is_file():
            log.warning("purge in-flight file=%s", local_path)
            local_path.unlink()
    except Exception as e:
        log.warning("could not purge in-flight file: %s", e)


def main() -> None:
    _patch()
    _purge_partial_last_file()
    host = os.environ.get("OUTPUT_DIR", "?").rstrip("/").split("/")[-2] if "/" in os.environ.get("OUTPUT_DIR", "") else "?"
    log.info("shim start output=%s", os.environ.get("OUTPUT_DIR"))
    t0 = time.monotonic()
    from wayback_archive.cli import main as cli_main
    try:
        cli_main()
    finally:
        log.info("shim end cache_hits=%d duration=%.1fs",
                 _cache_hits, time.monotonic() - t0)


if __name__ == "__main__":
    main()
    sys.exit(0)
