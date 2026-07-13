"""
Tests for src/familyvault/api.py
Run with: python -m pytest tests/test_api.py -v
"""

import pytest
from fastapi.testclient import TestClient

from familyvault.api import app
from familyvault.database import init_db, save_scan
from familyvault.scanner import scan
from familyvault import config


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    import familyvault.database as db_module
    monkeypatch.setattr(db_module, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "test.db")
    init_db()


@pytest.fixture
def media_dir(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"fake jpg")
    (tmp_path / "photo2.jpg").write_bytes(b"fake jpg 2")
    (tmp_path / "video.mp4").write_bytes(b"fake mp4")
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def client_with_scan(client, media_dir):
    result = scan(media_dir)
    save_scan(result)
    return client


# ── /health ────────────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_status_ok(client):
    response = client.get("/health")
    assert response.json()["status"] == "ok"


def test_health_returns_total_files(client):
    response = client.get("/health")
    assert "total_files" in response.json()


# ── /scans ─────────────────────────────────────────────────────────────────────

def test_list_scans_returns_200(client):
    response = client.get("/scans")
    assert response.status_code == 200


def test_list_scans_empty(client):
    response = client.get("/scans")
    assert response.json()["scans"] == []


def test_list_scans_after_save(client_with_scan):
    response = client_with_scan.get("/scans")
    assert response.json()["count"] == 1


def test_list_scans_returns_count(client_with_scan):
    response = client_with_scan.get("/scans")
    assert "count" in response.json()


# ── /scans/{scan_id} ───────────────────────────────────────────────────────────

def test_get_scan_returns_200(client_with_scan):
    response = client_with_scan.get("/scans/1")
    assert response.status_code == 200


def test_get_scan_returns_correct_id(client_with_scan):
    response = client_with_scan.get("/scans/1")
    assert response.json()["id"] == 1


def test_get_scan_not_found(client):
    response = client.get("/scans/999")
    assert response.status_code == 404


# ── /scans/{scan_id}/files ─────────────────────────────────────────────────────

def test_list_scan_files_returns_200(client_with_scan):
    response = client_with_scan.get("/scans/1/files")
    assert response.status_code == 200


def test_list_scan_files_returns_all(client_with_scan):
    response = client_with_scan.get("/scans/1/files")
    assert response.json()["total"] == 3


def test_list_scan_files_filter_by_extension(client_with_scan):
    response = client_with_scan.get("/scans/1/files?extension=.jpg")
    assert response.json()["total"] == 2


def test_list_scan_files_filter_by_image(client_with_scan):
    response = client_with_scan.get("/scans/1/files?media_type=image")
    assert response.json()["total"] == 2


def test_list_scan_files_filter_by_video(client_with_scan):
    response = client_with_scan.get("/scans/1/files?media_type=video")
    assert response.json()["total"] == 1


def test_list_scan_files_pagination(client_with_scan):
    response = client_with_scan.get("/scans/1/files?limit=2&offset=0")
    assert len(response.json()["files"]) == 2


def test_list_scan_files_offset(client_with_scan):
    response = client_with_scan.get("/scans/1/files?limit=10&offset=2")
    assert len(response.json()["files"]) == 1


def test_list_scan_files_not_found(client):
    response = client.get("/scans/999/files")
    assert response.status_code == 404


# ── /files/count ───────────────────────────────────────────────────────────────

def test_total_file_count_returns_200(client):
    response = client.get("/files/count")
    assert response.status_code == 200


def test_total_file_count_is_zero_initially(client):
    response = client.get("/files/count")
    assert response.json()["total_files"] == 0


def test_total_file_count_after_scan(client_with_scan):
    response = client_with_scan.get("/files/count")
    assert response.json()["total_files"] == 3
