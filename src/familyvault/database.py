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

CREATE TABLE IF NOT EXISTS people (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT,
    cover_face_id INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES media_files(id),
    person_id   INTEGER REFERENCES people(id),
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    confidence  REAL NOT NULL,
    embedding   BLOB NOT NULL,
    age         INTEGER,
    gender      TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_faces_file_id
    ON faces(file_id);

CREATE INDEX IF NOT EXISTS idx_faces_person_id
    ON faces(person_id);

CREATE INDEX IF NOT EXISTS idx_faces_person_confidence
    ON faces(person_id, confidence DESC);
"""

# Columns that must exist on media_files. Used by _migrate() to bring older
# databases (created before a given column existed) up to date without
# touching any existing rows.
REQUIRED_MEDIA_FILES_COLUMNS = {
    "caption": "TEXT",
    "date_taken": "TEXT",
    "date_source": "TEXT",
    "camera_make": "TEXT",
    "camera_model": "TEXT",
    "gps_lat": "REAL",
    "gps_lon": "REAL",
    "width": "INTEGER",
    "height": "INTEGER",
    "codec": "TEXT",
    "frame_rate": "REAL",
    "duration_seconds": "REAL",
    "city": "TEXT",
    "state": "TEXT",
    "country": "TEXT",
    "skip_reason": "TEXT",
    "faces_checked_at": "TEXT",
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

    For each file, extracts full metadata via metadata.py — date_taken
    (EXIF for images, falling back to file-modified-time), camera make/
    model and GPS for images, and width/height/codec/frame_rate/duration
    for videos.

    Args:
        result: Completed scan to store.

    Returns:
        The scan ID assigned by the database.
    """
    from datetime import datetime as dt
    from familyvault.metadata import extract_metadata

    scanned_at = datetime.now(timezone.utc).isoformat()

    rows = []
    for f in result.media_files:
        date_taken = None
        date_source = None
        camera_make = None
        camera_model = None
        gps_lat = None
        gps_lon = None
        width = None
        height = None
        codec = None
        frame_rate = None
        duration_seconds = None

        try:
            meta = extract_metadata(f.path)
            if meta is not None:
                width = meta.width
                height = meta.height
                codec = meta.codec
                frame_rate = meta.frame_rate
                duration_seconds = meta.duration_seconds
                camera_make = meta.camera_make
                camera_model = meta.camera_model
                gps_lat = meta.gps_lat
                gps_lon = meta.gps_lon
                if meta.has_datetime:
                    date_taken = meta.taken_at
                    date_source = "exif"
        except Exception as e:
            log.warning(f"Metadata extraction failed for {f.path.name}: {e}")

        if date_taken is None:
            try:
                mtime = f.path.stat().st_mtime
                date_taken = dt.fromtimestamp(mtime).isoformat()
                date_source = "file_modified"
            except OSError:
                date_taken = None
                date_source = None

        rows.append((
            str(f.path),
            f.extension,
            f.size_bytes,
            int(f.is_image),
            int(f.is_video),
            date_taken,
            date_source,
            camera_make,
            camera_model,
            gps_lat,
            gps_lon,
            width,
            height,
            codec,
            frame_rate,
            duration_seconds,
        ))

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
                (scan_id, path, extension, size_bytes, is_image, is_video,
                 date_taken, date_source, camera_make, camera_model,
                 gps_lat, gps_lon, width, height, codec, frame_rate,
                 duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (scan_id, *row)
                for row in rows
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


def save_date_taken(file_id: int, date_taken: str | None, date_source: str | None) -> None:
    """
    Store the taken date (and its source) for a single media file.

    Args:
        file_id: The media_files.id to update.
        date_taken: ISO 8601 date string, or None if no date could be determined.
        date_source: One of "exif", "video", "file_modified", or None.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE media_files SET date_taken = ?, date_source = ? WHERE id = ?",
            (date_taken, date_source, file_id),
        )
    log.debug(f"Saved date_taken for file #{file_id}")


def save_extended_metadata(file_id: int, meta) -> None:
    """
    Store camera/GPS (images) and technical (video) metadata for a
    single media file, extracted via metadata.extract_metadata().

    Args:
        file_id: The media_files.id to update.
        meta: A MediaMetadata instance (or None — all fields saved as NULL).
    """
    with _connect() as conn:
        conn.execute(
            """
            UPDATE media_files
            SET camera_make = ?, camera_model = ?, gps_lat = ?, gps_lon = ?,
                width = ?, height = ?, codec = ?, frame_rate = ?, duration_seconds = ?
            WHERE id = ?
            """,
            (
                meta.camera_make if meta else None,
                meta.camera_model if meta else None,
                meta.gps_lat if meta else None,
                meta.gps_lon if meta else None,
                meta.width if meta else None,
                meta.height if meta else None,
                meta.codec if meta else None,
                meta.frame_rate if meta else None,
                meta.duration_seconds if meta else None,
                file_id,
            ),
        )
    log.debug(f"Saved extended metadata for file #{file_id}")


def save_location(file_id: int, city: str | None, state: str | None, country: str | None) -> None:
    """
    Store the resolved city/state/country for a single media file,
    produced by location.resolve_location() from the file's GPS
    coordinates.

    Args:
        file_id: The media_files.id to update.
        city: Nearest resolved place name, or None if unresolved.
        state: Resolved state/admin-1 region, or None.
        country: Resolved country display name, or None.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE media_files SET city = ?, state = ?, country = ? WHERE id = ?",
            (city, state, country, file_id),
        )
    log.debug(f"Saved location for file #{file_id}")


def update_file_path(file_id: int, new_path: str) -> None:
    """
    Update a single file's stored path — used by the reconcile command
    when a file is detected to have moved to a different location under
    the same watched root (matched by filename + size at a new path).
    Deliberately only touches `path`; every other column (caption,
    date_taken, camera/GPS/location fields) is left exactly as-is, since
    a move doesn't change any of that — it's the same file.

    Args:
        file_id: The media_files.id to update.
        new_path: The file's new location on disk.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE media_files SET path = ? WHERE id = ?",
            (new_path, file_id),
        )
    log.debug(f"Updated path for file #{file_id} -> {new_path}")


def save_faces(file_id: int, faces: list) -> None:
    """
    Store every detected face for a single media file, and mark the
    file as checked (faces_checked_at) so it isn't reprocessed by
    future `familyvault faces` runs. Called with an empty list for a
    file with zero detected faces — that's a valid, successful result,
    distinct from "not yet processed" (see get_files_needing_faces()).

    Args:
        file_id: The media_files.id these faces belong to.
        faces: List of faces.FaceDetection instances (possibly empty).
    """
    now = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO faces
                (file_id, x, y, width, height, confidence, embedding, age, gender, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (file_id, f.x, f.y, f.width, f.height, f.confidence, f.embedding, f.age, f.gender, now)
                for f in faces
            ],
        )
        conn.execute(
            "UPDATE media_files SET faces_checked_at = ? WHERE id = ?",
            (now, file_id),
        )
    log.debug(f"Saved {len(faces)} face(s) for file #{file_id}")


def create_person(name: str | None = None) -> int:
    """
    Create a new person record, optionally with a name. Called with
    name=None for a brand-new cluster from cluster-faces — the person
    stays "Unknown Person #<id>" (computed at display time, not
    stored) until someone names them.

    Args:
        name: The person's name, or None to leave unnamed.

    Returns:
        The new person's id.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO people (name, cover_face_id, created_at) VALUES (?, NULL, ?)",
            (name, now),
        )
        person_id = cursor.lastrowid
    log.debug(f"Created person #{person_id}" + (f" ({name})" if name else " (unnamed)"))
    return person_id


