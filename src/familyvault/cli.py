"""
FamilyVault CLI
Entry point for running FamilyVault from the command line.
Usage: familyvault scan <path>
       familyvault caption --limit <n>
       familyvault backfill-dates --limit <n>
       familyvault backfill-metadata --limit <n>
       familyvault backfill-location --limit <n>
       familyvault faces --limit <n>
       familyvault cluster-faces --limit <n> [--threshold <float>]
       familyvault reset-clustering [--unnamed-only]
       familyvault export-face-previews
       familyvault merge-people <keeper_id> <person_id> [<person_id> ...]
       familyvault discard-person <person_id>
       familyvault name-person <person_id> <name>
       familyvault skip-file <path> [<path> ...] --reason "<text>"
       familyvault unskip-file <path> [<path> ...]
       familyvault list-skipped
       familyvault find-duplicates
       familyvault delete-duplicates <review_file>
       familyvault find-missing
       familyvault delete-missing <review_file>
       familyvault reconcile <path>
"""

import csv
import shutil
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

from familyvault.config import PROJECT_ROOT
from familyvault.logger import get_logger
from familyvault.scanner import scan, ScanResult
from familyvault.database import (
    init_db,
    save_scan,
    get_media_needing_captions,
    save_caption,
    get_files_missing_date,
    save_date_taken,
    get_files_missing_metadata,
    save_extended_metadata,
    get_files_missing_location,
    save_location,
    mark_file_skipped,
    unmark_file_skipped,
    get_file_by_path,
    get_skipped_files,
    get_all_files,
    delete_file_record,
    get_files_under_root,
    update_file_path,
    get_files_needing_faces,
    save_faces,
    get_faces_needing_clustering,
    get_people_with_faces,
    create_person,
    assign_faces_to_person,
    reset_face_clustering,
    reset_face_clustering_unnamed_only,
    discard_person,
    get_faces_grouped_by_person,
    get_person,
    count_faces_for_person,
    set_person_name,
    merge_people,
)
from familyvault.captioner import caption_media
from familyvault.metadata import extract_metadata
from familyvault.location import resolve_location
from familyvault.duplicates import find_exact_duplicates
from familyvault.thumbnailer import thumbnail_path
from familyvault.faces import detect_faces, crop_face
from familyvault.clustering import cluster_faces

