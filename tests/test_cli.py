"""
Tests for src/familyvault/cli.py
Run with: python -m pytest tests/test_cli.py -v
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from familyvault.cli import _format_size, _format_duration, cmd_scan
from familyvault import config


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect database to a temp directory for every test."""
    monkeypatch.setattr(config, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")

    import familyvault.database as db_module
    monkeypatch.setattr(db_module, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "test.db")


@pytest.fixture
def media_dir(tmp_path):
    """Temporary directory with media files."""
    (tmp_path / "photo.jpg").write_bytes(b"fake jpg")
    (tmp_path / "video.mp4").write_bytes(b"fake mp4")
    return tmp_path


@pytest.fixture
def scan_args(media_dir):
    """Simulated argparse namespace for the scan command."""
    class Args:
        path = str(media_dir)
    return Args()


# ── _format_size ───────────────────────────────────────────────────────────────

def test_format_size_bytes():
    assert _format_size(512) == "512 B"


def test_format_size_kilobytes():
    assert _format_size(2048) == "2.0 KB"


def test_format_size_megabytes():
    assert _format_size(5 * 1024 * 1024) == "5.0 MB"


def test_format_size_gigabytes():
    assert _format_size(2 * 1024 ** 3) == "2.00 GB"


# ── _format_duration ───────────────────────────────────────────────────────────

def test_format_duration_seconds():
    assert _format_duration(5.0) == "5.0s"


def test_format_duration_minutes():
    result = _format_duration(90.0)
    assert result == "1m 30.0s"


def test_format_duration_zero():
    assert _format_duration(0.0) == "0.0s"


# ── cmd_scan ───────────────────────────────────────────────────────────────────

def test_cmd_scan_returns_zero_on_success(scan_args):
    assert cmd_scan(scan_args) == 0


def test_cmd_scan_returns_one_for_missing_path(tmp_path):
    class Args:
        path = str(tmp_path / "nonexistent")
    assert cmd_scan(Args()) == 1


def test_cmd_scan_returns_one_for_file_path(tmp_path):
    f = tmp_path / "file.jpg"
    f.write_bytes(b"fake")
    class Args:
        path = str(f)
    assert cmd_scan(Args()) == 1


def test_cmd_scan_accepts_tilde_path(monkeypatch, media_dir):
    """Ensure ~ in paths is expanded correctly."""
    monkeypatch.setenv("HOME", str(media_dir.parent))
    class Args:
        path = "~/" + media_dir.name
    assert cmd_scan(Args()) == 0


def test_cmd_scan_prints_summary(scan_args, capsys):
    cmd_scan(scan_args)
    output = capsys.readouterr().out
    assert "FamilyVault Scan Complete" in output


def test_cmd_scan_prints_image_count(scan_args, capsys):
    cmd_scan(scan_args)
    output = capsys.readouterr().out
    assert "Images" in output


def test_cmd_scan_prints_video_count(scan_args, capsys):
    cmd_scan(scan_args)
    output = capsys.readouterr().out
    assert "Videos" in output


def test_cmd_scan_prints_scan_id(scan_args, capsys):
    cmd_scan(scan_args)
    output = capsys.readouterr().out
    assert "Scan ID" in output