def assign_faces_to_person(face_ids: list[int], person_id: int) -> None:
    """
    Assign a batch of faces to a person in one statement.

    Args:
        face_ids: The faces.id values to update.
        person_id: The people.id they belong to.
    """
    if not face_ids:
        return
    placeholders = ",".join("?" * len(face_ids))
    with _connect() as conn:
        conn.execute(
            f"UPDATE faces SET person_id = ? WHERE id IN ({placeholders})",
            (person_id, *face_ids),
        )
    log.debug(f"Assigned {len(face_ids)} face(s) to person #{person_id}")


def mark_file_skipped(file_id: int, reason: str) -> None:
    """
    Mark a single file as permanently skipped, with a human-readable
    reason. Skipped files are excluded from every future batch pass —
    captioning and all three backfill commands — so a file that's
    genuinely broken (e.g. corrupt beyond repair) stops being retried
    forever. This is deliberately a manual, explicit action (see the
    skip-file CLI command) rather than something the app decides on its
    own after N failures — a failure isn't proof a file is unfixable,
    just that it hasn't been fixed yet.

    Args:
        file_id: The media_files.id to mark.
        reason: Why this file is being skipped, for future review
            (e.g. "corrupt: moov atom not found — ffmpeg cannot read this file").
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE media_files SET skip_reason = ? WHERE id = ?",
            (reason, file_id),
        )
    log.info(f"Marked file #{file_id} as skipped: {reason}")


def unmark_file_skipped(file_id: int) -> None:
    """
    Clear a file's skip_reason, returning it to normal processing —
    e.g. after a fix makes something that used to fail now work, or
    after correcting a file that was skipped by mistake.

    Args:
        file_id: The media_files.id to un-skip.
    """
    with _connect() as conn:
        conn.execute(
            "UPDATE media_files SET skip_reason = NULL WHERE id = ?",
            (file_id,),
        )
    log.info(f"Un-skipped file #{file_id}")


def get_file_by_path(path: str) -> dict | None:
    """
    Look up a single media file by its exact stored path — used by the
    skip-file/unskip-file CLI commands, which take a path (copy-pasted
    from a log line) rather than a database ID.

    Args:
        path: The exact path string as stored in media_files.path.

    Returns:
        The file record as a dict, or None if no file has that path.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM media_files WHERE path = ?",
            (path,),
        ).fetchone()
    return dict(row) if row else None


def get_skipped_files() -> list[dict]:
    """Return every file currently marked as skipped, most recently skipped first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM media_files WHERE skip_reason IS NOT NULL ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


# ── Delete ─────────────────────────────────────────────────────────────────────

def delete_file_record(file_id: int) -> None:
    """
    Delete a single media file's row from the database.

    Does not touch the file on disk or its thumbnail — callers are
    responsible for handling those separately (see the
    delete-duplicates CLI command).

    Args:
        file_id: The media_files.id to remove.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM media_files WHERE id = ?", (file_id,))
    log.debug(f"Deleted database record for file #{file_id}")


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


