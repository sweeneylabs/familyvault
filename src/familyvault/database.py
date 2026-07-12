"""
FamilyVault Database
Creates and manages a local SQLite database for storing scan results.
All data is stored in database/familyvault.db at the project root.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from familyvault.config import DATABASE_DIR, DATABASE_PATH
from familyvault.logger import get_logger
from familyvault.scanner import MediaFile, ScanResult

log = get_logger(__name__)


# ── Schema ─────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path     TEXT    NOT NULL,
    scanned_at    TEXT    NOT NULL,
    total_count   INTEGER NOT NULL DEFAULT 0,
    image_count   INTEGER NOT NULL DEFAULT 0,
    video_count   INTEGER NOT NULL DEFAULT 0,
    total_size_bytes INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL REFERENCES scans(id),
    path        TEXT    NOT NULL,
    extension   TEXT    NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    is_image    INTEGER NOT NULL DEFAULT 0,
    is_video    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_media_files_scan_id
    ON media_files(scan_id);

CREATE INDEX IF NOT EXISTS idx_media_files_extension
    ON media_files(extension);
"""


# ── Connection ─────────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create the database file and apply the schema if not already present.
    Safe to call multiple times — uses CREATE IF NOT EXISTS throughout.
    """
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
    log.debug(f"Database ready at {DATABASE_PATH}")


@contextmanager
def _connect():
    """Open a database connection with foreign keys enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Write ──────────────────────────────────────────────────────────────────────

def save_scan(result: ScanResult) -> int:
    """
    Persist a ScanResult to the database.

    Args:
        result: Completed scan to store.

    Returns:
        The scan ID assigned by the database.
    """
    scanned_at = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scans
                (root_path, scanned_at, total_count, image_count, video_count,
                 total_size_bytes, skipped_count, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(result.root),
                scanned_at,
                result.total_count,
                result.image_count,
                result.video_count,
                result.total_size_bytes,
                result.skipped_count,
                result.error_count,
            ),
        )
        scan_id = cursor.lastrowid

        conn.executemany(
            """
            INSERT INTO media_files
                (scan_id, path, extension, size_bytes, is_image, is_video)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    scan_id,
                    str(f.path),
                    f.extension,
                    f.size_bytes,
                    int(f.is_image),
                    int(f.is_video),
                )
                for f in result.media_files
            ],
        )

    log.info(f"Saved scan #{scan_id} — {result.total_count} files")
    return scan_id


# ── Read ───────────────────────────────────────────────────────────────────────

def get_all_scans() -> list[dict]:
    """Return a list of all scan records, most recent first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scans ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_scan_files(scan_id: int) -> list[dict]:
    """Return all media files recorded under a given scan ID."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM media_files WHERE scan_id = ?",
            (scan_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_file_count() -> int:
    """Return the total number of media files stored across all scans."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM media_files").fetchone()
    return row[0]