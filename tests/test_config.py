"""
Tests for src/familyvault/config.py
Run with: python -m pytest tests/test_config.py -v
"""

from pathlib import Path
from familyvault import config


def test_project_root_is_a_directory():
    assert config.PROJECT_ROOT.is_dir()


def test_database_path_is_under_project_root():
    assert config.DATABASE_PATH.is_relative_to(config.PROJECT_ROOT)


def test_thumbnail_dir_is_under_project_root():
    assert config.THUMBNAIL_DIR.is_relative_to(config.PROJECT_ROOT)


def test_image_extensions_are_lowercase():
    for ext in config.IMAGE_EXTENSIONS:
        assert ext == ext.lower(), f"{ext!r} must be lowercase"


def test_video_extensions_are_lowercase():
    for ext in config.VIDEO_EXTENSIONS:
        assert ext == ext.lower(), f"{ext!r} must be lowercase"


def test_image_extensions_start_with_dot():
    for ext in config.IMAGE_EXTENSIONS:
        assert ext.startswith("."), f"{ext!r} must start with '.'"


def test_video_extensions_start_with_dot():
    for ext in config.VIDEO_EXTENSIONS:
        assert ext.startswith("."), f"{ext!r} must start with '.'"


def test_supported_extensions_is_union():
    assert config.SUPPORTED_EXTENSIONS == config.IMAGE_EXTENSIONS | config.VIDEO_EXTENSIONS


def test_no_overlap_between_image_and_video():
    overlap = config.IMAGE_EXTENSIONS & config.VIDEO_EXTENSIONS
    assert overlap == set(), f"Extensions in both sets: {overlap}"


def test_scan_batch_size_is_positive():
    assert config.SCAN_BATCH_SIZE > 0


def test_scan_follow_symlinks_is_false():
    assert config.SCAN_FOLLOW_SYMLINKS is False


def test_scan_skip_hidden_is_bool():
    assert isinstance(config.SCAN_SKIP_HIDDEN, bool)