def get_file_by_id(file_id: int) -> dict | None:
    """
    Return a single media file by its database ID.

    Args:
        file_id: The media_files.id to look up.

    Returns:
        The file record as a dict, or None if no file has that ID.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM media_files WHERE id = ?",
            (file_id,),
        ).fetchone()
    return dict(row) if row else None


def get_all_files() -> list[dict]:
    """
    Return every media file across all scans, ordered by id.

    Used by duplicate detection, which needs to scan the full library
    rather than a single scan's files.

    Returns:
        List of all media_files rows (as dicts).
    """
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM media_files ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_files_under_root(root: str) -> list[dict]:
    """
    Return every media file whose stored path is under the given root
    directory. Used by the reconcile command to scope its comparison to
    just the watched folder, leaving records from any other
    previously-scanned location untouched.

    Uses a LIKE prefix match rather than a Python-side filter, since
    scanning the whole media_files table into memory just to filter by
    prefix would be wasteful for a large library. Paths are always
    stored as fully-resolved absolute paths (scan() resolves them
    before saving), so a simple prefix match is reliable here.

    Args:
        root: Absolute path to the watched root directory.

    Returns:
        List of media_files rows (as dicts) whose path falls under root.
    """
    prefix = root if root.endswith("/") else root + "/"
    like_pattern = _escape_like(prefix) + "%"
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM media_files WHERE path LIKE ? ESCAPE '\\'",
            (like_pattern,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_files_needing_captions(limit: int | None = None) -> list[dict]:
    """
    Return image files that don't have a caption yet.

    Only returns images (is_image = 1) since this predates video
    captioning support. See get_media_needing_captions() for images and
    videos together. Excludes files marked skipped via mark_file_skipped()
    (see skip-file CLI command). Ordered by id so batches are processed
    in a stable order.

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) missing a caption.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE is_image = 1 AND caption IS NULL AND skip_reason IS NULL "
        "ORDER BY id"
    )
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
    types (videos via an extracted representative frame). Excludes
    files marked skipped via mark_file_skipped() (see skip-file CLI
    command). Ordered by id so batches are processed in a stable order.

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) missing a caption.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE (is_image = 1 OR is_video = 1) AND caption IS NULL AND skip_reason IS NULL "
        "ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_files_missing_date(limit: int | None = None) -> list[dict]:
    """
    Return image AND video files that don't have a date_taken yet.

    Used by the backfill-dates CLI command to process existing library
    files in batches. Excludes files marked skipped via
    mark_file_skipped() (see skip-file CLI command). Ordered by id so
    batches are processed in a stable order.

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) missing a date_taken.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE (is_image = 1 OR is_video = 1) AND date_taken IS NULL AND skip_reason IS NULL "
        "ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_files_missing_metadata(limit: int | None = None) -> list[dict]:
    """
    Return image AND video files that haven't had extended metadata
    (camera/GPS for images, technical fields for video) extracted yet.

    Uses `width IS NULL` as the "not yet processed" marker, since
    extract_metadata() returns a width for both images and videos —
    any file that's been through this pass will have it set (even if
    to a real value), while unprocessed files remain NULL. Excludes
    files marked skipped via mark_file_skipped() (see skip-file CLI
    command).

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) missing extended metadata.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE (is_image = 1 OR is_video = 1) AND width IS NULL AND skip_reason IS NULL "
        "ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_files_missing_location(limit: int | None = None) -> list[dict]:
    """
    Return image AND video files that have GPS coordinates but haven't
    been reverse geocoded yet.

    Unlike the other get_files_missing_*() helpers, this is naturally
    scoped to a subset of the library: files with no GPS coordinates at
    all are never returned here, since there's nothing to resolve (per
    the project's GPS coverage note, a majority of files have no GPS —
    older cameras and scanned prints don't embed it). Uses `city IS NULL`
    as the "not yet processed" marker, matching the pattern used by
    get_files_missing_metadata() for `width IS NULL`. Excludes files
    marked skipped via mark_file_skipped() (see skip-file CLI command).

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) with GPS but no city yet.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL AND city IS NULL AND skip_reason IS NULL "
        "ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_files_needing_faces(limit: int | None = None) -> list[dict]:
    """
    Return image files that haven't been run through face detection yet.

    Images only, for now — video face recognition isn't implemented.
    Uses faces_checked_at IS NULL as the "not yet processed" marker,
    distinct from "processed, zero faces found" (which sets
    faces_checked_at but leaves the file with no rows in the faces
    table) — same reasoning as get_files_missing_metadata()'s
    width IS NULL check. Excludes files marked skipped via
    mark_file_skipped().

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of media_files rows (as dicts) not yet checked for faces.
    """
    query = (
        "SELECT * FROM media_files "
        "WHERE is_image = 1 AND faces_checked_at IS NULL AND skip_reason IS NULL "
        "ORDER BY id"
    )
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_faces_needing_clustering(limit: int | None = None) -> list[dict]:
    """
    Return faces that haven't been assigned to a person yet
    (person_id IS NULL). Used by the cluster-faces CLI command to
    process new detections in batches — already-clustered faces are
    never touched, which is what makes re-running cluster-faces safe:
    previously-named people keep their name and their existing photos.

    Args:
        limit: Optional max number of rows to return (for batch processing).

    Returns:
        List of faces rows (as dicts), including the raw embedding bytes.
    """
    query = "SELECT * FROM faces WHERE person_id IS NULL ORDER BY id"
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_people_with_faces() -> list[dict]:
    """
    Return every person along with the raw embeddings of every face
    currently assigned to them. Used by the cluster-faces CLI command
    to compute each person's current mean embedding, for matching new
    faces against. Not intended for display — a lighter-weight summary
    for the API/frontend will be added alongside the People UI.

    Returns:
        List of dicts: {"id": ..., "name": ..., "embeddings": [bytes, ...]}
    """
    with _connect() as conn:
        people_rows = conn.execute("SELECT id, name FROM people ORDER BY id").fetchall()
        result = []
        for p in people_rows:
            face_rows = conn.execute(
                "SELECT embedding FROM faces WHERE person_id = ?", (p["id"],)
            ).fetchall()
            result.append({
                "id": p["id"],
                "name": p["name"],
                "embeddings": [row["embedding"] for row in face_rows],
            })
    return result

def get_person(person_id: int) -> dict | None:
    """
    Return a single person record by id, or None if it doesn't exist.

    Args:
        person_id: The people.id to look up.

    Returns:
        The person record as a dict, or None.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
    return dict(row) if row else None

def count_people() -> int:
    """Return the total number of person records in the library — used alongside get_people_with_counts() for pagination."""
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM people").fetchone()
    return row[0]


