"""Entry point that wraps upstream wayback_archive.cli.main with a disk
cache on `download_file`, enabling job-level resume: any file that already
exists on disk under the configured OUTPUT_DIR is served from disk instead
of being re-downloaded from Wayback.

Usage (from webui.jobs): python -m webui.wayback_resume_shim
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


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
            print(
                f"[dashboard] purging suspected in-flight file before resume: "
                f"{local_path}",
                flush=True,
            )
            local_path.unlink()
    except Exception as e:
        print(f"[dashboard] could not purge in-flight file: {e}", flush=True)


def main() -> None:
    _patch()
    _purge_partial_last_file()
    from wayback_archive.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
    sys.exit(0)
