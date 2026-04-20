"""Tests for REPAIR_PATHS_FILE plumbing.

Regression for the production crash where a 235 KB path list (5 000+
rels from a single 1997-era snapshot) pushed the REPAIR_PATHS env var
past Linux's MAX_ARG_STRLEN of 128 KB, so the kernel failed the
subprocess spawn with E2BIG and the job hit terminal error before the
shim even started.
"""
from __future__ import annotations
import importlib
import json
from pathlib import Path


def _load_shim():
    import webui.wayback_repair_shim as shim
    importlib.reload(shim)
    return shim


def _stub_downloader(monkeypatch, shim):
    class _StubDL:
        def __init__(self, cfg):
            self.original_timestamp = "20200101000000"

        def download_file(self, url):
            return b""
    monkeypatch.setattr(shim, "_alt_timestamps", lambda *a, **kw: [])
    monkeypatch.setattr(shim, "_download_from_wayback", lambda *a, **kw: None)

    class _Cfg:
        pass
    import sys
    parent = type(sys)("wayback_archive")
    cfg_mod = type(sys)("wayback_archive.config")
    cfg_mod.Config = _Cfg
    dl_mod = type(sys)("wayback_archive.downloader")
    dl_mod.WaybackDownloader = _StubDL
    parent.config = cfg_mod
    parent.downloader = dl_mod
    sys.modules["wayback_archive"] = parent
    sys.modules["wayback_archive.config"] = cfg_mod
    sys.modules["wayback_archive.downloader"] = dl_mod


def test_shim_reads_paths_from_repair_paths_file(tmp_path, monkeypatch):
    shim = _load_shim()
    _stub_downloader(monkeypatch, shim)
    paths_file = tmp_path / ".repair-paths"
    paths_file.write_text("a.html\nb/c.gif\nd.css\n", encoding="utf-8")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WAYBACK_URL",
                       "https://web.archive.org/web/20200101000000/https://x.com/")
    monkeypatch.setenv("REPAIR_PATHS_FILE", str(paths_file))
    monkeypatch.delenv("REPAIR_PATHS", raising=False)

    shim.main()
    unrec = Path(tmp_path) / ".unrecoverable.json"
    assert unrec.is_file(), "shim should have reached the path loop"
    data = json.loads(unrec.read_text())
    assert set(data) == {"a.html", "b/c.gif", "d.css"}


def test_shim_falls_back_to_env_var_when_no_file(tmp_path, monkeypatch):
    shim = _load_shim()
    _stub_downloader(monkeypatch, shim)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WAYBACK_URL",
                       "https://web.archive.org/web/20200101000000/https://x.com/")
    monkeypatch.setenv("REPAIR_PATHS", "one.html|two.css")
    monkeypatch.delenv("REPAIR_PATHS_FILE", raising=False)
    shim.main()
    unrec = Path(tmp_path) / ".unrecoverable.json"
    assert unrec.is_file()
    data = json.loads(unrec.read_text())
    assert set(data) == {"one.html", "two.css"}


def test_shim_bails_with_no_paths_source(tmp_path, monkeypatch):
    shim = _load_shim()
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WAYBACK_URL",
                       "https://web.archive.org/web/20200101000000/https://x.com/")
    monkeypatch.delenv("REPAIR_PATHS", raising=False)
    monkeypatch.delenv("REPAIR_PATHS_FILE", raising=False)
    assert shim.main() == 2


def test_jobs_writes_repair_paths_file_for_big_lists(tmp_path, monkeypatch):
    """The dashboard used to set env['REPAIR_PATHS'] = joined payload.
    A 5000-entry list is ~235 KB, past Linux MAX_ARG_STRLEN (128 KB),
    so subprocess spawn failed with E2BIG. Payload now lands on disk
    and only a small path goes through the env."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    import webui.jobs as j
    importlib.reload(j)
    j.init_db()

    big_list = [f"support/files/rel-{i}/index.html" for i in range(5000)]
    site_dir = tmp_path / "x.com" / "20200101000000"
    site_dir.mkdir(parents=True)
    with j.connect() as c:
        c.execute(
            """INSERT INTO jobs (target_url,timestamp,wayback_url,host,
               site_dir,log_path,flags_json,status,created_at,repair_paths_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("https://x.com/", "20200101000000",
             "https://web.archive.org/web/20200101000000/https://x.com/",
             "x.com", str(site_dir), str(site_dir / ".log"),
             "{}", "pending", j.now_iso(), json.dumps(big_list)),
        )
        row = c.execute("SELECT * FROM jobs WHERE id=1").fetchone()

    captured = {}

    async def fake_exec(*args, env=None, **kw):
        captured["env"] = dict(env)
        raise RuntimeError("stop here")
    monkeypatch.setattr(j.asyncio, "create_subprocess_exec", fake_exec)

    import asyncio
    try:
        asyncio.run(j._run_one(row))
    except RuntimeError as e:
        assert str(e) == "stop here"

    env = captured["env"]
    assert "REPAIR_PATHS_FILE" in env
    assert "REPAIR_PATHS" not in env
    assert all(len(v.encode()) < 131072 for v in env.values())

    written = Path(env["REPAIR_PATHS_FILE"]).read_text(encoding="utf-8")
    assert written.count("\n") == len(big_list) - 1
    assert written.splitlines()[0] == big_list[0]
    assert written.splitlines()[-1] == big_list[-1]
