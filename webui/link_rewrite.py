"""In-place rewriter for absolute-path refs inside stored archived HTML/CSS.

Archived HTML sometimes contains root-relative URLs like `/images/foo.gif`.
When served from the dashboard those resolve against the dashboard origin
and 404. This module walks a snapshot directory and rewrites such refs to
relative paths so the pages render locally under `/sites/<host>/view?...`.
"""
from __future__ import annotations
import re
from pathlib import Path
from posixpath import relpath

_URL_ATTR_RE = re.compile(
    r'''(\s(?:src|href|srcset|poster|data|action|background|formaction)\s*=\s*["'])([^"']+)(["'])''',
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r'''(url\(\s*["']?)([^)"']+)(["']?\s*\))''', re.IGNORECASE)
_HTML_EXTS = {".html", ".htm"}
_CSS_EXTS = {".css"}


def _is_absolute_path_ref(v: str) -> bool:
    v = v.strip()
    if not v.startswith("/"):
        return False
    if v.startswith("//"):
        return False
    if v.startswith("/web/"):
        return False
    return True


def _abs_to_rel(value: str, file_rel_dir: str) -> str:
    """Convert an absolute-path ref (/foo/bar.gif) to a relative path that
    resolves correctly when the served HTML lives at file_rel_dir inside the
    snapshot root."""
    v = value.strip()
    if not _is_absolute_path_ref(v):
        return value
    # Compute POSIX-style relative path from the file's dir to the target.
    target = v.lstrip("/")
    src_dir = (file_rel_dir or ".").replace("\\", "/")
    try:
        return relpath(target, src_dir)
    except ValueError:
        return value


def _rewrite_srcset(value: str, file_rel_dir: str) -> str:
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(None, 1)
        bits[0] = _abs_to_rel(bits[0], file_rel_dir)
        out.append(" ".join(bits))
    return ", ".join(out)


def rewrite_html(html: str, file_rel_dir: str) -> tuple[str, int]:
    hits = [0]

    def attr_sub(m):
        lead, val, trail = m.group(1), m.group(2), m.group(3)
        if lead.lower().strip().startswith("srcset"):
            new = _rewrite_srcset(val, file_rel_dir)
        else:
            new = _abs_to_rel(val, file_rel_dir)
        if new != val:
            hits[0] += 1
        return lead + new + trail

    def css_sub(m):
        new = _abs_to_rel(m.group(2), file_rel_dir)
        if new != m.group(2):
            hits[0] += 1
        return m.group(1) + new + m.group(3)

    html = _URL_ATTR_RE.sub(attr_sub, html)
    html = _CSS_URL_RE.sub(css_sub, html)
    return html, hits[0]


def rewrite_css(css: str, file_rel_dir: str) -> tuple[str, int]:
    hits = [0]

    def sub(m):
        new = _abs_to_rel(m.group(2), file_rel_dir)
        if new != m.group(2):
            hits[0] += 1
        return m.group(1) + new + m.group(3)

    return _CSS_URL_RE.sub(sub, css), hits[0]


def rewrite_snapshot(snapshot_dir: Path) -> dict:
    """Rewrite every HTML/CSS file under snapshot_dir in place. Returns a
    summary dict: {files_scanned, files_changed, refs_rewritten}."""
    scanned = changed = rewrites = 0
    for p in snapshot_dir.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in _HTML_EXTS and ext not in _CSS_EXTS:
            continue
        scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel_dir = str(p.parent.relative_to(snapshot_dir)).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        if ext in _HTML_EXTS:
            new_text, hits = rewrite_html(text, rel_dir)
        else:
            new_text, hits = rewrite_css(text, rel_dir)
        if hits and new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed += 1
            rewrites += hits
    return {"files_scanned": scanned, "files_changed": changed, "refs_rewritten": rewrites}