log = get_logger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def _format_duration(seconds: float) -> str:
    """Return a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def _print_summary(result, scan_id: int, duration: float) -> None:
    """Print a formatted scan summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Scan Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Scan ID':<20} #{scan_id:<{width - 23}}│")
    print(f"│  {'Root':<20} {str(result.root)[:width - 23]:<{width - 23}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Images':<20} {result.image_count:<{width - 23}}│")
    print(f"│  {'Videos':<20} {result.video_count:<{width - 23}}│")
    print(f"│  {'Total media':<20} {result.total_count:<{width - 23}}│")
    print(f"│  {'Total size':<20} {_format_size(result.total_size_bytes):<{width - 23}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Skipped':<20} {result.skipped_count:<{width - 23}}│")
    print(f"│  {'Errors':<20} {result.error_count:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_caption_summary(captioned: int, failed: int, duration: float, auto_skipped: int = 0) -> None:
    """Print a formatted captioning summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Captioning Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Captioned':<20} {captioned:<{width - 23}}│")
    print(f"│  {'Failed':<20} {failed:<{width - 23}}│")
    if auto_skipped:
        print(f"│  {'Auto-skipped':<20} {auto_skipped:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_date_summary(from_exif: int, from_file: int, failed: int, duration: float) -> None:
    """Print a formatted date-backfill summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Date Backfill Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'From EXIF/metadata':<20} {from_exif:<{width - 23}}│")
    print(f"│  {'From file modified':<20} {from_file:<{width - 23}}│")
    print(f"│  {'Failed':<20} {failed:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_metadata_summary(processed: int, failed: int, duration: float) -> None:
    """Print a formatted metadata-backfill summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Metadata Backfill Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Processed':<20} {processed:<{width - 23}}│")
    print(f"│  {'Failed':<20} {failed:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_location_summary(resolved: int, failed: int, duration: float) -> None:
    """Print a formatted location-backfill summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Location Backfill Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Resolved':<20} {resolved:<{width - 23}}│")
    print(f"│  {'Failed':<20} {failed:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_find_duplicates_summary(groups: int, redundant: int, reclaimable_bytes: int,
                                     output_path: Path, duration: float) -> None:
    """Print a formatted duplicate-detection summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Duplicate Scan Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Groups found':<20} {groups:<{width - 23}}│")
    print(f"│  {'Redundant files':<20} {redundant:<{width - 23}}│")
    print(f"│  {'Reclaimable space':<20} {_format_size(reclaimable_bytes):<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("├" + "─" * width + "┤")
    print(f"│  Review file:                                         │")
    print(f"│  {str(output_path)[:width - 3]:<{width - 3}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_delete_duplicates_summary(moved: int, skipped: int, freed_bytes: int, duration: float) -> None:
    """Print a formatted duplicate-deletion summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Duplicate Deletion Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Moved to trash':<20} {moved:<{width - 23}}│")
    print(f"│  {'Skipped':<20} {skipped:<{width - 23}}│")
    print(f"│  {'Space freed':<20} {_format_size(freed_bytes):<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_find_missing_summary(total_checked: int, missing: int, output_path: Path, duration: float) -> None:
    """Print a formatted missing-file scan summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Missing File Scan Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Files checked':<20} {total_checked:<{width - 23}}│")
    print(f"│  {'Missing on disk':<20} {missing:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("├" + "─" * width + "┤")
    print(f"│  Review file:                                         │")
    print(f"│  {str(output_path)[:width - 3]:<{width - 3}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_delete_missing_summary(removed: int, skipped: int, duration: float) -> None:
    """Print a formatted missing-file removal summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Missing File Removal Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Removed':<20} {removed:<{width - 23}}│")
    print(f"│  {'Skipped':<20} {skipped:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_reconcile_summary(unchanged: int, moved: int, added: int, missing: int,
                               missing_csv_path: Path | None, duration: float) -> None:
    """Print a formatted reconcile summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Reconcile Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Unchanged':<20} {unchanged:<{width - 23}}│")
    print(f"│  {'Moved (path updated)':<20} {moved:<{width - 23}}│")
    print(f"│  {'Added (new files)':<20} {added:<{width - 23}}│")
    print(f"│  {'Still missing':<20} {missing:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    if missing_csv_path:
        print("├" + "─" * width + "┤")
        print(f"│  Review file:                                         │")
        print(f"│  {str(missing_csv_path)[:width - 3]:<{width - 3}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_faces_summary(processed: int, total_faces: int, failed: int, duration: float) -> None:
    """Print a formatted face-detection summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Face Detection Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Files processed':<20} {processed:<{width - 23}}│")
    print(f"│  {'Faces found':<20} {total_faces:<{width - 23}}│")
    print(f"│  {'Failed':<20} {failed:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _print_cluster_faces_summary(matched_existing: int, in_new_people: int, new_people_created: int, duration: float) -> None:
    """Print a formatted face-clustering summary to the console."""
    width = 56
    print()
    print("┌" + "─" * width + "┐")
    print(f"│{'FamilyVault Face Clustering Complete':^{width}}│")
    print("├" + "─" * width + "┤")
    print(f"│  {'Matched to people':<20} {matched_existing:<{width - 23}}│")
    print(f"│  {'Formed new people':<20} {in_new_people:<{width - 23}}│")
    print(f"│  {'New people created':<20} {new_people_created:<{width - 23}}│")
    print(f"│  {'Duration':<20} {_format_duration(duration):<{width - 23}}│")
    print("└" + "─" * width + "┘")
    print()


def _drive_trash_dir(path: Path) -> Path:
    """
    Determine a trash directory on the same drive as the given file, so
    deleted media is moved rather than copied across a slower connection.

    On macOS, external drives mount under /Volumes/<name> — that's used
    as the trash root when the file lives there. Falls back to a trash
    folder at the path's own drive root otherwise (e.g. an internal disk).
    """
    parts = path.parts
    if len(parts) >= 3 and parts[1] == "Volumes":
        drive_root = Path(*parts[:3])
    else:
        drive_root = Path(path.anchor)
    return drive_root / "FamilyVault_Trash"


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_scan(args) -> int:
    """Handle the scan subcommand."""
    root = Path(args.path).expanduser().resolve()

    if not root.exists():
        print(f"Error: path does not exist: {root}", file=sys.stderr)
        return 1

    if not root.is_dir():
        print(f"Error: path is not a directory: {root}", file=sys.stderr)
        return 1

    print(f"Scanning: {root}")
    print("This may take a moment for large libraries...\n")

    init_db()
    start = time.perf_counter()

    try:
        result = scan(root)
        scan_id = save_scan(result)
        duration = time.perf_counter() - start
        _print_summary(result, scan_id, duration)
        return 0

    except Exception as e:
        log.error(f"Scan failed: {e}")
        print(f"\nError: scan failed — {e}", file=sys.stderr)
        return 1


def cmd_caption(args) -> int:
    """Handle the caption subcommand — captions a limited batch of
    uncaptioned images and videos, so you can test before running the
    full library.

    With --auto, a failure that caption_media() has classified as
    permanent (CaptionResult.permanent — see captioner.py) is
    automatically marked skipped via mark_file_skipped(), the same
    mechanism the skip-file command uses, so it stops being pulled into
    future caption runs without you having to hand-copy its path. This
    is deliberately narrow: only failures captioner.py is confident are
    unrecoverable qualify (e.g. a file that isn't a recognizable image
    format at all). Video frame-extraction failures are never
    auto-skipped, even with this flag — see the comment in
    captioner.py's caption_video() for why — so those still need a
    manual `familyvault skip-file` once you've confirmed they're
    genuinely unrecoverable.
    """
    init_db()

    print(f"Looking for up to {args.limit} uncaptioned files...\n")
    pending = get_media_needing_captions(limit=args.limit)

    if not pending:
        print("Nothing to caption — every file already has a caption.")
        return 0

    print(f"Captioning {len(pending)} file(s)...\n")
    start = time.perf_counter()

    captioned = 0
    failed = 0
    auto_skipped = 0

    for i, file_record in enumerate(pending, start=1):
        path = Path(file_record["path"])
        label = path.name

        if not path.exists():
            print(f"  [{i}/{len(pending)}] {label} — skipped (file missing on disk)")
            failed += 1
            continue

        result = caption_media(path)

        if result.success:
            save_caption(file_record["id"], result.caption)
            captioned += 1
            preview = result.caption[:70] + ("..." if len(result.caption) > 70 else "")
            print(f"  [{i}/{len(pending)}] {label} — {preview}")
        else:
            failed += 1
            if args.auto and result.permanent:
                mark_file_skipped(file_record["id"], result.error)
                auto_skipped += 1
                print(f"  [{i}/{len(pending)}] {label} — failed, auto-skipped ({result.error})")
            else:
                print(f"  [{i}/{len(pending)}] {label} — failed ({result.error})")

    duration = time.perf_counter() - start
    _print_caption_summary(captioned, failed, duration, auto_skipped)
    return 0


def cmd_backfill_dates(args) -> int:
    """Handle the backfill-dates subcommand — fills in date_taken for a
    limited batch of existing files that don't have one yet, so older
    scans can be dated without re-running a full scan.

    Tries embedded metadata (EXIF for images) first, falling back to the
    file's on-disk modified time when no embedded date is available —
    which today means every video, since video metadata extraction
    doesn't currently capture a recording date.
    """
    init_db()

    print(f"Looking for up to {args.limit} files missing a date...\n")
    pending = get_files_missing_date(limit=args.limit)

    if not pending:
        print("Nothing to backfill — every file already has a date.")
        return 0

    print(f"Backfilling dates for {len(pending)} file(s)...\n")
    start = time.perf_counter()

    from_exif = 0
    from_file = 0
    failed = 0

    for i, file_record in enumerate(pending, start=1):
        path = Path(file_record["path"])
        label = path.name

        if not path.exists():
            print(f"  [{i}/{len(pending)}] {label} — skipped (file missing on disk)")
            failed += 1
            continue

        date_taken = None
        date_source = None

        try:
            meta = extract_metadata(path)
            if meta is not None and meta.has_datetime:
                date_taken = meta.taken_at
                date_source = "exif"
        except Exception as e:
            log.warning(f"Metadata extraction failed for {path.name}: {e}")

        if date_taken is None:
            try:
                mtime = path.stat().st_mtime
                date_taken = datetime.fromtimestamp(mtime).isoformat()
                date_source = "file_modified"
            except OSError:
                pass

        if date_taken is None:
            failed += 1
            print(f"  [{i}/{len(pending)}] {label} — failed (no date available)")
            continue

        save_date_taken(file_record["id"], date_taken, date_source)

        if date_source == "exif":
            from_exif += 1
        else:
            from_file += 1

        print(f"  [{i}/{len(pending)}] {label} — {date_taken} ({date_source})")

    duration = time.perf_counter() - start
    _print_date_summary(from_exif, from_file, failed, duration)
    return 0


def cmd_backfill_metadata(args) -> int:
    """Handle the backfill-metadata subcommand — fills in camera make/
    model and GPS coordinates (images) and width/height/codec/frame
    rate/duration (video) for a limited batch of existing files that
    haven't been processed yet.
    """
    init_db()

    print(f"Looking for up to {args.limit} files missing extended metadata...\n")
    pending = get_files_missing_metadata(limit=args.limit)

    if not pending:
        print("Nothing to backfill — every file already has extended metadata.")
        return 0

    print(f"Backfilling metadata for {len(pending)} file(s)...\n")
    start = time.perf_counter()

    processed = 0
    failed = 0

    for i, file_record in enumerate(pending, start=1):
        path = Path(file_record["path"])
        label = path.name

        if not path.exists():
            print(f"  [{i}/{len(pending)}] {label} — skipped (file missing on disk)")
            failed += 1
            continue

        try:
            meta = extract_metadata(path)
        except Exception as e:
            log.warning(f"Metadata extraction failed for {path.name}: {e}")
            meta = None

        save_extended_metadata(file_record["id"], meta)

        if meta is not None:
            processed += 1
            if file_record["is_video"]:
                detail = f"{meta.width}x{meta.height} {meta.codec or '?'} {meta.duration_seconds or '?'}s"
            else:
                detail = meta.camera_model or "no camera info"
            print(f"  [{i}/{len(pending)}] {label} — {detail}")
        else:
            failed += 1
            print(f"  [{i}/{len(pending)}] {label} — failed (no metadata extracted)")

    duration = time.perf_counter() - start
    _print_metadata_summary(processed, failed, duration)
    return 0


def cmd_backfill_location(args) -> int:
    """Handle the backfill-location subcommand — reverse geocodes GPS
    coordinates into city/state/country for a limited batch of existing
    files that have GPS but haven't been geocoded yet.

    Uses an offline dataset (reverse_geocoder) — no cloud API calls, no
    internet required. Files with no GPS coordinates are skipped
    entirely by get_files_missing_location() itself, since there's
    nothing to resolve for them (a majority of the library has no GPS —
    older cameras and scanned prints don't embed it).

    Requires the reverse_geocoder package: pip install reverse_geocoder
    """
    init_db()

    print(f"Looking for up to {args.limit} files with GPS but no location yet...\n")
    pending = get_files_missing_location(limit=args.limit)

    if not pending:
        print("Nothing to backfill — every file with GPS already has a location.")
        return 0

    print(f"Resolving locations for {len(pending)} file(s)...\n")
    start = time.perf_counter()

    resolved = 0
    failed = 0

    for i, file_record in enumerate(pending, start=1):
        label = Path(file_record["path"]).name
        lat = file_record["gps_lat"]
        lon = file_record["gps_lon"]

        location = resolve_location(lat, lon)

        if location is None or not location.has_location:
            failed += 1
            print(f"  [{i}/{len(pending)}] {label} — failed (could not resolve location)")
            continue

        save_location(file_record["id"], location.city, location.state, location.country)
        resolved += 1
        print(f"  [{i}/{len(pending)}] {label} — {location.display_name}")

    duration = time.perf_counter() - start
    _print_location_summary(resolved, failed, duration)
    return 0


def cmd_faces(args) -> int:
    """Handle the faces subcommand — detects faces and extracts
    embeddings for a limited batch of images that haven't been checked
    yet. Images only in this phase (see faces.py docstring). Does not
    assign anyone a name or cluster faces into people yet — every face
    is stored with person_id NULL; that's a separate future pass.
    """
    init_db()

    print(f"Looking for up to {args.limit} images not yet checked for faces...\n")
    pending = get_files_needing_faces(limit=args.limit)

    if not pending:
        print("Nothing to process — every image has already been checked for faces.")
        return 0

    print(f"Processing {len(pending)} file(s) — the first run will take a moment to load the model...\n")
    start = time.perf_counter()

    processed = 0
    total_faces = 0
    failed = 0

    for i, file_record in enumerate(pending, start=1):
        path = Path(file_record["path"])
        label = path.name

        if not path.exists():
            print(f"  [{i}/{len(pending)}] {label} — skipped (file missing on disk)")
            failed += 1
            continue

        result = detect_faces(path)

        if result.success:
            save_faces(file_record["id"], result.faces)
            processed += 1
            total_faces += len(result.faces)
            print(f"  [{i}/{len(pending)}] {label} — {len(result.faces)} face(s)")
        else:
            failed += 1
            print(f"  [{i}/{len(pending)}] {label} — failed ({result.error})")

    duration = time.perf_counter() - start
    _print_faces_summary(processed, total_faces, failed, duration)
    return 0


def cmd_cluster_faces(args) -> int:
    """
    Handle the cluster-faces subcommand — groups not-yet-clustered
    faces (person_id IS NULL) into people, matching against existing
    people first and creating new (unnamed) people for whatever's
    left. Safe to re-run any time new faces are added via
    `familyvault faces` — already-clustered faces are never touched,
    so previously-named people keep their name and their existing
    photos.

    MATCH_THRESHOLD in clustering.py is a starting heuristic, not a
    guarantee — use --threshold to try a different value without
    editing code, and `export-face-previews` to visually check results
    before committing to one. `reset-clustering` clears everything so
    a new threshold can be applied from scratch.
    """
    init_db()

    print(f"Looking for up to {args.limit} unclustered faces...\n")
    pending = get_faces_needing_clustering(limit=args.limit)

    if not pending:
        print("Nothing to cluster — every detected face already belongs to a person.")
        return 0

    print("Loading existing people for matching...")
    existing_people = get_people_with_faces()

    print(f"Clustering {len(pending)} face(s)...\n")
    start = time.perf_counter()

    assignments, new_people_specs = cluster_faces(pending, existing_people, match_threshold=args.threshold)

    # Create a real person row for each brand-new cluster, then remap
    # the negative placeholder ids cluster_faces() used to real ones.
    placeholder_to_real: dict[int, int] = {}
    for spec_idx in range(len(new_people_specs)):
        placeholder = -(spec_idx + 1)
        placeholder_to_real[placeholder] = create_person(name=None)

    by_person: dict[int, list[int]] = {}
    matched_existing = 0
    in_new_people = 0

    for a in assignments:
        real_person_id = placeholder_to_real[a.person_id] if a.person_id < 0 else a.person_id
        by_person.setdefault(real_person_id, []).append(a.face_id)
        if a.is_new_person:
            in_new_people += 1
        else:
            matched_existing += 1

    for person_id, face_ids in by_person.items():
        assign_faces_to_person(face_ids, person_id)

    duration = time.perf_counter() - start
    _print_cluster_faces_summary(matched_existing, in_new_people, len(new_people_specs), duration)
    return 0


def cmd_reset_clustering(args) -> int:
    """
    Handle the reset-clustering subcommand — clears person assignments
    and deletes person records, so cluster-faces can be re-run from
    scratch (e.g. after adjusting the match threshold). Face
    detections and embeddings themselves are never touched.

    Default is all-or-nothing (every person, named or not — see
    reset_face_clustering()). --unnamed-only instead scopes this to
    people with no name set, via reset_face_clustering_unnamed_only() —
    named people and every face already assigned to one are left
    completely untouched. That makes it safe to try a different
    --threshold on cluster-faces afterward without losing any naming
    (or merging) work already done, and safe to repeat more than once
    while dialing in a threshold that looks right.

    Requires typing 'yes' to confirm either way.
    """
    init_db()

    if args.unnamed_only:
        confirm = input(
            "This clears every UNNAMED person and their re-clustering assignment "
            "(not the detected faces or embeddings themselves, and not named "
            "people or their faces, which are left untouched). "
            "Type 'yes' to continue: "
        )
        if confirm.strip().lower() != "yes":
            print("Cancelled — nothing changed.")
            return 0

        count = reset_face_clustering_unnamed_only()
        print(f"Cleared {count} unnamed people. Their faces are unclustered again — run `familyvault cluster-faces` to rebuild. Named people were left untouched.")
        return 0

    confirm = input(
        "This clears every person and re-clustering assignment (not the detected "
        "faces or embeddings themselves). Any names already set will be lost. "
        "Type 'yes' to continue: "
    )
    if confirm.strip().lower() != "yes":
        print("Cancelled — nothing changed.")
        return 0

    count = reset_face_clustering()
    print(f"Cleared {count} people. Every face is unclustered again — run `familyvault cluster-faces` to rebuild.")
    return 0


def cmd_export_face_previews(args) -> int:
    """
    Handle the export-face-previews subcommand — a diagnostic tool for
    tuning the clustering threshold before a real People UI exists.
    Exports cropped face thumbnails for the largest N clustered people
    into folders you can browse in Finder — one folder per person. If
    every face in a folder is really the same person, and that same
    real person isn't also showing up split across other folders, the
    threshold is in a reasonable place.
    """
    init_db()

    print(f"Loading the {args.limit} largest clustered people...")
    people = get_faces_grouped_by_person(person_limit=args.limit)

    if not people:
        print("No clustered people found — run `familyvault cluster-faces` first.")
        return 0

    output_dir = Path(args.output).expanduser().resolve() if args.output else (PROJECT_ROOT / "face_previews")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    exported = 0
    for person in people:
        person_dir = output_dir / f"person_{person['id']}_({len(person['faces'])}_faces)"
        person_dir.mkdir(parents=True, exist_ok=True)

        for face in person["faces"][: args.faces_per_person]:
            source = Path(face["path"])
            if not source.exists():
                continue
            try:
                crop = crop_face(source, face["x"], face["y"], face["width"], face["height"])
                crop.save(person_dir / f"face_{face['id']}.jpg", format="JPEG", quality=85)
                exported += 1
            except Exception as e:
                log.warning(f"Could not crop face #{face['id']} from {source.name}: {e}")

    print(f"\nExported {exported} face crop(s) across {len(people)} people to:")
    print(f"  {output_dir}")
    print("\nBrowse in Finder. For each folder: is it really one person? Does that")
    print("same person also have a separate folder elsewhere?")
    return 0

def cmd_merge_people(args) -> int:
    """
    Handle the merge-people subcommand — combines two or more person
    ids (as seen in export-face-previews folder names, e.g.
    person_12_(8_faces)) into one. Every face from the loser id(s) is
    reassigned to the keeper id, and the loser person records are
    deleted.

    This exists specifically for cases clustering can't be expected to
    solve on its own — most notably the same person at very different
    ages (a baby vs a child vs an adult), where embeddings are too
    different for any similarity threshold to safely bridge without
    also risking merging different people elsewhere. Merging is always
    a deliberate, explicit action here, never automatic.
    """
    init_db()

    keeper_id = args.keeper
    loser_ids = args.losers

    keeper = get_person(keeper_id)
    if keeper is None:
        print(f"Error: person #{keeper_id} not found.", file=sys.stderr)
        return 1

    missing = [pid for pid in loser_ids if get_person(pid) is None]
    if missing:
        print(f"Error: person id(s) not found: {missing}", file=sys.stderr)
        return 1

    keeper_before = count_faces_for_person(keeper_id)
    print(f"Merging into person #{keeper_id} ({keeper['name'] or 'unnamed'}, {keeper_before} face(s) currently):")
    for pid in loser_ids:
        other = get_person(pid)
        other_count = count_faces_for_person(pid)
        print(f"  + person #{pid} ({other['name'] or 'unnamed'}, {other_count} face(s))")

    reassigned = merge_people(keeper_id, loser_ids)
    print(f"\nDone — {reassigned} face(s) reassigned to person #{keeper_id}. {len(loser_ids)} person record(s) removed.")
    return 0


def cmd_discard_person(args) -> int:
    """
    Handle the discard-person subcommand — permanently deletes every
    face detection assigned to a person, then removes the person
    record. Meant for a cluster clustering has incorrectly formed from
    unrelated people's low-quality detections — most commonly side-
    profile faces, whose embeddings are too indistinct to be a
    reliable identity signal, ending up clustered together despite not
    actually being the same person. That's a different situation from
    a real person split across too many fragments (which
    merge-people fixes instead) — export-face-previews is the way to
    visually spot which case you're looking at before deciding.

    Refuses to run on a named person — naming implies you've confirmed
    it's a real, correctly-identified individual, a fundamentally
    different situation from a junk cluster that was never really
    anyone. Face detections (and their embeddings) are deleted
    permanently; there's no undo. The underlying photos themselves are
    never touched — only the incorrect face tag goes away.
    """
    init_db()

    person = get_person(args.person_id)
    if person is None:
        print(f"Error: person #{args.person_id} not found.", file=sys.stderr)
        return 1

    if person["name"] is not None:
        print(
            f"Error: person #{args.person_id} is named '{person['name']}' — "
            "discard-person only works on unnamed clusters, to avoid ever "
            "accidentally deleting a real, identified person's face data. "
            "If this genuinely needs removing, do it deliberately some other way.",
            file=sys.stderr,
        )
        return 1

    face_count = count_faces_for_person(args.person_id)
    if face_count == 0:
        print(f"Person #{args.person_id} has no faces — nothing to discard.")
        return 0

    print(f"Person #{args.person_id} (unnamed) has {face_count} face(s) across their photos.")
    confirm = input(
        "This permanently deletes these face detections (and their embeddings) "
        "— not the photos themselves, just the face tags. There's no undo. "
        "Type 'yes' to continue: "
    )
    if confirm.strip().lower() != "yes":
        print("Cancelled — nothing changed.")
        return 0

    deleted = discard_person(args.person_id)
    print(f"Discarded person #{args.person_id} — {deleted} face(s) permanently deleted.")
    return 0


def cmd_name_person(args) -> int:
    """Handle the name-person subcommand — sets or updates a person's name."""
    init_db()

    person = get_person(args.person_id)
    if person is None:
        print(f"Error: person #{args.person_id} not found.", file=sys.stderr)
        return 1

    set_person_name(args.person_id, args.name)
    print(f"Person #{args.person_id} named '{args.name}'.")
    return 0

def cmd_skip_file(args) -> int:
    """
    Handle the skip-file subcommand — marks one or more files as
    permanently skipped, with a reason, so they stop being retried by
    every future caption/backfill-dates/backfill-metadata/
    backfill-location run.

    This is deliberately manual: the app never decides on its own that
    a file is unfixable. Files are looked up by their exact path (as
    stored in the database, and as printed in caption/backfill log
    lines) rather than by database ID, so a path can be copied straight
    out of a failure message.
    """
    init_db()

    marked = 0
    not_found = 0

    for path_str in args.paths:
        record = get_file_by_path(path_str)
        if record is None:
            print(f"Not found in database (check the path is exact): {path_str}")
            not_found += 1
            continue

        mark_file_skipped(record["id"], args.reason)
        print(f"Skipped: {path_str}")
        marked += 1

    print(f"\n{marked} file(s) marked skipped, {not_found} not found.")
    return 0


def cmd_unskip_file(args) -> int:
    """
    Handle the unskip-file subcommand — clears skip_reason for one or
    more files, returning them to normal processing. Useful after a fix
    makes something that used to fail now work, or to undo a mistaken
    skip.
    """
    init_db()

    unmarked = 0
    not_found = 0

    for path_str in args.paths:
        record = get_file_by_path(path_str)
        if record is None:
            print(f"Not found in database (check the path is exact): {path_str}")
            not_found += 1
            continue

        unmark_file_skipped(record["id"])
        print(f"Un-skipped: {path_str}")
        unmarked += 1

    print(f"\n{unmarked} file(s) un-skipped, {not_found} not found.")
    return 0


def cmd_list_skipped(args) -> int:
    """Handle the list-skipped subcommand — prints every currently-skipped file and its reason."""
    init_db()

    skipped = get_skipped_files()

    if not skipped:
        print("No files are currently marked skipped.")
        return 0

    print(f"{len(skipped)} skipped file(s):\n")
    for record in skipped:
        print(f"  [{record['id']}] {record['path']}")
        print(f"      reason: {record['skip_reason']}")

    return 0


def cmd_find_duplicates(args) -> int:
    """Handle the find-duplicates subcommand — scans the full library
    for exact (byte-for-byte identical) duplicate files and writes a
    review CSV. Nothing is deleted by this command — review the CSV
    and run delete-duplicates against it when ready.
    """
    init_db()

    output_path = Path(args.output).expanduser().resolve() if args.output else (PROJECT_ROOT / "duplicates_review.csv")

    print("Loading file list from database...")
    records = get_all_files()

    if not records:
        print("No files in the database — run a scan first.")
        return 0

    by_path = {r["path"]: r for r in records}
    paths = [Path(r["path"]) for r in records]

    print(f"Hashing {len(paths)} files — this reads full file contents and may take a while...\n")
    start = time.perf_counter()

    report = find_exact_duplicates(paths)

    if not report.groups:
        duration = time.perf_counter() - start
        print(f"\nNo exact duplicates found ({report.errors} file(s) could not be hashed).")
        print(f"Duration: {_format_duration(duration)}")
        return 0

    reclaimable_bytes = 0
    csv_rows = []

    for group_id, group in enumerate(report.groups, start=1):
        keeper = group.keeper
        for f in sorted(group.files):
            record = by_path.get(str(f))
            if record is None:
                continue
            action = "keep" if f == keeper else "delete"
            if action == "delete":
                reclaimable_bytes += record["size_bytes"]
            csv_rows.append({
                "group_id": group_id,
                "file_id": record["id"],
                "path": record["path"],
                "size_bytes": record["size_bytes"],
                "action": action,
            })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["group_id", "file_id", "path", "size_bytes", "action"])
        writer.writeheader()
        writer.writerows(csv_rows)

    duration = time.perf_counter() - start
    _print_find_duplicates_summary(
        report.total_groups, report.total_duplicates, reclaimable_bytes, output_path, duration
    )
    print("Review the CSV and edit the 'action' column if needed (keep/delete).")
    print(f"When ready: familyvault delete-duplicates {output_path}")
    print()
    return 0


def cmd_delete_duplicates(args) -> int:
    """Handle the delete-duplicates subcommand — reads a reviewed CSV
    (produced by find-duplicates) and, for every row marked 'delete',
    moves the file to a trash folder on the same drive, removes its
    thumbnail, and removes its database record.

    Deletion is driven entirely by the CSV, not a fresh duplicate scan,
    so what gets removed matches exactly what was reviewed.
    """
    init_db()

    review_path = Path(args.review_file).expanduser().resolve()
    if not review_path.exists():
        print(f"Error: review file not found: {review_path}", file=sys.stderr)
        return 1

    with open(review_path, newline="") as f:
        rows = list(csv.DictReader(f))

    to_delete = [r for r in rows if r["action"].strip().lower() == "delete"]

    if not to_delete:
        print("No rows marked 'delete' in the review file — nothing to do.")
        return 0

    print(f"Deleting {len(to_delete)} file(s) marked for deletion...\n")
    start = time.perf_counter()

    moved = 0
    skipped = 0
    freed_bytes = 0

    for i, row in enumerate(to_delete, start=1):
        file_id = int(row["file_id"])
        source = Path(row["path"])
        label = source.name

        if not source.exists():
            print(f"  [{i}/{len(to_delete)}] {label} — skipped (file missing on disk)")
            skipped += 1
            continue

        try:
            trash_dir = _drive_trash_dir(source)
            trash_dir.mkdir(parents=True, exist_ok=True)
            dest = trash_dir / f"{file_id}_{source.name}"

            shutil.move(str(source), str(dest))

            thumb = thumbnail_path(source)
            if thumb.exists():
                thumb.unlink()

            delete_file_record(file_id)

            moved += 1
            freed_bytes += int(row["size_bytes"])
            print(f"  [{i}/{len(to_delete)}] {label} — moved to trash")

        except Exception as e:
            log.warning(f"Could not delete {label}: {e}")
            print(f"  [{i}/{len(to_delete)}] {label} — failed ({e})")
            skipped += 1

    duration = time.perf_counter() - start
    _print_delete_duplicates_summary(moved, skipped, freed_bytes, duration)
    return 0


def cmd_find_missing(args) -> int:
    """Handle the find-missing subcommand — checks every file the
    database knows about against what's actually still on disk, and
    writes a review CSV for anything missing (e.g. deleted from the
    watched Drive folder). Nothing is deleted by this command — review
    the CSV and run delete-missing against it when ready.

    A file being missing here isn't necessarily permanent: it could
    also mean a removable drive is unplugged, or a cloud-synced folder
    (like Google Drive) hasn't finished propagating a delete yet, or
    the file simply moved elsewhere. The CSV lets you flip 'action' to
    'keep' for anything you're not sure about before it's actually
    removed from the library. For files that move within a watched
    folder rather than truly disappear, prefer `reconcile` instead —
    it detects and repairs moves automatically rather than treating
    them as deletions.
    """
    init_db()

    output_path = Path(args.output).expanduser().resolve() if args.output else (PROJECT_ROOT / "missing_review.csv")

    print("Loading file list from database...")
    records = get_all_files()

    if not records:
        print("No files in the database — run a scan first.")
        return 0

    print(f"Checking {len(records)} file(s) against disk...\n")
    start = time.perf_counter()

    missing_rows = []
    for record in records:
        path = Path(record["path"])
        if not path.exists():
            missing_rows.append({
                "file_id": record["id"],
                "path": record["path"],
                "size_bytes": record["size_bytes"],
                "action": "delete",
            })

    duration = time.perf_counter() - start

    if not missing_rows:
        print(f"\nEvery file in the database was found on disk ({len(records)} checked).")
        print(f"Duration: {_format_duration(duration)}")
        return 0

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file_id", "path", "size_bytes", "action"])
        writer.writeheader()
        writer.writerows(missing_rows)

    _print_find_missing_summary(len(records), len(missing_rows), output_path, duration)
    print("Review the CSV — change 'action' to 'keep' for anything that's just")
    print("temporarily unavailable (unmounted drive, still syncing) rather than")
    print("actually gone.")
    print(f"When ready: familyvault delete-missing {output_path}")
    print()
    return 0


def cmd_delete_missing(args) -> int:
    """Handle the delete-missing subcommand — reads a reviewed CSV
    (produced by find-missing or reconcile) and, for every row marked
    'delete', removes its database record and any cached thumbnail.

    Unlike delete-duplicates, there's no source file to move to trash
    here — by definition, these files are already gone from disk. This
    only cleans up the leftover database row (which is what makes a
    removed file still show up in search results) and its thumbnail
    cache file, if one exists.
    """
    init_db()

    review_path = Path(args.review_file).expanduser().resolve()
    if not review_path.exists():
        print(f"Error: review file not found: {review_path}", file=sys.stderr)
        return 1

    with open(review_path, newline="") as f:
        rows = list(csv.DictReader(f))

    to_delete = [r for r in rows if r["action"].strip().lower() == "delete"]

    if not to_delete:
        print("No rows marked 'delete' in the review file — nothing to do.")
        return 0

    print(f"Removing {len(to_delete)} file record(s) marked for deletion...\n")
    start = time.perf_counter()

    removed = 0
    skipped = 0

    for i, row in enumerate(to_delete, start=1):
        file_id = int(row["file_id"])
        source = Path(row["path"])
        label = source.name

        # Guard against the file having reappeared since the review CSV
        # was generated (e.g. a drive got remounted, Drive sync finished
        # catching up, or it was actually a move caught late) — don't
        # remove the record for a file that's actually there now.
        if source.exists():
            print(f"  [{i}/{len(to_delete)}] {label} — skipped (file exists on disk again)")
            skipped += 1
            continue

        try:
            thumb = thumbnail_path(source)
            if thumb.exists():
                thumb.unlink()

            delete_file_record(file_id)

            removed += 1
            print(f"  [{i}/{len(to_delete)}] {label} — removed")

        except Exception as e:
            log.warning(f"Could not remove record for {label}: {e}")
            print(f"  [{i}/{len(to_delete)}] {label} — failed ({e})")
            skipped += 1

    duration = time.perf_counter() - start
    _print_delete_missing_summary(removed, skipped, duration)
    return 0


def cmd_reconcile(args) -> int:
    """
    Handle the reconcile subcommand — the all-in-one sync for a watched
    folder. In a single pass over the current contents of `path`:

      1. Files that moved to a new location under the same root (same
         filename + size, found at a different path than the database
         has on record) have their database row's path updated in
         place — caption, date, camera/GPS/location data are all
         preserved, since it's the same file, just relocated.
      2. Files found on disk with no matching database record at all
         (new, and not a move-target for anything missing) are added
         as a new scan, with full metadata extraction — same as a
         normal `scan` run.
      3. Files the database has on record (under this root) that
         aren't on disk anymore, and don't match any on-disk file by
         name+size, are written to a review CSV — exactly like
         find-missing — rather than deleted automatically. Run
         delete-missing against that CSV once you've confirmed they're
         genuinely gone, not just missed by the name+size match.

    This command never deletes a database record itself — steps 1 and
    2 are safe to run unattended (e.g. on a schedule); step 3 always
    stops short of the destructive part, on purpose.

    Move-matching is done by (filename, size_bytes), and only ever
    resolved automatically when it's unambiguous: exactly one missing
    database record and exactly one on-disk candidate share that key.
    If either side has more than one (e.g. two identically-named,
    identically-sized files), nothing is auto-matched for that key —
    the missing record(s) go to the review CSV and the on-disk
    candidate(s) are added as new files, rather than risk attaching
    one file's metadata to a different one.

    Refuses to run at all if `path` doesn't exist, rather than treating
    every database record under it as missing — an unmounted drive
    should never look like a mass deletion.
    """
    root = Path(args.path).expanduser().resolve()

    if not root.exists():
        print(f"Error: path does not exist (is the drive mounted?): {root}", file=sys.stderr)
        return 1

    if not root.is_dir():
        print(f"Error: path is not a directory: {root}", file=sys.stderr)
        return 1

    init_db()

    print(f"Reconciling: {root}")
    print("Walking the folder...\n")
    start = time.perf_counter()

    try:
        scan_result = scan(root)
    except Exception as e:
        log.error(f"Reconcile scan failed: {e}")
        print(f"\nError: could not walk {root} — {e}", file=sys.stderr)
        return 1

    current_by_path = {str(f.path): f for f in scan_result.media_files}

    print("Comparing against database records under this root...")
    existing_records = get_files_under_root(str(root))
    existing_by_path = {r["path"]: r for r in existing_records}

    unmatched_current = {
        path: f for path, f in current_by_path.items() if path not in existing_by_path
    }
    missing_records = [
        record for path, record in existing_by_path.items() if path not in current_by_path
    ]
    unchanged = len(existing_by_path) - len(missing_records)

    candidates_by_key: dict = {}
    for path, f in unmatched_current.items():
        key = (f.path.name, f.size_bytes)
        candidates_by_key.setdefault(key, []).append(path)

    missing_by_key: dict = {}
    for record in missing_records:
        key = (Path(record["path"]).name, record["size_bytes"])
        missing_by_key.setdefault(key, []).append(record)

    moved = 0
    still_missing: list[dict] = []
    consumed_paths: set = set()

    for record in missing_records:
        key = (Path(record["path"]).name, record["size_bytes"])
        candidates = candidates_by_key.get(key, [])
        same_key_missing = missing_by_key.get(key, [])

        if len(candidates) == 1 and len(same_key_missing) == 1:
            new_path = candidates[0]
            update_file_path(record["id"], new_path)
            consumed_paths.add(new_path)
            moved += 1
            print(f"  Moved: {record['path']} -> {new_path}")
        else:
            still_missing.append(record)

    new_files = [f for path, f in unmatched_current.items() if path not in consumed_paths]

    added = 0
    if new_files:
        print(f"\nAdding {len(new_files)} new file(s)...")
        new_result = ScanResult(root=root, media_files=new_files)
        save_scan(new_result)
        added = len(new_files)

    duration = time.perf_counter() - start

    missing_csv_path = None
    if still_missing:
        missing_csv_path = Path(args.output).expanduser().resolve() if args.output else (PROJECT_ROOT / "missing_review.csv")
        with open(missing_csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["file_id", "path", "size_bytes", "action"])
            writer.writeheader()
            for record in still_missing:
                writer.writerow({
                    "file_id": record["id"],
                    "path": record["path"],
                    "size_bytes": record["size_bytes"],
                    "action": "delete",
                })

    _print_reconcile_summary(unchanged, moved, added, len(still_missing), missing_csv_path, duration)

    if still_missing:
        print("Some files are still missing after move-matching — review the CSV before deleting:")
        print(f"  {missing_csv_path}")
        print(f"When ready: familyvault delete-missing {missing_csv_path}")
        print()

    return 0


# ── Entry Point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="familyvault",
        description="Private AI-powered photo and video library.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # scan subcommand
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan a directory for media files.",
    )
    scan_parser.add_argument(
        "path",
        metavar="<path>",
        help="Directory to scan.",
    )
    scan_parser.set_defaults(func=cmd_scan)

    # caption subcommand
    caption_parser = subparsers.add_parser(
        "caption",
        help="Generate AI captions for a limited batch of uncaptioned files.",
    )
    caption_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of files to caption in this run (default: 20).",
    )
    caption_parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Automatically skip files whose failure is confidently unrecoverable "
            "(e.g. not a recognizable image format at all), same as running "
            "skip-file by hand. Video frame-extraction failures are never "
            "auto-skipped -- use skip-file manually for those once confirmed."
        ),
    )
    caption_parser.set_defaults(func=cmd_caption)

    # backfill-dates subcommand
    backfill_parser = subparsers.add_parser(
        "backfill-dates",
        help="Fill in date_taken for a limited batch of existing files.",
    )
    backfill_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of files to process in this run (default: 100).",
    )
    backfill_parser.set_defaults(func=cmd_backfill_dates)

    # backfill-metadata subcommand
    backfill_meta_parser = subparsers.add_parser(
        "backfill-metadata",
        help="Fill in camera/GPS/technical metadata for a limited batch of existing files.",
    )
    backfill_meta_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of files to process in this run (default: 100).",
    )
    backfill_meta_parser.set_defaults(func=cmd_backfill_metadata)

    # backfill-location subcommand
    backfill_loc_parser = subparsers.add_parser(
        "backfill-location",
        help="Reverse geocode GPS coordinates into city/state/country for a limited batch of existing files.",
    )
    backfill_loc_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of files to process in this run (default: 100).",
    )
    backfill_loc_parser.set_defaults(func=cmd_backfill_location)

    # faces subcommand
    faces_parser = subparsers.add_parser(
        "faces",
        help="Detect faces and extract embeddings for a limited batch of not-yet-checked images.",
    )
    faces_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of files to process in this run (default: 20).",
    )
    faces_parser.set_defaults(func=cmd_faces)

    # cluster-faces subcommand
    cluster_faces_parser = subparsers.add_parser(
        "cluster-faces",
        help="Group not-yet-clustered faces into people, matching against existing people first.",
    )
    cluster_faces_parser.add_argument(
        "--limit",
        type=int,
        default=2000,
        help="Maximum number of faces to process in this run (default: 2000).",
    )
    cluster_faces_parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override the match distance threshold for this run. Lower = stricter (more, smaller people); higher = looser (fewer, larger people).",
    )
    cluster_faces_parser.set_defaults(func=cmd_cluster_faces)

    # reset-clustering subcommand
    reset_clustering_parser = subparsers.add_parser(
        "reset-clustering",
        help="Clear person assignments and delete people, so cluster-faces can be re-run from scratch.",
    )
    reset_clustering_parser.add_argument(
        "--unnamed-only",
        action="store_true",
        help="Only clear and delete unnamed people, leaving named people and their faces completely untouched.",
    )
    reset_clustering_parser.set_defaults(func=cmd_reset_clustering)

    # export-face-previews subcommand
    export_previews_parser = subparsers.add_parser(
        "export-face-previews",
        help="Export cropped face thumbnails grouped by person, for visually tuning the clustering threshold.",
    )
    export_previews_parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Number of largest people to export (default: 30).",
    )
    export_previews_parser.add_argument(
        "--faces-per-person",
        type=int,
        default=6,
        help="Max faces to export per person (default: 6).",
    )
    export_previews_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output folder (default: face_previews/ at project root).",
    )
    export_previews_parser.set_defaults(func=cmd_export_face_previews)

