"""Entry point that wraps upstream wayback_archive.cli.main with a disk
cache on `download_file`, enabling job-level resume: any file that already
exists on disk under the configured OUTPUT_DIR is served from disk instead
of being re-downloaded from Wayback.

Usage (from webui.jobs): python -m webui.wayback_resume_shim
"""
from __future__ import annotations
import sys
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


def main() -> None:
    _patch()
    from wayback_archive.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
    sys.exit(0)
