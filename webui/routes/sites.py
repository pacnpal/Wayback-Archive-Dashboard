"""Per-site (host) overview: local + remote snapshots + date picker."""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import jobs, wayback

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _local_hosts() -> list[tuple[str, int, str]]:
    """Return (host, snapshot_count, newest_ts) tuples from disk."""
    root = jobs.OUTPUT_ROOT
    if not root.exists():
        return []
    out = []
    for h in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        snaps = sorted([s.name for s in h.iterdir() if s.is_dir()], reverse=True)
        if snaps:
            out.append((h.name, len(snaps), snaps[0]))
    return out


def _local_snapshots(host: str) -> list[str]:
    d = jobs.OUTPUT_ROOT / host
    if not d.is_dir():
        return []
    return sorted((s.name for s in d.iterdir() if s.is_dir()), reverse=True)


@router.get("/sites", response_class=HTMLResponse)
async def sites_index(request: Request):
    return templates.TemplateResponse("sites_index.html", {
        "request": request, "hosts": _local_hosts(),
    })


@router.get("/sites/{host}", response_class=HTMLResponse)
async def site_detail(request: Request, host: str, from_year: str = "", to_year: str = "",
                       remote: int = 1):
    local = _local_snapshots(host)
    remote_snaps: list[dict] = []
    remote_error = None
    if remote:
        target_url = f"https://{host}"
        try:
            remote_snaps = wayback.list_snapshots(
                target_url,
                from_year=int(from_year) if from_year.isdigit() else None,
                to_year=int(to_year) if to_year.isdigit() else None,
                limit=10000,
                collapse_digits=14,  # no collapsing; show all
            )
        except Exception as e:
            remote_error = str(e)

    # Group remote snapshots by date for a calendar-ish index
    by_day: dict[str, list[dict]] = defaultdict(list)
    years: set[str] = set()
    for s in remote_snaps:
        ts = s["timestamp"]
        day = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
        by_day[day].append(s)
        years.add(ts[0:4])
    days_sorted = sorted(by_day.keys(), reverse=True)
    local_set = set(local)

    return templates.TemplateResponse("site_detail.html", {
        "request": request,
        "host": host,
        "local": local,
        "local_set": local_set,
        "remote_snaps": remote_snaps,
        "remote_error": remote_error,
        "by_day": by_day,
        "days_sorted": days_sorted,
        "years": sorted(years, reverse=True),
        "from_year": from_year,
        "to_year": to_year,
        "remote": int(remote),
    })


@router.post("/sites/{host}/archive")
async def archive_one(host: str, request: Request):
    form = await request.form()
    ts = (form.get("timestamp") or "").strip() or None
    from .dashboard import _default_flags
    jobs.enqueue(f"https://{host}", ts, _default_flags())
    return RedirectResponse(f"/sites/{host}", status_code=303)
