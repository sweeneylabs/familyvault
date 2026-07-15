"""
Tests for src/familyvault/captioner.py
Run with: python -m pytest tests/test_captioner.py -v
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from familyvault.captioner import (
    caption_image,
    caption_batch,
    caption_video,
    caption_media,
    caption_media_batch,
    CaptionResult,
)


@pytest.fixture
def plain_jpg(tmp_path) -> Path:
    path = tmp_path / "photo.jpg"
    img = Image.new("RGB", (100, 100), color=(100, 150, 200))
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def plain_png(tmp_path) -> Path:
    path = tmp_path / "photo.png"
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    img.save(path, format="PNG")
    return path


@pytest.fixture
def plain_heic(tmp_path) -> Path:
    path = tmp_path / "photo.heic"
    img = Image.new("RGB", (100, 100), color=(50, 200, 100))
    img.save(path, format="HEIF")
    return path


@pytest.fixture
def fake_video(tmp_path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake mp4 data")
    return path


@pytest.fixture
def fake_frame(tmp_path) -> Path:
    """A fake extracted video frame, as generate_thumbnail() would produce."""
    path = tmp_path / "frame.jpg"
    Image.new("RGB", (100, 100), color=(10, 20, 30)).save(path, format="JPEG")
    return path


@pytest.fixture
def unsupported(tmp_path) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"fake pdf")
    return path


@pytest.fixture
def mock_anthropic():
    with patch("familyvault.captioner.anthropic.Anthropic") as mock_class:
        client = MagicMock()
        mock_class.return_value = client
        message = MagicMock()
        message.content = [MagicMock(text="A sunny beach scene with children playing in the waves.")]
        client.messages.create.return_value = message
        yield client


# -- CaptionResult -------------------------------------------------------------

def test_caption_result_success():
    r = CaptionResult(path=Path("x.jpg"), caption="A dog in a park.")
    assert r.success is True


def test_caption_result_failure():
    r = CaptionResult(path=Path("x.jpg"), error="API error")
    assert r.success is False


def test_caption_result_no_caption_no_error():
    r = CaptionResult(path=Path("x.jpg"))
    assert r.success is False


# -- caption_image -------------------------------------------------------------

def test_caption_image_unsupported_type(unsupported):
    result = caption_image(unsupported)
    assert result.success is False
    assert result.error is not None


def test_caption_image_no_api_key(plain_jpg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = caption_image(plain_jpg)
    assert result.success is False
    assert "ANTHROPIC_API_KEY" in result.error


def test_caption_image_returns_caption(plain_jpg, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_image(plain_jpg)
    assert result.success is True
    assert isinstance(result.caption, str)
    assert len(result.caption) > 0


def test_caption_image_caption_content(plain_jpg, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_image(plain_jpg)
    assert len(result.caption) > 5


def test_caption_image_path_is_set(plain_jpg, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_image(plain_jpg)
    assert result.path == plain_jpg


def test_caption_image_png(plain_png, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_image(plain_png)
    assert result.success is True


def test_caption_image_api_error(plain_jpg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("familyvault.captioner.anthropic.Anthropic") as mock_class:
        mock_class.side_effect = Exception("Connection error")
        result = caption_image(plain_jpg)
    assert result.success is False
    assert result.error is not None


# -- caption_image (HEIC) --------------------------------------------------------

def test_caption_image_heic_returns_caption(plain_heic, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_image(plain_heic)
    assert result.success is True
    assert isinstance(result.caption, str)
    assert len(result.caption) > 0


def test_caption_image_heic_sent_as_jpeg(plain_heic, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    caption_image(plain_heic)

    call_kwargs = mock_anthropic.messages.create.call_args.kwargs
    content_blocks = call_kwargs["messages"][0]["content"]
    image_block = next(b for b in content_blocks if b["type"] == "image")

    assert image_block["source"]["media_type"] == "image/jpeg"


def test_caption_image_heic_path_is_original_heic(plain_heic, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_image(plain_heic)
    assert result.path == plain_heic
    assert result.path.suffix.lower() == ".heic"


# -- caption_video ---------------------------------------------------------------

def test_caption_video_returns_caption(fake_video, fake_frame, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("familyvault.captioner.generate_thumbnail", return_value=fake_frame):
        result = caption_video(fake_video)
    assert result.success is True
    assert isinstance(result.caption, str)
    assert len(result.caption) > 0


def test_caption_video_path_is_original_video(fake_video, fake_frame, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("familyvault.captioner.generate_thumbnail", return_value=fake_frame):
        result = caption_video(fake_video)
    assert result.path == fake_video
    assert result.path.suffix.lower() == ".mp4"


def test_caption_video_frame_extraction_fails(fake_video, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("familyvault.captioner.generate_thumbnail", return_value=None):
        result = caption_video(fake_video)
    assert result.success is False
    assert result.error is not None


def test_caption_video_unsupported_type(unsupported):
    result = caption_video(unsupported)
    assert result.success is False
    assert result.error is not None


def test_caption_video_no_api_key(fake_video, fake_frame, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("familyvault.captioner.generate_thumbnail", return_value=fake_frame):
        result = caption_video(fake_video)
    assert result.success is False
    assert "ANTHROPIC_API_KEY" in result.error


# -- caption_media -----------------------------------------------------------------

def test_caption_media_dispatches_to_image(plain_jpg, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    result = caption_media(plain_jpg)
    assert result.success is True
    assert result.path == plain_jpg


def test_caption_media_dispatches_to_video(fake_video, fake_frame, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("familyvault.captioner.generate_thumbnail", return_value=fake_frame):
        result = caption_media(fake_video)
    assert result.success is True
    assert result.path == fake_video


# -- caption_batch -------------------------------------------------------------

def test_caption_batch_returns_list(plain_jpg, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_batch([plain_jpg])
    assert isinstance(results, list)


def test_caption_batch_correct_count(plain_jpg, plain_png, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_batch([plain_jpg, plain_png])
    assert len(results) == 2


def test_caption_batch_respects_max(tmp_path, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    paths = []
    for i in range(5):
        p = tmp_path / f"photo_{i}.jpg"
        Image.new("RGB", (50, 50)).save(p, format="JPEG")
        paths.append(p)
    results = caption_batch(paths, max_images=3)
    assert len(results) == 3


def test_caption_batch_skips_unsupported(plain_jpg, unsupported, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_batch([plain_jpg, unsupported])
    assert len(results) == 1


def test_caption_batch_empty_list(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_batch([])
    assert results == []


def test_caption_batch_includes_heic(plain_heic, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_batch([plain_heic])
    assert len(results) == 1
    assert results[0].success is True


def test_caption_batch_excludes_video(plain_jpg, fake_video, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_batch([plain_jpg, fake_video])
    assert len(results) == 1
    assert results[0].path == plain_jpg


# -- caption_media_batch -------------------------------------------------------------

def test_caption_media_batch_includes_images_and_videos(plain_jpg, fake_video, fake_frame, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    with patch("familyvault.captioner.generate_thumbnail", return_value=fake_frame):
        results = caption_media_batch([plain_jpg, fake_video])
    assert len(results) == 2
    result_paths = {r.path for r in results}
    assert plain_jpg in result_paths
    assert fake_video in result_paths


def test_caption_media_batch_respects_max_items(tmp_path, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    paths = []
    for i in range(5):
        p = tmp_path / f"photo_{i}.jpg"
        Image.new("RGB", (50, 50)).save(p, format="JPEG")
        paths.append(p)
    results = caption_media_batch(paths, max_items=3)
    assert len(results) == 3


def test_caption_media_batch_skips_unsupported(plain_jpg, unsupported, mock_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_media_batch([plain_jpg, unsupported])
    assert len(results) == 1


def test_caption_media_batch_empty_list(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    results = caption_media_batch([])
    assert results == []
