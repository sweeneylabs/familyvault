"""
Tests for src/familyvault/metadata.py
Run with: python -m pytest tests/test_metadata.py -v
"""

import pytest
from pathlib import Path
from PIL import Image
from familyvault.metadata import (
    extract_metadata,
    MediaMetadata,
    _parse_exif_datetime,
    _to_decimal,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def plain_jpg(tmp_path) -> Path:
    """A valid JPEG with no EXIF data."""
    path = tmp_path / "plain.jpg"
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def plain_png(tmp_path) -> Path:
    """A valid PNG file."""
    path = tmp_path / "plain.png"
    img = Image.new("RGB", (200, 150), color=(0, 255, 0))
    img.save(path, format="PNG")
    return path


@pytest.fixture
def plain_mp4(tmp_path) -> Path:
    """A minimal MP4-like file (not a real video — tests graceful fallback)."""
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"\x00" * 1024)
    return path


@pytest.fixture
def unsupported_file(tmp_path) -> Path:
    """A file type not supported by metadata extraction."""
    path = tmp_path / "document.pdf"
    path.write_bytes(b"fake pdf content")
    return path


# ── extract_metadata — images ──────────────────────────────────────────────────

def test_extract_metadata_returns_media_metadata(plain_jpg):
    result = extract_metadata(plain_jpg)
    assert isinstance(result, MediaMetadata)


def test_extract_metadata_jpg_has_dimensions(plain_jpg):
    result = extract_metadata(plain_jpg)
    assert result.width == 100
    assert result.height == 80


def test_extract_metadata_png_has_dimensions(plain_png):
    result = extract_metadata(plain_png)
    assert result.width == 200
    assert result.height == 150


def test_extract_metadata_jpg_path_is_set(plain_jpg):
    result = extract_metadata(plain_jpg)
    assert result.path == plain_jpg


def test_extract_metadata_plain_jpg_no_datetime(plain_jpg):
    result = extract_metadata(plain_jpg)
    assert result.taken_at is None


def test_extract_metadata_plain_jpg_no_gps(plain_jpg):
    result = extract_metadata(plain_jpg)
    assert result.has_gps is False


def test_extract_metadata_plain_jpg_no_camera(plain_jpg):
    result = extract_metadata(plain_jpg)
    assert result.camera_make is None
    assert result.camera_model is None


def test_extract_metadata_unsupported_returns_none(unsupported_file):
    result = extract_metadata(unsupported_file)
    assert result is None


# ── extract_metadata — videos ──────────────────────────────────────────────────

def test_extract_metadata_video_returns_media_metadata(plain_mp4):
    result = extract_metadata(plain_mp4)
    assert isinstance(result, MediaMetadata)


def test_extract_metadata_video_path_is_set(plain_mp4):
    result = extract_metadata(plain_mp4)
    assert result.path == plain_mp4


def test_extract_metadata_fake_video_graceful_fallback(plain_mp4):
    """A fake MP4 should not raise — it should return empty metadata."""
    result = extract_metadata(plain_mp4)
    assert result is not None


# ── MediaMetadata properties ───────────────────────────────────────────────────

def test_has_dimensions_true():
    m = MediaMetadata(path=Path("x.jpg"), width=100, height=80)
    assert m.has_dimensions is True


def test_has_dimensions_false():
    m = MediaMetadata(path=Path("x.jpg"))
    assert m.has_dimensions is False


def test_megapixels_calculated():
    m = MediaMetadata(path=Path("x.jpg"), width=4000, height=3000)
    assert m.megapixels == 12.0


def test_megapixels_none_when_no_dimensions():
    m = MediaMetadata(path=Path("x.jpg"))
    assert m.megapixels is None


def test_has_gps_true():
    m = MediaMetadata(path=Path("x.jpg"), gps_lat=37.7749, gps_lon=-122.4194)
    assert m.has_gps is True


def test_has_gps_false():
    m = MediaMetadata(path=Path("x.jpg"))
    assert m.has_gps is False


def test_has_datetime_true():
    m = MediaMetadata(path=Path("x.jpg"), taken_at="2023-06-15T14:30:00")
    assert m.has_datetime is True


def test_has_datetime_false():
    m = MediaMetadata(path=Path("x.jpg"))
    assert m.has_datetime is False


# ── Helper functions ───────────────────────────────────────────────────────────

def test_parse_exif_datetime_valid():
    result = _parse_exif_datetime("2023:06:15 14:30:00")
    assert result == "2023-06-15T14:30:00"


def test_parse_exif_datetime_invalid_returns_none():
    result = _parse_exif_datetime("not a date")
    assert result is None


def test_to_decimal_valid():
    result = _to_decimal((37, 46, 29.0))
    assert abs(result - 37.7747) < 0.001


def test_to_decimal_invalid_returns_none():
    result = _to_decimal("bad data")
    assert result is None