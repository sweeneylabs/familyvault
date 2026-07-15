"""
Tests for src/familyvault/database.py
Run with: python -m pytest tests/test_database.py -v
"""

import pytest
from pathlib import Path

from familyvault.database import (
    init_db,
    save_scan,
    get_all_scans,
    get_scan_files,
    get_file_count,
    save_caption,
    get_files_needing_captions,
    get_media_needing_captions,
)
from familyvault.scanner import scan, ScanResult, MediaFile
from familyvault import config


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    Redirect the database to a temporary directory for every test.
    Ensures tests never touch the real database.
    """
    monkeypatch.setattr(config, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")

    import familyvault.database as db_module
    monkeypatch.setattr(db_module, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "test.db")

    init_db()


@pytest.fixture
def media_dir(tmp_path):
    """Temporary directory with a few media files."""
    (tmp_path / "photo.jpg").write_bytes(b"fake jpg")
    (tmp_path / "video.mp4").write_bytes(b"fake mp4")
    (tmp_path / "photo.png").write_bytes(b"fake png")
    return tmp_path


@pytest.fixture
def saved_scan(media_dir):
    """A scan that has already been saved to the database."""
    result = scan(media_dir)
    scan_id = save_scan(result)
    return scan_id, result


# ── init_db ────────────────────────────────────────────────────────────────────

def test_init_db_creates_database_file(tmp_path, monkeypatch):
    import familyvault.database as db_module
    db_path = tmp_path / "new.db"
    monkeypatch.setattr(db_module, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "DATABASE_PATH", db_path)
    init_db()
    assert db_path.exists()


def test_init_db_is_idempotent():
    init_db()
    init_db()  # Should not raise


# ── save_scan ──────────────────────────────────────────────────────────────────

def test_save_scan_returns_integer(saved_scan):
    scan_id, _ = saved_scan
    assert isinstance(scan_id, int)


def test_save_scan_returns_positive_id(saved_scan):
    scan_id, _ = saved_scan
    assert scan_id > 0


def test_save_scan_stores_scan_record(saved_scan):
    scan_id, _ = saved_scan
    scans = get_all_scans()
    assert any(s["id"] == scan_id for s in scans)


def test_save_scan_stores_correct_file_count(saved_scan):
    scan_id, result = saved_scan
    files = get_scan_files(scan_id)
    assert len(files) == result.total_count


def test_save_scan_stores_root_path(media_dir):
    result = scan(media_dir)
    scan_id = save_scan(result)
    scans = get_all_scans()
    record = next(s for s in scans if s["id"] == scan_id)
    assert record["root_path"] == str(media_dir)


def test_save_scan_stores_image_count(saved_scan):
    scan_id, result = saved_scan
    scans = get_all_scans()
    record = next(s for s in scans if s["id"] == scan_id)
    assert record["image_count"] == result.image_count


def test_save_scan_stores_video_count(saved_scan):
    scan_id, result = saved_scan
    scans = get_all_scans()
    record = next(s for s in scans if s["id"] == scan_id)
    assert record["video_count"] == result.video_count


def test_save_empty_scan(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"not media")
    result = scan(tmp_path)
    scan_id = save_scan(result)
    files = get_scan_files(scan_id)
    assert len(files) == 0


# ── get_all_scans ──────────────────────────────────────────────────────────────

def test_get_all_scans_returns_list():
    assert isinstance(get_all_scans(), list)


def test_get_all_scans_most_recent_first(media_dir):
    result = scan(media_dir)
    id1 = save_scan(result)
    id2 = save_scan(result)
    scans = get_all_scans()
    ids = [s["id"] for s in scans]
    assert ids.index(id2) < ids.index(id1)


# ── get_scan_files ─────────────────────────────────────────────────────────────

def test_get_scan_files_returns_list(saved_scan):
    scan_id, _ = saved_scan
    assert isinstance(get_scan_files(scan_id), list)


def test_get_scan_files_contains_correct_extensions(saved_scan):
    scan_id, _ = saved_scan
    files = get_scan_files(scan_id)
    extensions = {f["extension"] for f in files}
    assert ".jpg" in extensions
    assert ".mp4" in extensions


def test_get_scan_files_unknown_id_returns_empty():
    assert get_scan_files(99999) == []


# ── get_file_count ─────────────────────────────────────────────────────────────

def test_get_file_count_returns_int():
    assert isinstance(get_file_count(), int)


def test_get_file_count_increases_after_save(media_dir):
    before = get_file_count()
    result = scan(media_dir)
    save_scan(result)
    after = get_file_count()
    assert after > before


# ── save_caption ───────────────────────────────────────────────────────────────

def test_new_media_files_have_null_caption_by_default(saved_scan):
    scan_id, _ = saved_scan
    files = get_scan_files(scan_id)
    assert all(f["caption"] is None for f in files)


def test_save_caption_updates_caption(saved_scan):
    scan_id, _ = saved_scan
    files = get_scan_files(scan_id)
    file_id = files[0]["id"]

    save_caption(file_id, "a dog running on the beach")

    updated_files = get_scan_files(scan_id)
    updated = next(f for f in updated_files if f["id"] == file_id)
    assert updated["caption"] == "a dog running on the beach"


def test_save_caption_only_updates_target_file(saved_scan):
    scan_id, _ = saved_scan
    files = get_scan_files(scan_id)
    target_id = files[0]["id"]
    other_ids = [f["id"] for f in files[1:]]

    save_caption(target_id, "a birthday cake with candles")

    updated_files = get_scan_files(scan_id)
    for f in updated_files:
        if f["id"] in other_ids:
            assert f["caption"] is None


# ── get_files_needing_captions ───────────────────────────────────────────────────

def test_get_files_needing_captions_returns_list():
    assert isinstance(get_files_needing_captions(), list)


def test_get_files_needing_captions_only_returns_images(saved_scan):
    scan_id, _ = saved_scan
    needing = get_files_needing_captions()
    assert all(f["is_image"] == 1 for f in needing)
    assert all(f["is_video"] == 0 for f in needing)


def test_get_files_needing_captions_excludes_captioned_files(saved_scan):
    scan_id, _ = saved_scan
    files = get_scan_files(scan_id)
    image_file = next(f for f in files if f["is_image"] == 1)

    save_caption(image_file["id"], "a sunset over the water")

    needing = get_files_needing_captions()
    remaining_ids = [f["id"] for f in needing]
    assert image_file["id"] not in remaining_ids


def test_get_files_needing_captions_respects_limit(saved_scan):
    scan_id, _ = saved_scan
    needing = get_files_needing_captions(limit=1)
    assert len(needing) == 1


# ── get_media_needing_captions ───────────────────────────────────────────────────

def test_get_media_needing_captions_returns_list():
    assert isinstance(get_media_needing_captions(), list)


def test_get_media_needing_captions_includes_videos(saved_scan):
    scan_id, _ = saved_scan
    needing = get_media_needing_captions()
    assert any(f["is_video"] == 1 for f in needing)


def test_get_media_needing_captions_includes_images(saved_scan):
    scan_id, _ = saved_scan
    needing = get_media_needing_captions()
    assert any(f["is_image"] == 1 for f in needing)


def test_get_media_needing_captions_returns_all_uncaptioned(saved_scan):
    scan_id, result = saved_scan
    needing = get_media_needing_captions()
    assert len(needing) == result.total_count


def test_get_media_needing_captions_excludes_captioned_files(saved_scan):
    scan_id, _ = saved_scan
    files = get_scan_files(scan_id)
    video_file = next(f for f in files if f["is_video"] == 1)

    save_caption(video_file["id"], "a birthday party in the backyard")

    needing = get_media_needing_captions()
    remaining_ids = [f["id"] for f in needing]
    assert video_file["id"] not in remaining_ids


def test_get_media_needing_captions_respects_limit(saved_scan):
    scan_id, _ = saved_scan
    needing = get_media_needing_captions(limit=1)
    assert len(needing) == 1
