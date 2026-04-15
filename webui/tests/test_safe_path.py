"""Sanitizer at the OUTPUT_ROOT chokepoint rejects path-escape attempts."""
import pytest

from webui import jobs
from webui.safe_path import safe_output_child


def test_accepts_normal_host(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    (tmp_path / "example.com").mkdir()
    p = safe_output_child("example.com")
    assert p == (tmp_path / "example.com").resolve()


def test_accepts_host_and_ts(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    (tmp_path / "example.com" / "20240101000000").mkdir(parents=True)
    p = safe_output_child("example.com", "20240101000000")
    assert p == (tmp_path / "example.com" / "20240101000000").resolve()


def test_rejects_parent_traversal_host(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    with pytest.raises(ValueError):
        safe_output_child("..")


def test_rejects_parent_traversal_ts(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    (tmp_path / "example.com").mkdir()
    with pytest.raises(ValueError):
        safe_output_child("example.com", "../../etc")


def test_rejects_absolute_host(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    with pytest.raises(ValueError):
        safe_output_child("/etc/passwd")


def test_returns_path_inside_root_even_for_nonexistent(tmp_path, monkeypatch):
    # safe_output_child doesn't require the dir exists; it only enforces
    # containment. Callers (_host_dir etc.) do their own .is_dir() check.
    monkeypatch.setattr(jobs, "OUTPUT_ROOT", tmp_path)
    p = safe_output_child("new-host.example")
    assert p == (tmp_path / "new-host.example").resolve()
