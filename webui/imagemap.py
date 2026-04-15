"""NCSA/CERN server-side imagemap replacement.

Archived pages from 1993–late-1990s used `<img ismap>` to post click
coordinates to a server-side `imagemap` CGI, which read a plain-text
`.map` file defining rect/poly/circle shapes and their target URLs, then
302'd to the shape containing the click. The CGI is permanently gone from
Wayback, so we reconstruct the lookup ourselves:

- `parse_map(text)` parses NCSA-format map bodies.
- `resolve(shapes, x, y)` returns the first matching URL (or the default).
- `recover_map(local_path, host, ts)` best-effort-fetches the raw text
  from Wayback CDX when our local copy is the CGI's HTML error page.

Format reference (NCSA httpd imagemap):
    # comments start with hash
    default http://host/fallback
    rect    http://host/a 10,20 50,60
    poly    http://host/b 0,0 100,0 50,100
    circle  http://host/c 30,30 40,30      # center + a point on the edge
    point   http://host/d 80,80            # nearest-neighbor if no rect/poly/circle hit
"""
from __future__ import annotations
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger("wayback.imagemap")

_SHAPE_RE = re.compile(r"^\s*(default|rect|poly|circle|point)\b", re.IGNORECASE)
_QUERY_COORD_RE = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*$")


@dataclass
class Shape:
    kind: str                              # 'default' | 'rect' | 'poly' | 'circle' | 'point'
    url: str
    coords: list[tuple[int, int]] = field(default_factory=list)


def parse_map(text: str) -> list[Shape]:
    """Parse NCSA-format map text. Unrecognized lines are skipped silently."""
    shapes: list[Shape] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or not _SHAPE_RE.match(line):
            continue
        parts = line.split()
        kind = parts[0].lower()
        if kind == "default":
            if len(parts) >= 2:
                shapes.append(Shape("default", parts[1]))
            continue
        if len(parts) < 2:
            continue
        url = parts[1]
        coords: list[tuple[int, int]] = []
        for tok in parts[2:]:
            m = _QUERY_COORD_RE.match(tok)
            if m:
                coords.append((int(m.group(1)), int(m.group(2))))
        shapes.append(Shape(kind, url, coords))
    return shapes


def _in_rect(x: int, y: int, c: list[tuple[int, int]]) -> bool:
    if len(c) < 2:
        return False
    (x1, y1), (x2, y2) = c[0], c[1]
    lo_x, hi_x = min(x1, x2), max(x1, x2)
    lo_y, hi_y = min(y1, y2), max(y1, y2)
    return lo_x <= x <= hi_x and lo_y <= y <= hi_y


def _in_circle(x: int, y: int, c: list[tuple[int, int]]) -> bool:
    if len(c) < 2:
        return False
    (cx, cy), (ex, ey) = c[0], c[1]
    r2 = (ex - cx) ** 2 + (ey - cy) ** 2
    return (x - cx) ** 2 + (y - cy) ** 2 <= r2


def _in_poly(x: int, y: int, c: list[tuple[int, int]]) -> bool:
    if len(c) < 3:
        return False
    inside = False
    n = len(c)
    j = n - 1
    for i in range(n):
        xi, yi = c[i]
        xj, yj = c[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def resolve(shapes: Iterable[Shape], x: int, y: int) -> str | None:
    """Return the URL of the first rect/poly/circle containing (x,y).
    If none match, fall back to the closest `point` (NCSA behavior), then
    the `default`, else None."""
    shapes = list(shapes)
    # First: hard shapes in declaration order (NCSA semantics).
    for s in shapes:
        c = s.coords
        if s.kind == "rect" and _in_rect(x, y, c):
            return s.url
        if s.kind == "circle" and _in_circle(x, y, c):
            return s.url
        if s.kind == "poly" and _in_poly(x, y, c):
            return s.url
    # Then: nearest point, if any.
    points = [s for s in shapes if s.kind == "point" and s.coords]
    if points:
        best = min(points, key=lambda s: (s.coords[0][0] - x) ** 2 + (s.coords[0][1] - y) ** 2)
        return best.url
    # Last: default.
    for s in shapes:
        if s.kind == "default":
            return s.url
    return None


def parse_query_coords(q: str) -> tuple[int, int] | None:
    """Parse the `?x,y` ismap query string."""
    m = _QUERY_COORD_RE.match(q or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def is_plausible_map_text(body: bytes) -> bool:
    """True if `body` starts with a line that looks like an NCSA map directive.
    Used to distinguish real map files from Wayback CGI error HTML."""
    try:
        head = body[:512].decode("ascii", errors="ignore")
    except Exception:
        return False
    for line in head.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        return bool(_SHAPE_RE.match(stripped))
    return False


def recover_map(local_path: Path, host: str, ts: str,
                session=None, cdx_limit: int = 30) -> bytes | None:
    """If `local_path` holds the Wayback CGI's HTML error page, try CDX
    to find an alt-timestamp capture whose body is real NCSA text. Writes
    the recovered bytes to `local_path` and returns them. Returns None
    (and leaves the file alone) if nothing plausible was found."""
    from .cdx import alt_timestamps, raw_fetch
    # Build the origin URL from the snapshot-relative path.
    try:
        rel = local_path.relative_to(local_path.parent.parent.parent)
    except ValueError:
        rel = local_path.name
    origin_url = f"http://{host}/{str(rel).replace(chr(92), '/')}"

    # Session is optional — callers that already have a requests session
    # (the repair shim) can pass it; otherwise make a throwaway.
    if session is None:
        try:
            import requests
            session = requests.Session()
            session.headers.update({"User-Agent": "Wayback-Archive-Imagemap/1.0"})
        except Exception:
            return None

    alts = alt_timestamps(origin_url, ts, limit=cdx_limit)
    for alt in alts:
        data = raw_fetch(session, alt, origin_url)
        if not data:
            continue
        if is_plausible_map_text(data):
            try:
                local_path.write_bytes(data)
            except OSError as e:
                log.warning("write %s failed: %s", local_path, e)
                return None
            log.info("imagemap recovered host=%s path=%s alt=%s bytes=%d",
                     host, rel, alt, len(data))
            return data
    return None
