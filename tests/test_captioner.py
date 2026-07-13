"""
Tests for src/familyvault/captioner.py
Run with: python -m pytest tests/test_captioner.py -v
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from familyvault.captioner import caption_image, caption_batch, CaptionResult


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