def get_people_with_counts(limit: int | None = 100, offset: int = 0) -> list[dict]:
    """
    Return people with their face count and the face to use as a cover
    thumbnail — an explicitly set cover_face_id if present, otherwise
    their highest-confidence face. Largest face count first.

    limit=None returns every person with no pagination at all — used
    by the merge picker, which needs the complete roster for its
    search box to find any cluster, including small fragments sorted
    toward the bottom by face_count DESC (exactly the ones most worth
    merging). A numeric limit is used by the People grid instead,
    which paginates: a library that's been through a large
    cluster-faces run can easily have tens of thousands of person
    records, mostly small fragments from over-fragmentation — loading
    (and fetching a cover image for) every single one at once was slow
    for no benefit, since only a page's worth is ever on screen. See
    count_people() for the matching total.

    Args:
        limit: Max number of people to return, or None for everyone.
        offset: Number of matching people to skip (ignored if limit is None).

    Returns:
        List of dicts: {"id", "name", "face_count", "cover_face_id"}
        (cover_face_id may be None for a person with zero faces).
    """
    query = """
        SELECT
            p.id,
            p.name,
            COUNT(f.id) as face_count,
            COALESCE(
                p.cover_face_id,
                (SELECT f2.id FROM faces f2 WHERE f2.person_id = p.id
                 ORDER BY f2.confidence DESC LIMIT 1)
            ) as cover_face_id
        FROM people p
        LEFT JOIN faces f ON f.person_id = p.id
        GROUP BY p.id
        ORDER BY face_count DESC
    """
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params = (limit, offset)

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_person_cover_face(person_id: int) -> dict | None:
    """
    Return the face record to use as a person's cover thumbnail —
    their explicitly set cover_face_id if present, otherwise their
    highest-confidence face — along with its source file's path. Used
    by the /people/{id}/cover API endpoint to generate the crop.

    Returns:
        Dict with the face's columns plus "path", or None if the
        person doesn't exist or has no faces at all.
    """
    with _connect() as conn:
        person_row = conn.execute(
            "SELECT cover_face_id FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        if person_row is None:
            return None

        if person_row["cover_face_id"] is not None:
            face_id = person_row["cover_face_id"]
        else:
            best = conn.execute(
                "SELECT id FROM faces WHERE person_id = ? ORDER BY confidence DESC LIMIT 1",
                (person_id,),
            ).fetchone()
            if best is None:
                return None
            face_id = best["id"]

        row = conn.execute(
            """
            SELECT f.*, m.path
            FROM faces f JOIN media_files m ON m.id = f.file_id
            WHERE f.id = ?
            """,
            (face_id,),
        ).fetchone()
    return dict(row) if row else None


def get_people_for_file(file_id: int) -> list[dict]:
    """
    Return every clustered person detected in a single media file — the
    reverse of get_files_for_person(). Powers the lightbox's "who's in
    this photo" panel: for each face detected in this exact file,
    returns its face id (so the caller can generate a crop from *this*
    photo specifically — see get_face_by_id()) alongside its person's
    id and name.

    Faces with no person_id yet (not yet run through cluster-faces) are
    excluded — there's no person record or name to show for them yet.
    A file can have more than one row here if it has more than one
    detected+clustered face, which is expected and fine (a group photo).

    Args:
        file_id: The media_files.id to look up faces/people for.

    Returns:
        List of dicts: {"face_id", "person_id", "name", "display_name"},
        one per detected and clustered face, ordered by face id.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.id as face_id, f.person_id, p.name
            FROM faces f
            JOIN people p ON p.id = f.person_id
            WHERE f.file_id = ? AND f.person_id IS NOT NULL
            ORDER BY f.id
            """,
            (file_id,),
        ).fetchall()
    return [
        {
            "face_id": row["face_id"],
            "person_id": row["person_id"],
            "name": row["name"],
            "display_name": row["name"] or f"Unknown Person #{row['person_id']}",
        }
        for row in rows
    ]


def get_face_by_id(face_id: int) -> dict | None:
    """
    Return a single face record by id, joined with its source file's
    path — used by the per-face thumbnail endpoint to crop the exact
    face region from the exact photo it was detected in. Distinct from
    get_person_cover_face(), which picks a person's single best face
    from anywhere in the library — that's the wrong source for the
    lightbox, where the crop needs to match whatever photo is currently
    on screen (a person's general cover photo could be a different,
    more recent picture entirely).

    Args:
        face_id: The faces.id to look up.

    Returns:
        Dict with the face's columns plus "path", or None if no face
        has that id.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT f.*, m.path
            FROM faces f JOIN media_files m ON m.id = f.file_id
            WHERE f.id = ?
            """,
            (face_id,),
        ).fetchone()
    return dict(row) if row else None


def get_files_for_person(
    person_id: int,
    limit: int = 100,
    offset: int = 0,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """
    Return every media file containing at least one face assigned to
    this person, newest date_taken first — powers the person detail
    view. DISTINCT so a file with multiple faces belonging to the same
    person (e.g. two crops from a burst) only appears once.

    Optionally scoped to a date range via date_from/date_to (see
    _build_date_range_clause()) — either bound can be omitted for an
    open-ended range.

    Args:
        person_id: The people.id to look up files for.
        limit: Max number of rows to return.
        offset: Number of matching rows to skip (for pagination).
        date_from: ISO date string (YYYY-MM-DD), inclusive lower bound, or None.
        date_to: ISO date string (YYYY-MM-DD), inclusive upper bound, or None.

    Returns:
        List of media_files rows (as dicts).
    """
    date_clause, date_params = _build_date_range_clause(date_from, date_to)
    extra_where = f" AND ({date_clause})" if date_clause else ""

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT m.*
            FROM media_files m
            JOIN faces f ON f.file_id = m.id
            WHERE f.person_id = ?{extra_where}
            ORDER BY (m.date_taken IS NULL), m.date_taken DESC, m.id DESC
            LIMIT ? OFFSET ?
            """,
            (person_id, *date_params, limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def count_files_for_person(person_id: int, date_from: str | None = None, date_to: str | None = None) -> int:
    """
    Return the total number of distinct media files containing a face
    assigned to this person, optionally scoped to a date range (see
    get_files_for_person()).
    """
    date_clause, date_params = _build_date_range_clause(date_from, date_to)

    with _connect() as conn:
        if date_clause:
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT f.file_id)
                FROM faces f
                JOIN media_files m ON m.id = f.file_id
                WHERE f.person_id = ? AND ({date_clause})
                """,
                (person_id, *date_params),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(DISTINCT f.file_id) FROM faces f WHERE f.person_id = ?",
                (person_id,),
            ).fetchone()
    return row[0]

