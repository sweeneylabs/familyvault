"""
Tests for src/familyvault/scanner.py
Run with: python -m pytest tests/test_scanner.py -v
"""

import pytest
from pathlib import Path

from familyvault.scanner import scan, MediaFile, ScanResult


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def media_dir(tmp_path):
    """A temporary directory with a mix of media and non-media files."""
    (tmp_path / "photo.jpg").write_bytes(b"fake jpg")
    (tmp_path / "photo.JPG").write_bytes(b"fake jpg uppercase")
    (tmp_path / "video.mp4").write_bytes(b"fake mp4")
    (tmp_path / "document.pdf").write_bytes(b"fake pdf")
    (tmp_path / "notes.txt").write_bytes(b"fake txt")
    subdir = tmp_path / "subfolder"
    subdir.mkdir()
    (subdir / "nested.png").write_bytes(b"fake png")
    (subdir / "nested.mov").write_bytes(b"fake mov")
    return tmp_path


@pytest.fixture
def empty_dir(tmp_path):
    """A temporary directory with no media files."""
    (tmp_path / "readme.txt").write_bytes(b"not a media file")
    return tmp_path


@pytest.fixture
def hidden_dir(tmp_path):
    """A temporary directory with hidden files and folders."""
    (tmp_path / ".hidden_photo.jpg").write_bytes(b"hidden jpg")
    hidden_sub = tmp_path / ".hidden_folder"
    hidden_sub.mkdir()
    (hidden_sub / "photo.jpg").write_bytes(b"jpg in hidden folder")
    (tmp_path / "visible.jpg").write_bytes(b"visible jpg")
    return tmp_path


# ── Basic scan tests ───────────────────────────────────────────────────────────

def test_scan_returns_scan_result(media_dir):
    result = scan(media_dir)
    assert isinstance(result, ScanResult)


def test_scan_finds_jpg(media_dir):
    result = scan(media_dir)
    extensions = {f.extension for f in result.media_files}
    assert ".jpg" in extensions


def test_scan_finds_mp4(media_dir):
    result = scan(media_dir)
    extensions = {f.extension for f in result.media_files}
    assert ".mp4" in extensions


def test_scan_finds_nested_files(media_dir):
    result = scan(media_dir)
    paths = {f.path.name for f in result.media_files}
    assert "nested.png" in paths
    assert "nested.mov" in paths


def test_scan_excludes_pdf(media_dir):
    result = scan(media_dir)
    extensions = {f.extension for f in result.media_files}
    assert ".pdf" not in extensions


def test_scan_excludes_txt(media_dir):
    result = scan(media_dir)
    extensions = {f.extension for f in result.media_files}
    assert ".txt" not in extensions


def test_scan_normalises_extension_to_lowercase(media_dir):
    result = scan(media_dir)
    extensions = [f.extension for f in result.media_files]
    assert all(ext == ext.lower() for ext in extensions)


def test_scan_empty_directory(empty_dir):
    result = scan(empty_dir)
    assert result.total_count == 0


def test_scan_skips_hidden_files(hidden_dir):
    result = scan(hidden_dir)
    names = {f.path.name for f in result.media_files}
    assert ".hidden_photo.jpg" not in names
    assert "visible.jpg" in names


def test_scan_skips_hidden_folders(hidden_dir):
    result = scan(hidden_dir)
    names = {f.path.name for f in result.media_files}
    assert "photo.jpg" not in names


# ── ScanResult property tests ──────────────────────────────────────────────────

def test_scan_result_image_count(media_dir):
    result = scan(media_dir)
    assert result.image_count >= 2


def test_scan_result_video_count(media_dir):
    result = scan(media_dir)
    assert result.video_count >= 2


def test_scan_result_total_count(media_dir):
    result = scan(media_dir)
    assert result.total_count == result.image_count + result.video_count


def test_scan_result_total_size_is_positive(media_dir):
    result = scan(media_dir)
    assert result.total_size_bytes > 0


def test_scan_result_summary_is_string(media_dir):
    result = scan(media_dir)
    assert isinstance(result.summary(), str)


# ── MediaFile property tests ───────────────────────────────────────────────────

def test_media_file_is_image(tmp_path):
    f = tmp_path / "test.jpg"
    f.write_bytes(b"fake")
    result = scan(tmp_path)
    image = next(m for m in result.media_files if m.extension == ".jpg")
    assert image.is_image is True
    assert image.is_video is False


def test_media_file_is_video(tmp_path):
    f = tmp_path / "test.mp4"
    f.write_bytes(b"fake")
    result = scan(tmp_path)
    video = next(m for m in result.media_files if m.extension == ".mp4")
    assert video.is_video is True
    assert video.is_image is False


# ── Error handling ─────────────────────────────────────────────────────────────

def test_scan_raises_if_path_does_not_exist():
    with pytest.raises(NotADirectoryError):
        scan(Path("/nonexistent/path/xyz"))


def test_scan_raises_if_path_is_a_file(tmp_path):
    f = tmp_path / "file.jpg"
    f.write_bytes(b"fake")
    with pytest.raises(NotADirectoryError):
        scan(f)