"""
Tests for src/familyvault/thumbnailer.py
Run with: python -m pytest tests/test_thumbnailer.py -v
"""

import pytest
from pathlib import Path
from PIL import Image

from familyvault import config
from familyvault.thumbnailer import (
    generate_thumbnail,
    thumbnail_path,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_thumbnails(tmp_path, monkeypatch):
    """Redirect thumbnails to a temp directory for every test."""
    monkeypatch.setattr(config, "THUMBNAIL_DIR", tmp_path / "thumbnails")
    import familyvault.thumbnailer as thumbnailer_module
    monkeypatch.setattr(thumbnailer_module, "THUMBNAIL_DIR", tmp_path / "thumbnails")


@pytest.fixture
def plain_jpg(tmp_path) -> Path:
    path = tmp_path / "photo.jpg"
    img = Image.new("RGB", (800, 600), color=(100, 149, 237))
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def plain_png(tmp_path) -> Path:
    path = tmp_path / "photo.png"
    img = Image.new("RGBA", (1000, 750), color=(255, 100, 50, 255))
    img.save(path, format="PNG")
    return path


@pytest.fixture
def large_jpg(tmp_path) -> Path:
    """An image larger than the thumbnail size."""
    path = tmp_path / "large.jpg"
    img = Image.new("RGB", (4000, 3000), color=(50, 100, 200))
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def fake_mp4(tmp_path) -> Path:
    """A fake MP4 — tests graceful fallback."""
    path = tmp_path / "video.mp4"
    path.write_bytes(b"\x00" * 1024)
    return path


@pytest.fixture
def unsupported(tmp_path) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"fake pdf")
    return path


# ── thumbnail_path ─────────────────────────────────────────────────────────────

def test_thumbnail_path_returns_path(plain_jpg):
    result = thumbnail_path(plain_jpg)
    assert isinstance(result, Path)


def test_thumbnail_path_ends_with_jpg(plain_jpg):
    result = thumbnail_path(plain_jpg)
    assert result.suffix == ".jpg"


def test_thumbnail_path_is_deterministic(plain_jpg):
    assert thumbnail_path(plain_jpg) == thumbnail_path(plain_jpg)


def test_thumbnail_path_differs_for_different_files(plain_jpg, plain_png):
    assert thumbnail_path(plain_jpg) != thumbnail_path(plain_png)


def test_thumbnail_path_has_two_char_subdir(plain_jpg):
    result = thumbnail_path(plain_jpg)
    assert len(result.parent.name) == 2


# ── generate_thumbnail — images ────────────────────────────────────────────────

def test_generate_thumbnail_returns_path(plain_jpg):
    result = generate_thumbnail(plain_jpg)
    assert isinstance(result, Path)


def test_generate_thumbnail_file_exists(plain_jpg):
    result = generate_thumbnail(plain_jpg)
    assert result.exists()


def test_generate_thumbnail_is_jpeg(plain_jpg):
    result = generate_thumbnail(plain_jpg)
    with Image.open(result) as img:
        assert img.format == "JPEG"


def test_generate_thumbnail_respects_size_limit(large_jpg):
    result = generate_thumbnail(large_jpg)
    with Image.open(result) as img:
        assert img.width <= 400
        assert img.height <= 400


def test_generate_thumbnail_png_converted_to_jpeg(plain_png):
    result = generate_thumbnail(plain_png)
    assert result is not None
    with Image.open(result) as img:
        assert img.format == "JPEG"


def test_generate_thumbnail_cached_on_second_call(plain_jpg):
    first = generate_thumbnail(plain_jpg)
    second = generate_thumbnail(plain_jpg)
    assert first == second


def test_generate_thumbnail_creates_subdirectory(plain_jpg):
    result = generate_thumbnail(plain_jpg)
    assert result.parent.is_dir()


# ── generate_thumbnail — videos ────────────────────────────────────────────────

def test_generate_thumbnail_fake_video_does_not_raise(fake_mp4):
    """A fake video file should fail gracefully, not crash."""
    result = generate_thumbnail(fake_mp4)
    assert result is None or isinstance(result, Path)


# ── generate_thumbnail — unsupported ──────────────────────────────────────────

def test_generate_thumbnail_unsupported_returns_none(unsupported):
    result = generate_thumbnail(unsupported)
    assert result is None