# merge-people subcommand
    merge_people_parser = subparsers.add_parser(
        "merge-people",
        help="Merge one or more people into a single keeper person (e.g. the same person at different ages).",
    )
    merge_people_parser.add_argument(
        "keeper",
        type=int,
        metavar="<keeper_id>",
        help="Person id to keep — every merged face ends up here.",
    )
    merge_people_parser.add_argument(
        "losers",
        type=int,
        nargs="+",
        metavar="<person_id>",
        help="One or more person id(s) to merge into keeper and remove.",
    )
    merge_people_parser.set_defaults(func=cmd_merge_people)

    # discard-person subcommand
    discard_person_parser = subparsers.add_parser(
        "discard-person",
        help="Permanently delete a junk/incorrect unnamed person's face detections (never works on a named person).",
    )
    discard_person_parser.add_argument(
        "person_id",
        type=int,
        metavar="<person_id>",
        help="Person id to discard — every face detection they have is permanently deleted.",
    )
    discard_person_parser.set_defaults(func=cmd_discard_person)

    # name-person subcommand
    name_person_parser = subparsers.add_parser(
        "name-person",
        help="Set or update a person's name.",
    )
    name_person_parser.add_argument("person_id", type=int, metavar="<person_id>")
    name_person_parser.add_argument("name", type=str, metavar="<name>")
    name_person_parser.set_defaults(func=cmd_name_person)

    # skip-file subcommand
    skip_parser = subparsers.add_parser(
        "skip-file",
        help="Mark one or more files as permanently skipped (stop retrying them in future caption/backfill runs).",
    )
    skip_parser.add_argument(
        "paths",
        metavar="<path>",
        nargs="+",
        help="Exact file path(s) as stored in the database (copy from a caption/backfill log line).",
    )
    skip_parser.add_argument(
        "--reason",
        type=str,
        required=True,
        help="Why this file is being skipped, e.g. 'corrupt: moov atom not found'.",
    )
    skip_parser.set_defaults(func=cmd_skip_file)

    # unskip-file subcommand
    unskip_parser = subparsers.add_parser(
        "unskip-file",
        help="Clear the skipped status on one or more files, returning them to normal processing.",
    )
    unskip_parser.add_argument(
        "paths",
        metavar="<path>",
        nargs="+",
        help="Exact file path(s) as stored in the database.",
    )
    unskip_parser.set_defaults(func=cmd_unskip_file)

    # list-skipped subcommand
    list_skipped_parser = subparsers.add_parser(
        "list-skipped",
        help="List every file currently marked as skipped, with its reason.",
    )
    list_skipped_parser.set_defaults(func=cmd_list_skipped)

    # find-duplicates subcommand
    find_dupes_parser = subparsers.add_parser(
        "find-duplicates",
        help="Scan the full library for exact duplicate files and write a review CSV.",
    )
    find_dupes_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write the review CSV (default: duplicates_review.csv at project root).",
    )
    find_dupes_parser.set_defaults(func=cmd_find_duplicates)

    # delete-duplicates subcommand
    delete_dupes_parser = subparsers.add_parser(
        "delete-duplicates",
        help="Delete files marked 'delete' in a reviewed duplicates CSV.",
    )
    delete_dupes_parser.add_argument(
        "review_file",
        metavar="<review_file>",
        help="Path to the reviewed CSV produced by find-duplicates.",
    )
    delete_dupes_parser.set_defaults(func=cmd_delete_duplicates)

    # find-missing subcommand
    find_missing_parser = subparsers.add_parser(
        "find-missing",
        help="Check every file in the database against disk and write a review CSV of anything missing.",
    )
    find_missing_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write the review CSV (default: missing_review.csv at project root).",
    )
    find_missing_parser.set_defaults(func=cmd_find_missing)

    # delete-missing subcommand
    delete_missing_parser = subparsers.add_parser(
        "delete-missing",
        help="Remove database records (and cached thumbnails) for files marked 'delete' in a reviewed missing-file CSV.",
    )
    delete_missing_parser.add_argument(
        "review_file",
        metavar="<review_file>",
        help="Path to the reviewed CSV produced by find-missing or reconcile.",
    )
    delete_missing_parser.set_defaults(func=cmd_delete_missing)

    # reconcile subcommand
    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Sync the database with a watched folder: detect moves, add new files, and flag genuinely missing ones for review.",
    )
    reconcile_parser.add_argument(
        "path",
        metavar="<path>",
        help="Watched root directory to reconcile against.",
    )
    reconcile_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write the still-missing review CSV, if any (default: missing_review.csv at project root).",
    )
    reconcile_parser.set_defaults(func=cmd_reconcile)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()