def count_faces_for_person(person_id: int) -> int:
    """Return how many faces are currently assigned to a person."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM faces WHERE person_id = ?", (person_id,)
        ).fetchone()
    return row[0]


def set_person_name(person_id: int, name: str) -> None:
    """
    Set or update a person's name.

    Args:
        person_id: The people.id to update.
        name: The name to set.
    """
    with _connect() as conn:
        conn.execute("UPDATE people SET name = ? WHERE id = ?", (name, person_id))
    log.debug(f"Named person #{person_id}: {name}")


def merge_people(keeper_id: int, loser_ids: list[int]) -> int:
    """
    Merge one or more people into a single keeper person. Every face
    currently assigned to any loser_id is reassigned to keeper_id, and
    the loser person records are deleted. The keeper's own name (if
    any) is left untouched — use set_person_name() separately if the
    merged result should be (re)named.

    This exists for cases embedding similarity can't be expected to
    bridge on its own — most notably the same person at very different
    ages (baby vs child vs adult), where the underlying face structure
    has changed too much for any similarity threshold to safely merge
    without also risking merging different people elsewhere. Merging
    is always a deliberate, explicit action — cluster-faces never does
    this automatically.

    Args:
        keeper_id: The person id to keep. Every face ends up here.
        loser_ids: Person ids to merge into keeper_id and delete.
            keeper_id is ignored if it also appears in this list.

    Returns:
        The number of faces reassigned.
    """
    loser_ids = [pid for pid in loser_ids if pid != keeper_id]
    if not loser_ids:
        return 0

    placeholders = ",".join("?" * len(loser_ids))
    with _connect() as conn:
        cursor = conn.execute(
            f"UPDATE faces SET person_id = ? WHERE person_id IN ({placeholders})",
            (keeper_id, *loser_ids),
        )
        reassigned = cursor.rowcount
        conn.execute(f"DELETE FROM people WHERE id IN ({placeholders})", loser_ids)
    log.info(f"Merged {len(loser_ids)} people into person #{keeper_id} — {reassigned} face(s) reassigned")
    return reassigned

def reset_face_clustering() -> int:
    """
    Clear all person assignments and delete every person record, so
    cluster-faces can be re-run from scratch with a different
    match_threshold. Face detections and their embeddings are never
    touched — only the person_id link and the people table.

    Returns:
        The number of people records deleted.
    """
    with _connect() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM people")
        count = cursor.fetchone()[0]
        conn.execute("UPDATE faces SET person_id = NULL")
        conn.execute("DELETE FROM people")
    log.info(f"Reset face clustering — cleared {count} people, all faces unassigned")
    return count


def reset_face_clustering_unnamed_only() -> int:
    """
    Clear person assignments and delete person records, but ONLY for
    unnamed people (name IS NULL) — named people and every face
    already assigned to one are left completely untouched. Lets
    cluster-faces be re-run with a different match_threshold to reduce
    fragmentation among "Unknown Person #N" clusters specifically,
    without discarding any naming (or merging) work already done.

    Unlike reset_face_clustering() (all-or-nothing), this is safe to
    run more than once while trying different threshold values — named
    people are never at risk either way.

    Returns:
        The number of unnamed people records deleted.
    """
    with _connect() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM people WHERE name IS NULL")
        count = cursor.fetchone()[0]
        conn.execute(
            "UPDATE faces SET person_id = NULL "
            "WHERE person_id IN (SELECT id FROM people WHERE name IS NULL)"
        )
        conn.execute("DELETE FROM people WHERE name IS NULL")
    log.info(f"Reset face clustering (unnamed only) — cleared {count} unnamed people, their faces unassigned; named people untouched")
    return count


def discard_person(person_id: int) -> int:
    """
    Permanently delete every face detection (and its embedding)
    currently assigned to this person, then delete the person record
    itself.

    Unlike merge_people() (reassigns faces to another person) or
    reset_face_clustering()/reset_face_clustering_unnamed_only() (only
    unassign, leaving faces to be reconsidered by a future
    cluster-faces run), this permanently removes the face rows. Meant
    for a cluster that clustering has repeatedly formed incorrectly —
    most notably a pile of unrelated people's low-quality detections
    (e.g. side-profile faces, whose embeddings are too indistinct to
    be a reliable identity signal) that embedded similarly to each
    other despite not being the same person at all, and would just
    re-form as a similar junk cluster on any future re-cluster if only
    unassigned rather than deleted outright.

    The photos themselves (media_files) are never touched — this only
    ever removes derived face-detection rows, never anything about the
    actual image/video file.

    This function performs the deletion unconditionally for whatever
    person_id it's given — it does not itself check whether the person
    is named. See cmd_discard_person's "refuse to touch a named
    person" rule, which is enforced at the CLI layer before this is
    ever called, consistent with how merge_people()/cmd_merge_people
    divide the same kind of responsibility.

    Args:
        person_id: The people.id to discard.

    Returns:
        The number of face rows permanently deleted.
    """
    with _connect() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM faces WHERE person_id = ?", (person_id,))
        count = cursor.fetchone()[0]
        conn.execute("DELETE FROM faces WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
    log.info(f"Discarded person #{person_id} — {count} face(s) permanently deleted")
    return count


def get_faces_grouped_by_person(person_limit: int | None = None) -> list[dict]:
    """
    Return clustered people (largest groups first) along with each
    face's bounding box and source file path — used by
    export-face-previews to generate visual samples for threshold
    tuning, not by normal clustering logic.

    Args:
        person_limit: Optional max number of people to return, largest
            group first.

    Returns:
        List of dicts: {"id": person_id, "faces": [{"id", "x", "y",
        "width", "height", "path"}, ...]}
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT f.id as face_id, f.person_id, f.x, f.y, f.width, f.height, m.path
            FROM faces f
            JOIN media_files m ON m.id = f.file_id
            WHERE f.person_id IS NOT NULL
            ORDER BY f.person_id, f.id
            """
        ).fetchall()

    by_person: dict[int, list[dict]] = {}
    for row in rows:
        by_person.setdefault(row["person_id"], []).append({
            "id": row["face_id"],
            "x": row["x"],
            "y": row["y"],
            "width": row["width"],
            "height": row["height"],
            "path": row["path"],
        })

    people = [{"id": pid, "faces": faces} for pid, faces in by_person.items()]
    people.sort(key=lambda p: len(p["faces"]), reverse=True)

    if person_limit is not None:
        people = people[:person_limit]
    return people

def get_named_people() -> list[dict]:
    """
    Return every person who has actually been given a name (name IS
    NOT NULL), for person-name search — both as the vocabulary passed
    into query_parser.parse_query() and to resolve a recognized name
    back to a person id in _build_person_clause(). Unnamed "Unknown
    Person #N" clusters are deliberately excluded — there's no name
    text to search for.

    Returns:
        List of dicts: {"id", "name"}.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name FROM people WHERE name IS NOT NULL ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]

