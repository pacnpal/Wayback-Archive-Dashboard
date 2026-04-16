"""Smoke tests for the lazy /audit-cell route used by site_detail.html."""
import asyncio

from webui import jobs
from webui.routes.sites import audit_cell


def _run(coro):
    return asyncio.run(coro)


def _populate_snapshot(root, host, ts, files):
    snap = root / host / ts
    snap.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = snap / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return snap


def test_returns_dash_for_no_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / ".dashboard.db")
    jobs.init_db()
    _populate_snapshot(tmp_path, "example.com", "20240101000000",
                       {"index.html": "<html><body>nothing here</body></html>"})
    resp = _run(audit_cell(host="example.com", ts="20240101000000"))
    assert resp.status_code == 200


def test_returns_100_when_all_present(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / ".dashboard.db")
    jobs.init_db()
    _populate_snapshot(tmp_path, "example.com", "20240101000000", {
        "index.html": '<a href="page.html">x</a>',
        "page.html": "ok",
    })
    resp = _run(audit_cell(host="example.com", ts="20240101000000"))
    assert resp.status_code == 200
    assert b"100%" in resp.body
    assert b"status-ok" in resp.body


def test_returns_pct_with_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / ".dashboard.db")
    jobs.init_db()
    _populate_snapshot(tmp_path, "example.com", "20240101000000", {
        "index.html": '<a href="a.html">a</a><a href="b.html">b</a><a href="c.html">c</a>',
        "a.html": "ok",
    })
    resp = _run(audit_cell(host="example.com", ts="20240101000000"))
    assert resp.status_code == 200
    assert b"missing" in resp.body
    assert b"href=" in resp.body


def test_skips_audit_during_active_job(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / ".dashboard.db")
    jobs.init_db()
    _populate_snapshot(tmp_path, "example.com", "20240101000000",
                       {"index.html": "<html></html>"})
    # Insert a running job row directly so we don't trigger the worker loop.
    with jobs.connect() as c:
        c.execute(
            "INSERT INTO jobs(target_url,timestamp,wayback_url,host,site_dir,"
            "log_path,flags_json,status,created_at) VALUES "
            "(?,?,?,?,?,?,?,?,?)",
            ("https://example.com/", "20240101000000",
             "https://web.archive.org/web/20240101000000/https://example.com/",
             "example.com", str(tmp_path / "example.com" / "20240101000000"),
             "/tmp/log", "{}", "running", jobs.now_iso()),
        )
    resp = _run(audit_cell(host="example.com", ts="20240101000000"))
    assert resp.status_code == 200
    assert b"audit-pending" in resp.body
