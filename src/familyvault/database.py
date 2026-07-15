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
    is_video    INTEGER NOT NULL DEFAULT 0,
    caption     TEXT
);

CREATE INDEX IF NOT EXISTS idx_media_files_scan_id
    ON media_files(scan_id);

CREATE INDEX IF NOT EXISTS idx_media_files_extension
    ON media_files(extension);
"""

# Columns that must exist on media_files. Used by _migrate() to bring older
# databases (created before a given column existed) up to date without
# touching any existing rows.
REQUIRED_MEDIA_FILES_COLUMNS = {
    "caption": "TEXT",
}


# ── Connection ─────────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create the database file and apply the schema if not already present.
    Safe to call multiple times — uses CREATE IF NOT EXISTS throughout.
    Also runs lightweight migrations for columns added after the database
    was first created (e.g. `caption`), without affecting existing rows.
    """
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    log.debug(f"Database ready at {DATABASE_PATH}")


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Add any missing columns to media_files.

    This only runs ALTER TABLE ADD COLUMN for columns that don't already
    exist — existing rows and data are never touched. Safe to call every
    time init_db() runs.
    """
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(media_files)")
    }

    for column, col_type in REQUIRED_MEDIA_FILES_COLUMNS.items():
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE media_files ADD COLUMN {column} {col_type}"
            )
            log.info(f"Migrated media_files: added column '{column}'")


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


def save_caption(file_id: int, caption: str) -> None:
    """
    Store a caption for a single media file.

    Args:
        file_id: The media_files.id to update.
        caption: The generated caption text.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE media_files SET caption = ? WHERE id = ?",
            (caption, file_id),
        )
    log.debug(f"Saved caption for file #{file_id}")


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


def get_files_needing_captions(limit: int | None = None) -> list[dict]:
    """
    Return image files that don't have a caption yet.

    Only returns images (is_image = 1) since this predates video
    captioning support. See get_media_needing_captions() for images and
    videos together. Ordered by id so batches are processed in a stable
    order.

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) missing a caption.
    """
    query = "SELECT * FROM media_files WHERE is_image = 1 AND caption IS NULL ORDER BY id"
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_media_needing_captions(limit: int | None = None) -> list[dict]:
    """
    Return image AND video files that don't have a caption yet.

    Unlike get_files_needing_captions(), this includes videos — pairs
    with caption_media_batch(), which knows how to caption both file
    types (videos via an extracted representative frame). Ordered by id
    so batches are processed in a stable order.

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) missing a caption.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE (is_image = 1 OR is_video = 1) AND caption IS NULL "
        "ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards (% and _) so search text is matched literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_by_caption(query: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """
    Search media files by a case-insensitive substring match on caption.

    Uses a SQL LIKE query (not Python-side filtering) so this stays fast
    against a large library — matching happens in SQLite, and only the
    requested page of rows is returned. Special LIKE characters (% and _)
    in the query are escaped so they're matched literally, not as wildcards.

    Args:
        query: Search text to match against captions.
        limit: Max number of rows to return.
        offset: Number of matching rows to skip (for pagination).

    Returns:
        List of media_files rows (as dicts) whose caption contains query.
    """
    like_pattern = f"%{_escape_like(query)}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM media_files
            WHERE caption LIKE ? ESCAPE '\\' COLLATE NOCASE
            ORDER BY id
            LIMIT ? OFFSET ?
            """,
            (like_pattern, limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def count_search_results(query: str) -> int:
    """Return the total number of media files whose caption matches query."""
    like_pattern = f"%{_escape_like(query)}%"
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM media_files WHERE caption LIKE ? ESCAPE '\\' COLLATE NOCASE",
            (like_pattern,),
        ).fetchone()
    return row[0]