def get_named_people_for_files(file_ids: list[int]) -> dict[int, list[str]]:
    """
    Return the named people appearing in each of a batch of files, as a
    single batched query — used by the /search endpoint to attach a
    "people" tag to every result in one query rather than one extra
    request per file (which would mean 50+ additional round trips for a
    single page of results). Only named people are included, matching
    the same "named only" rule used elsewhere (get_named_people(),
    person-name search) — an unnamed "Unknown Person #N" isn't
    meaningful as a browsing tag.

    Args:
        file_ids: The media_files.id values to look up.

    Returns:
        Dict mapping file_id -> list of person names (alphabetical). A
        file_id with no named people at all is simply absent from the
        dict rather than mapped to an empty list — callers should use
        .get(file_id, []) at the call site.
    """
    if not file_ids:
        return {}

    placeholders = ",".join("?" * len(file_ids))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT f.file_id, p.name
            FROM faces f
            JOIN people p ON p.id = f.person_id
            WHERE f.file_id IN ({placeholders}) AND p.name IS NOT NULL
            ORDER BY f.file_id, p.name COLLATE NOCASE
            """,
            file_ids,
        ).fetchall()

    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(row["file_id"], []).append(row["name"])
    return result


def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcards (% and _) so search text is matched literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Meteorological seasons by hemisphere. Southern Hemisphere seasons are
# the Northern set shifted by 6 months (winter <-> summer, spring <-> fall).
_SEASON_MONTHS_NORTH = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "fall": (9, 10, 11),
}
_SEASON_MONTHS_SOUTH = {
    "winter": (6, 7, 8),
    "spring": (9, 10, 11),
    "summer": (12, 1, 2),
    "fall": (3, 4, 5),
}


def _build_date_range_clause(date_from: str | None, date_to: str | None) -> tuple[str, list]:
    """
    Build a SQL WHERE fragment (and its bound params) for an explicit
    date range — distinct from _build_date_clause()'s year/month/
    season parsing, this takes two plain ISO date strings directly
    (e.g. from an <input type="date"> picker) for a precise, arbitrary
    range rather than a whole year/month/season bucket. Either bound
    can be omitted for an open-ended range. Shared by search_media()
    (Library) and get_files_for_person()/count_files_for_person()
    (a person's photo grid) — the same range filter, just applied
    against a different base query in each case.

    date_to's comparison uses SQLite's date() function to compute the
    day after date_to, then compares with '<' — rather than comparing
    the plain date_to string directly — so a photo timestamped any
    time during date_to itself (not just midnight) is still included.
    date_taken is always stored as a full ISO 8601 datetime string
    (see save_scan()/save_date_taken()), never a bare date, so the
    naive string comparison for the lower bound (date_taken >= ?)
    already works correctly without similar handling: any timestamp
    on or after date_from's midnight sorts after date_from lexically.

    Args:
        date_from: ISO date string (YYYY-MM-DD), inclusive lower bound, or None.
        date_to: ISO date string (YYYY-MM-DD), inclusive upper bound, or None.

    Returns:
        (sql_fragment, params) — sql_fragment is "" if both are None,
        in which case params is also empty.
    """
    clauses = []
    params: list = []

    if date_from:
        clauses.append("date_taken >= ?")
        params.append(date_from)

    if date_to:
        clauses.append("date_taken < date(?, '+1 day')")
        params.append(date_to)

    if not clauses:
        return "", []

    return "date_taken IS NOT NULL AND " + " AND ".join(clauses), params


def _build_date_clause(parsed) -> tuple[str, list]:
    """
    Build a SQL WHERE fragment (and its bound params) for the date
    portion of a parsed search query — year, explicit month, and/or
    season. Returns ("", []) if the query has no date filter at all.

    Season is resolved per-file based on hemisphere, inferred from the
    sign of gps_lat (negative = Southern Hemisphere). Files with no GPS
    default to Northern Hemisphere — a stated assumption, not a fact —
    since that's assumed to cover the majority of an unlabeled library
    (per the GPS coverage note in the project context); worth revisiting
    if it turns out wrong for a meaningful chunk of files.

    If both an explicit month and a season are present on the parsed
    query, the explicit month wins (it's more precise) and season is
    ignored for filtering purposes — see query_parser.parse_query().

    Args:
        parsed: An object with .year, .month, .season attributes (see
            query_parser.ParsedQuery).

    Returns:
        (sql_fragment, params) — sql_fragment is "" if there's no date
        filter at all, in which case params is also empty.
    """
    clauses = []
    params: list = []

    if parsed.year is not None:
        clauses.append("CAST(strftime('%Y', date_taken) AS INTEGER) = ?")
        params.append(parsed.year)

    if parsed.month is not None:
        clauses.append("CAST(strftime('%m', date_taken) AS INTEGER) = ?")
        params.append(parsed.month)
    elif parsed.season is not None:
        north_months = _SEASON_MONTHS_NORTH[parsed.season]
        south_months = _SEASON_MONTHS_SOUTH[parsed.season]
        north_placeholders = ",".join("?" * len(north_months))
        south_placeholders = ",".join("?" * len(south_months))
        clauses.append(
            "("
            f"((gps_lat IS NULL OR gps_lat >= 0) AND CAST(strftime('%m', date_taken) AS INTEGER) IN ({north_placeholders}))"
            " OR "
            f"(gps_lat < 0 AND CAST(strftime('%m', date_taken) AS INTEGER) IN ({south_placeholders}))"
            ")"
        )
        params.extend(north_months)
        params.extend(south_months)

    if not clauses:
        return "", []

    return "date_taken IS NOT NULL AND " + " AND ".join(clauses), params


def _build_text_clause(text: str) -> tuple[str, list]:
    """
    Build a SQL WHERE fragment (and its bound params) matching text
    against caption, city, state, or country. Returns ("", []) if text
    is blank, so callers can skip this clause entirely rather than
    matching against an empty pattern.
    """
    stripped = text.strip()
    if not stripped:
        return "", []

    like_pattern = f"%{_escape_like(stripped)}%"
    clause = (
        "("
        "caption LIKE ? ESCAPE '\\' COLLATE NOCASE "
        "OR city LIKE ? ESCAPE '\\' COLLATE NOCASE "
        "OR state LIKE ? ESCAPE '\\' COLLATE NOCASE "
        "OR country LIKE ? ESCAPE '\\' COLLATE NOCASE"
        ")"
    )
    return clause, [like_pattern, like_pattern, like_pattern, like_pattern]


# Bucket boundaries for the video sub-filters, mirroring resolutionTier()/
# lengthCategory() in App.jsx exactly so a "1080p · Short clip" tag on a
# result matches whichever filter buttons would have included it. Each
# value is (min_inclusive, max_exclusive) in the file's native units
# (width in pixels, duration in seconds); max=None means unbounded above.
_RESOLUTION_TIER_RANGES = {
    "4k": (3840, None),
    "1080p": (1920, 3840),
    "720p": (1280, 1920),
    "sd": (0, 1280),
}

_LENGTH_CATEGORY_RANGES = {
    "live_photo": (0, 4),
    "short_clip": (4, 30),
    "clip": (30, 120),
    "long_video": (120, None),
}


def _range_clause(column: str, lo: int | float, hi: int | float | None) -> tuple[str, list]:
    """Build a single `col >= ?` or `col >= ? AND col < ?` clause."""
    if hi is None:
        return f"{column} >= ?", [lo]
    return f"{column} >= ? AND {column} < ?", [lo, hi]


def _build_video_filter_clause(
    video_lengths: list[str] | None,
    video_resolutions: list[str] | None,
) -> tuple[str | None, list]:
    """
    Build the WHERE fragment for the video sub-filters. Values within one
    facet (e.g. two resolution tiers) are OR'd together; the two facets
    are AND'd together, so "1080p,4k" + "short_clip" means
    (1080p OR 4K) AND short clip. Unknown keys are silently ignored
    rather than raising, since these come straight off the URL.
    Returns (None, []) if neither facet has any (valid) values.
    """
    clauses = []
    params: list = []

    if video_resolutions:
        sub, sub_params = [], []
        for key in video_resolutions:
            if key not in _RESOLUTION_TIER_RANGES:
                continue
            lo, hi = _RESOLUTION_TIER_RANGES[key]
            clause, p = _range_clause("width", lo, hi)
            sub.append(clause)
            sub_params.extend(p)
        if sub:
            clauses.append("width IS NOT NULL AND (" + " OR ".join(sub) + ")")
            params.extend(sub_params)

    if video_lengths:
        sub, sub_params = [], []
        for key in video_lengths:
            if key not in _LENGTH_CATEGORY_RANGES:
                continue
            lo, hi = _LENGTH_CATEGORY_RANGES[key]
            clause, p = _range_clause("duration_seconds", lo, hi)
            sub.append(clause)
            sub_params.extend(p)
        if sub:
            clauses.append("duration_seconds IS NOT NULL AND (" + " OR ".join(sub) + ")")
            params.extend(sub_params)

    if not clauses:
        return None, []
    return " AND ".join(clauses), params


def _build_person_clause(
    person_names: list[str] | None,
    excluded_person_names: list[str] | None,
) -> tuple[str | None, list]:
    """
    Build the WHERE fragment for person-name search. Every name in
    person_names is required (AND, not OR) — "Patrick and Tamika"
    means both people must have a face in the same file — and every
    name in excluded_person_names must NOT have a face in the file
    ("Patrick NOT Owen"). Names are resolved to person ids by looking
    up the current named-people roster (case-insensitive); a name that
    doesn't match anyone currently named is silently skipped rather
    than raising, since query_parser.parse_query() only recognized it
    in the first place because it was in that same roster at parse
    time — a mismatch here would mean the roster changed between the
    two calls, not a real error worth surfacing.

    Uses one EXISTS/NOT EXISTS subquery against faces per name rather
    than a single JOIN, so combining an include and an exclude (or
    multiple includes) composes correctly with plain AND rather than
    needing self-joins per name.

    Returns:
        (sql_fragment, params) — sql_fragment is None if there's
        nothing to filter on (both lists empty, or every name failed
        to resolve), in which case params is also empty.
    """
    if not person_names and not excluded_person_names:
        return None, []

    named_people = get_named_people()
    name_to_id = {p["name"].strip().lower(): p["id"] for p in named_people}

    clauses = []
    params: list = []

    for name in person_names or []:
        person_id = name_to_id.get(name.strip().lower())
        if person_id is None:
            continue
        clauses.append(
            "EXISTS (SELECT 1 FROM faces f WHERE f.file_id = media_files.id AND f.person_id = ?)"
        )
        params.append(person_id)

    for name in excluded_person_names or []:
        person_id = name_to_id.get(name.strip().lower())
        if person_id is None:
            continue
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM faces f WHERE f.file_id = media_files.id AND f.person_id = ?)"
        )
        params.append(person_id)

    if not clauses:
        return None, []
    return " AND ".join(clauses), params


def _build_search_where(
    parsed,
    media_type: str | None = None,
    video_lengths: list[str] | None = None,
    video_resolutions: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, list]:
    """
    Combine the date clause, text clause, person-name clause, optional
    media-type filter, optional video length/resolution sub-filters,
    and an optional explicit date range into a single WHERE expression
    for search_media()/count_media_search(). A parsed query with
    nothing set at all yields "1=1" — matching everything — which is
    what powers the default "browse everything" gallery view.

    Supplying either video sub-filter forces is_video = 1, even if
    media_type is "image" or unset — a video-only sub-filter with no
    matching media_type would otherwise silently match nothing or leak
    into image results.

    date_from/date_to (see _build_date_range_clause()) are independent
    of, and combine via AND with, the parsed query's own year/month/
    season date clause — a free-text search can still narrow further
    by an explicit picked range, and vice versa.
    """
    where_clauses = []
    params: list = []

    date_clause, date_params = _build_date_clause(parsed)
    if date_clause:
        where_clauses.append(f"({date_clause})")
        params.extend(date_params)

    date_range_clause, date_range_params = _build_date_range_clause(date_from, date_to)
    if date_range_clause:
        where_clauses.append(f"({date_range_clause})")
        params.extend(date_range_params)

    text_clause, text_params = _build_text_clause(parsed.text)
    if text_clause:
        where_clauses.append(text_clause)
        params.extend(text_params)

    person_clause, person_params = _build_person_clause(
        getattr(parsed, "person_names", None), getattr(parsed, "excluded_person_names", None)
    )
    if person_clause:
        where_clauses.append(f"({person_clause})")
        params.extend(person_params)

    has_video_subfilter = bool(video_lengths) or bool(video_resolutions)

    if media_type == "image" and not has_video_subfilter:
        where_clauses.append("is_image = 1")
    elif media_type == "video" or has_video_subfilter:
        where_clauses.append("is_video = 1")

    video_clause, video_params = _build_video_filter_clause(video_lengths, video_resolutions)
    if video_clause:
        where_clauses.append(f"({video_clause})")
        params.extend(video_params)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    return where_sql, params

def search_media(
    parsed,
    media_type: str | None = None,
    video_lengths: list[str] | None = None,
    video_resolutions: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """
    Search media files against a parsed query — combining a date filter
    (year/month/season, season resolved per-file by hemisphere) with a
    free-text match against caption/city/state/country, an optional
    image/video filter, optional video length/resolution sub-filters
    (only meaningful for video), and an optional explicit date range
    (date_from/date_to, e.g. from a date-picker UI — see
    _build_date_range_clause()). Any piece can be absent: a date-only
    query ("summer 2019") returns everything in that range regardless
    of caption, and a completely empty parsed query with no filters
    returns every file, newest first — this is what powers the default
    "everything" gallery view before a search is typed.

    Args:
        parsed: A parsed query object with .text, .year, .month, .season
            attributes (see query_parser.parse_query()).
        media_type: Optional "image" or "video" filter.
        video_lengths: Optional list of length-category keys to include
            (see _LENGTH_CATEGORY_RANGES) — OR'd together.
        video_resolutions: Optional list of resolution-tier keys to
            include (see _RESOLUTION_TIER_RANGES) — OR'd together.
        date_from: ISO date string (YYYY-MM-DD), inclusive lower bound, or None.
        date_to: ISO date string (YYYY-MM-DD), inclusive upper bound, or None.
        limit: Max number of rows to return.
        offset: Number of matching rows to skip (for pagination).

    Returns:
        List of media_files rows (as dicts), newest date_taken first
        (undated files last).
    """
    where_sql, params = _build_search_where(
        parsed, media_type, video_lengths, video_resolutions, date_from, date_to
    )

    query = (
        f"SELECT * FROM media_files WHERE {where_sql} "
        "ORDER BY (date_taken IS NULL), date_taken DESC, id DESC "
        "LIMIT ? OFFSET ?"
    )
    params = params + [limit, offset]

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def count_media_search(
    parsed,
    media_type: str | None = None,
    video_lengths: list[str] | None = None,
    video_resolutions: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Return the total number of media files matching a parsed query (see search_media())."""
    where_sql, params = _build_search_where(
        parsed, media_type, video_lengths, video_resolutions, date_from, date_to
    )
    query = f"SELECT COUNT(*) FROM media_files WHERE {where_sql}"

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
    return row[0]