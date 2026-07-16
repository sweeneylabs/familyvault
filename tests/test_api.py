"""
Tests for src/familyvault/api.py
Run with: python -m pytest tests/test_api.py -v
"""

import pytest
from fastapi.testclient import TestClient

from familyvault.api import app
from familyvault.database import init_db, save_scan, save_caption, get_scan_files
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


@pytest.fixture
def client_with_captions(client, media_dir):
    """A client with a scan whose files have distinct, searchable captions."""
    result = scan(media_dir)
    scan_id = save_scan(result)
    files = get_scan_files(scan_id)

    captions = [
        "A dog playing on the beach at sunset",
        "A birthday party with cake and balloons",
        "A dog running in the park",
    ]
    for f, caption in zip(files, captions):
        save_caption(f["id"], caption)

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


# ── /search ────────────────────────────────────────────────────────────────────

def test_search_returns_200(client_with_captions):
    response = client_with_captions.get("/search?q=dog")
    assert response.status_code == 200


def test_search_missing_query_returns_422(client):
    response = client.get("/search")
    assert response.status_code == 422


def test_search_empty_query_returns_422(client):
    response = client.get("/search?q=")
    assert response.status_code == 422


def test_search_returns_matching_files(client_with_captions):
    response = client_with_captions.get("/search?q=dog")
    data = response.json()
    assert data["total"] == 2
    assert len(data["files"]) == 2


def test_search_no_matches_returns_empty_list(client_with_captions):
    response = client_with_captions.get("/search?q=elephant")
    data = response.json()
    assert data["total"] == 0
    assert data["files"] == []


def test_search_includes_query_in_response(client_with_captions):
    response = client_with_captions.get("/search?q=dog")
    assert response.json()["query"] == "dog"


def test_search_is_case_insensitive(client_with_captions):
    response = client_with_captions.get("/search?q=DOG")
    assert response.json()["total"] == 2


def test_search_respects_limit(client_with_captions):
    response = client_with_captions.get("/search?q=a&limit=1")
    data = response.json()
    assert len(data["files"]) == 1
    assert data["limit"] == 1


def test_search_respects_offset(client_with_captions):
    page_1 = client_with_captions.get("/search?q=dog&limit=1&offset=0").json()
    page_2 = client_with_captions.get("/search?q=dog&limit=1&offset=1").json()
    assert page_1["files"][0]["id"] != page_2["files"][0]["id"]


def test_search_on_empty_database_returns_no_results(client):
    response = client.get("/search?q=anything")
    data = response.json()
    assert data["total"] == 0
    assert data["files"] == []


# ── Unhandled exception handling ────────────────────────────────────────────────
#
# These tests use their own TestClient with raise_server_exceptions=False.
# By default, Starlette's TestClient re-raises exceptions even when a
# handler catches them, specifically so bugs are loud during testing. To
# actually inspect the handled response (what a real client would see),
# that behavior needs to be turned off for these specific tests.

def test_unhandled_exception_returns_500(monkeypatch):
    def boom():
        raise RuntimeError("something broke")
    monkeypatch.setattr("familyvault.api.get_all_scans", boom)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/scans")
    assert response.status_code == 500


def test_unhandled_exception_returns_json_detail(monkeypatch):
    def boom():
        raise RuntimeError("something broke")
    monkeypatch.setattr("familyvault.api.get_all_scans", boom)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/scans")
    assert "detail" in response.json()


def test_unhandled_exception_does_not_leak_internal_error_text(monkeypatch):
    def boom():
        raise RuntimeError("secret internal detail that should not reach the client")
    monkeypatch.setattr("familyvault.api.get_all_scans", boom)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/scans")
    assert "secret internal detail" not in response.text


def test_http_exception_still_returns_404_not_500(client):
    # Confirms the generic Exception handler doesn't swallow HTTPException
    # and turn deliberate 404s into 500s.
    response = client.get("/scans/999")
    assert response.status_code == 404


def test_validation_error_still_returns_422_not_500(client):
    # Confirms the generic Exception handler doesn't interfere with
    # FastAPI's normal query-param validation responses.
    response = client.get("/search")
    assert response.status_code == 422
