"""
Tests for src/familyvault/duplicates.py
Run with: python -m pytest tests/test_duplicates.py -v
"""

import pytest
import shutil
from pathlib import Path
from PIL import Image

from familyvault.duplicates import (
    find_duplicates,
    file_hash,
    perceptual_hash,
    DuplicateGroup,
    DuplicateReport,
)


@pytest.fixture
def plain_jpg(tmp_path) -> Path:
    path = tmp_path / "photo.png"
    img = Image.new("RGB", (400, 400))
    pixels = img.load()
    for x in range(400):
        for y in range(400):
            pixels[x, y] = (int(x * 255 / 400), int(y * 255 / 400), 128)
    img.save(path, format="PNG")
    return path


@pytest.fixture
def different_jpg(tmp_path) -> Path:
    path = tmp_path / "different.png"
    img = Image.new("RGB", (400, 400))
    pixels = img.load()
    for x in range(400):
        for y in range(400):
            pixels[x, y] = (255 - int(x * 255 / 400), 128, int(y * 255 / 400))
    img.save(path, format="PNG")
    return path


@pytest.fixture
def copy_jpg(tmp_path, plain_jpg) -> Path:
    copy = tmp_path / "copy.png"
    shutil.copy2(plain_jpg, copy)
    return copy


@pytest.fixture
def stable_img(tmp_path) -> Path:
    path = tmp_path / "stable.png"
    img = Image.new("RGB", (400, 400))
    pixels = img.load()
    for x in range(400):
        for y in range(400):
            if x < 200 and y < 200:
                pixels[x, y] = (255, 0, 0)
            elif x >= 200 and y < 200:
                pixels[x, y] = (0, 255, 0)
            elif x < 200 and y >= 200:
                pixels[x, y] = (0, 0, 255)
            else:
                pixels[x, y] = (255, 255, 0)
    img.save(path, format="PNG")
    return path


@pytest.fixture
def stable_img_resized(tmp_path, stable_img) -> Path:
    path = tmp_path / "stable_resized.png"
    with Image.open(stable_img) as img:
        resized = img.resize((200, 200), Image.LANCZOS)
        resized.save(path, format="PNG")
    return path


@pytest.fixture
def text_file(tmp_path) -> Path:
    path = tmp_path / "notes.txt"
    path.write_text("some text content")
    return path


def test_file_hash_returns_string(plain_jpg):
    result = file_hash(plain_jpg)
    assert isinstance(result, str)


def test_file_hash_is_deterministic(plain_jpg):
    assert file_hash(plain_jpg) == file_hash(plain_jpg)


def test_file_hash_differs_for_different_files(plain_jpg, different_jpg):
    assert file_hash(plain_jpg) != file_hash(different_jpg)


def test_file_hash_same_for_copies(plain_jpg, copy_jpg):
    assert file_hash(plain_jpg) == file_hash(copy_jpg)


def test_file_hash_nonexistent_returns_none():
    assert file_hash(Path("/nonexistent/file.jpg")) is None


def test_file_hash_length(plain_jpg):
    result = file_hash(plain_jpg)
    assert len(result) == 64


def test_perceptual_hash_returns_value(plain_jpg):
    result = perceptual_hash(plain_jpg)
    assert result is not None


def test_perceptual_hash_is_deterministic(plain_jpg):
    assert perceptual_hash(plain_jpg) == perceptual_hash(plain_jpg)


def test_perceptual_hash_differs_for_different_images(plain_jpg, different_jpg):
    assert perceptual_hash(plain_jpg) != perceptual_hash(different_jpg)


def test_perceptual_hash_similar_for_resized(stable_img, stable_img_resized):
    h1 = perceptual_hash(stable_img)
    h2 = perceptual_hash(stable_img_resized)
    assert (h1 - h2) <= 4


def test_perceptual_hash_nonexistent_returns_none():
    assert perceptual_hash(Path("/nonexistent/file.jpg")) is None


def test_duplicate_group_count(plain_jpg, copy_jpg):
    group = DuplicateGroup(files=[plain_jpg, copy_jpg], similarity="exact")
    assert group.count == 2


def test_duplicate_group_keeper_is_path(plain_jpg, copy_jpg):
    group = DuplicateGroup(files=[plain_jpg, copy_jpg], similarity="exact")
    assert isinstance(group.keeper, Path)


def test_duplicate_group_duplicates_excludes_keeper(plain_jpg, copy_jpg):
    group = DuplicateGroup(files=[plain_jpg, copy_jpg], similarity="exact")
    assert group.keeper not in group.duplicates


def test_duplicate_group_duplicates_count(plain_jpg, copy_jpg):
    group = DuplicateGroup(files=[plain_jpg, copy_jpg], similarity="exact")
    assert len(group.duplicates) == 1


def test_duplicate_report_summary_is_string():
    report = DuplicateReport(scanned=10)
    assert isinstance(report.summary(), str)


def test_duplicate_report_total_duplicates():
    group = DuplicateGroup(
        files=[Path("a.jpg"), Path("b.jpg"), Path("c.jpg")],
        similarity="exact"
    )
    report = DuplicateReport(scanned=3, groups=[group])
    assert report.total_duplicates == 2


def test_find_duplicates_returns_report(plain_jpg):
    report = find_duplicates([plain_jpg])
    assert isinstance(report, DuplicateReport)


def test_find_duplicates_empty_list():
    report = find_duplicates([])
    assert report.total_groups == 0
    assert report.scanned == 0


def test_find_duplicates_no_duplicates(plain_jpg, different_jpg):
    report = find_duplicates([plain_jpg, different_jpg])
    assert report.total_groups == 0


def test_find_duplicates_detects_exact_copies(plain_jpg, copy_jpg):
    report = find_duplicates([plain_jpg, copy_jpg])
    assert len(report.exact_groups) == 1


def test_find_duplicates_exact_group_has_both_files(plain_jpg, copy_jpg):
    report = find_duplicates([plain_jpg, copy_jpg])
    group = report.exact_groups[0]
    paths = {str(p) for p in group.files}
    assert str(plain_jpg) in paths
    assert str(copy_jpg) in paths


def test_find_duplicates_detects_perceptual_duplicates(stable_img, stable_img_resized):
    report = find_duplicates([stable_img, stable_img_resized])
    assert report.total_groups >= 1


def test_find_duplicates_scanned_count(plain_jpg, different_jpg):
    report = find_duplicates([plain_jpg, different_jpg])
    assert report.scanned == 2


def test_find_duplicates_non_image_skipped_in_perceptual(plain_jpg, text_file):
    report = find_duplicates([plain_jpg, text_file])
    assert report.total_groups == 0
