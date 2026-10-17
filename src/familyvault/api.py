"""
FamilyVault FastAPI Backend
Provides a REST API for accessing the FamilyVault library.
Run with: uvicorn familyvault.api:app --reload --host 0.0.0.0
"""

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from familyvault.database import (
    init_db,
    get_all_scans,
    get_scan_files,
    get_file_count,
    get_file_by_id,
    search_media,
    count_media_search,
    get_people_with_counts,
    count_people,
    get_person,
    get_person_cover_face,
    get_people_for_file,
    get_face_by_id,
    get_named_people_for_files,
    get_files_for_person,
    count_files_for_person,
    set_person_name,
    merge_people,
    get_named_people,
)
from familyvault.query_parser import parse_query
from familyvault.thumbnailer import generate_thumbnail, generate_preview
from familyvault.config import NON_BROWSER_SAFE_IMAGE_EXTENSIONS
from familyvault.faces import get_or_create_face_thumbnail
from familyvault.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("FamilyVault API started")
    yield


app = FastAPI(
    title="FamilyVault",
    description="Private AI-powered photo and video library.",
    version="0.1.4",
    lifespan=lifespan,
)

# Allows the dev frontend on localhost, plus any device on a typical home
# 192.168.x.x subnet (e.g. a family member's phone or laptop on the same
# WiFi), on the standard Vite/CRA dev ports. Scoped to private-network
# ranges only, not open to arbitrary origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_origin_regex=r"http://192\.168\.\d{1,3}\.\d{1,3}:(3000|5173)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Catches any error not already handled elsewhere (e.g. HTTPException,
    validation errors, which keep their own normal responses). Logs the
    full error server-side for debugging, but returns a plain, readable
    JSON error to the client rather than an HTML traceback page.
    """
    log.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."},
    )


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "total_files": get_file_count(),
    }


@app.get("/scans", tags=["scans"])
async def list_scans():
    """
    Raw scan history (one row per `familyvault scan` run). Not currently
    used by the frontend, which now presents one unified library rather
    than browsing scan-by-scan — kept here as a still-valid part of the
    API surface, e.g. for direct inspection or future tooling.
    """
    scans = get_all_scans()
    return {"scans": scans, "count": len(scans)}


@app.get("/scans/{scan_id}", tags=["scans"])
async def get_scan(scan_id: int):
    scans = get_all_scans()
    scan = next((s for s in scans if s["id"] == scan_id), None)
    if scan is None:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found")
    return scan


@app.get("/scans/{scan_id}/files", tags=["files"])
async def list_scan_files(
    scan_id: int,
    extension: Optional[str] = Query(None, description="Filter by extension e.g. .jpg"),
    media_type: Optional[str] = Query(None, description="Filter by type: image or video"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    files = get_scan_files(scan_id)
    if not files and scan_id not in {s["id"] for s in get_all_scans()}:
        raise HTTPException(status_code=404, detail=f"Scan {scan_id} not found")
    if extension:
        ext = extension if extension.startswith(".") else f".{extension}"
        files = [f for f in files if f["extension"] == ext.lower()]
    if media_type == "image":
        files = [f for f in files if f["is_image"]]
    elif media_type == "video":
        files = [f for f in files if f["is_video"]]
    total = len(files)
    page = files[offset: offset + limit]
    return {
        "scan_id": scan_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "files": page,
    }


@app.get("/files/count", tags=["files"])
async def total_file_count():
    return {"total_files": get_file_count()}


@app.get("/files/{file_id}/thumbnail", tags=["files"])
async def get_file_thumbnail(file_id: int):
    """
    Return a JPEG thumbnail for a media file, generating it on first
    request if it doesn't exist on disk yet. Returns 404 if the file
    record doesn't exist, the source is missing (e.g. external drive
    unplugged), or thumbnail generation fails (e.g. corrupt file,
    unsupported video codec).
    """
    file_record = get_file_by_id(file_id)
    if file_record is None:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")

    source = Path(file_record["path"])
    if not source.exists():
        log.warning(f"Source file missing for thumbnail request: {source}")
        raise HTTPException(status_code=404, detail="Source file not found on disk")

    thumb = generate_thumbnail(source)
    if thumb is None:
        raise HTTPException(status_code=404, detail="Could not generate thumbnail for this file")

    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/files/{file_id}/media", tags=["files"])
async def get_file_media(file_id: int):
    """
    Stream the full-resolution image or video file for viewing (e.g. in
    a lightbox). Video and browser-safe image formats (JPEG, PNG, GIF,
    WebP, BMP) stream as the original file, unchanged, exactly as
    before.

    Image formats a browser can't decode inline — HEIC/HEIF and TIFF,
    see config.NON_BROWSER_SAFE_IMAGE_EXTENSIONS — are instead converted
    to a full-resolution JPEG preview on first request and cached
    thereafter (see thumbnailer.generate_preview()). Without this,
    streaming those formats' original bytes into an <img> tag silently
    fails to render client-side even though the file itself streams
    successfully — the thumbnail grid still works because thumbnails
    are always pre-converted to JPEG regardless of source format.

    RAW formats (.cr2/.nef/.arw/.raw) aren't covered by this — Pillow
    can't open them without an additional dependency — and continue to
    stream as the original file, same as before this fix.

    Returns 404 if the file record doesn't exist, the source is missing
    on disk (e.g. external drive unplugged), or — for a
    NON_BROWSER_SAFE_IMAGE_EXTENSIONS file — preview generation fails
    (e.g. corrupt file).
    """
    file_record = get_file_by_id(file_id)
    if file_record is None:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")

    source = Path(file_record["path"])
    if not source.exists():
        log.warning(f"Source file missing for media request: {source}")
        raise HTTPException(status_code=404, detail="Source file not found on disk")

    ext = source.suffix.lower()
    if ext in NON_BROWSER_SAFE_IMAGE_EXTENSIONS:
        preview = generate_preview(source)
        if preview is None:
            raise HTTPException(status_code=404, detail="Could not generate a viewable preview for this file")
        return FileResponse(preview, media_type="image/jpeg")

    media_type, _ = mimetypes.guess_type(str(source))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(source, media_type=media_type)


@app.get("/files/{file_id}/people", tags=["files"])
async def get_file_people(file_id: int):
    """
    List every clustered person detected in a single media file — powers
    the lightbox's "who's in this photo" panel. Only faces already
    assigned to a person (via cluster-faces) are included; see
    get_people_for_file() for why unclustered faces are excluded.

    404s only if the file itself doesn't exist — a file with zero
    detected or zero clustered faces returns an empty list, not a 404,
    since that's a normal, valid state (not every photo has a face
    in it).
    """
    file_record = get_file_by_id(file_id)
    if file_record is None:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")

    people = get_people_for_file(file_id)
    return {"file_id": file_id, "people": people}


@app.get("/faces/{face_id}/thumbnail", tags=["faces"])
async def get_face_thumbnail(face_id: int):
    """
    Return a cropped thumbnail of one specific detected face, from the
    exact photo it was found in. Distinct from /people/{id}/cover, which
    shows a person's single best face from anywhere in the library —
    this always matches whatever photo is currently open in the
    lightbox, which matters when naming: a person's general cover photo
    could be a totally different, more recent picture, and would be
    confusing to name against here.
    """
    face = get_face_by_id(face_id)
    if face is None:
        raise HTTPException(status_code=404, detail=f"Face {face_id} not found")

    source = Path(face["path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source file not found on disk")

    thumb = get_or_create_face_thumbnail(
        face["id"], source, face["x"], face["y"], face["width"], face["height"]
    )
    if thumb is None:
        raise HTTPException(status_code=404, detail="Could not generate face thumbnail")

    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/people", tags=["people"])
async def list_people(
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Max people to return. Omit for the full roster (used by the merge picker)."),
    offset: int = Query(0, ge=0),
):
    """
    List people, largest face count first. `name` is null until
    someone names them via PATCH /people/{id} — display_name is a
    ready-to-show fallback ("Unknown Person #<id>") computed here
    rather than stored, so it never needs backfilling if the numbering
    shifts.

    Paginated when limit is supplied (what the People grid uses, to
    avoid loading/rendering every person — and fetching every cover
    image — at once on a library with tens of thousands of person
    records). Omitting limit returns everyone in one response, which
    the merge picker relies on for its full-roster search.
    """
    people = get_people_with_counts(limit=limit, offset=offset)
    total = count_people()
    return {
        "people": [
            {
                "id": p["id"],
                "name": p["name"],
                "display_name": p["name"] or f"Unknown Person #{p['id']}",
                "face_count": p["face_count"],
                "has_cover": p["cover_face_id"] is not None,
            }
            for p in people
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(people),
    }


@app.get("/people/{person_id}/cover", tags=["people"])
async def get_person_cover(person_id: int):
    """
    Return a cropped face thumbnail representing this person — their
    highest-confidence face, generated on first request and cached
    thereafter. 404s if the person doesn't exist, has no faces yet, or
    their source file is missing on disk.
    """
    face = get_person_cover_face(person_id)
    if face is None:
        raise HTTPException(status_code=404, detail="Person not found or has no faces")

    source = Path(face["path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source file not found on disk")

    thumb = get_or_create_face_thumbnail(
        face["id"], source, face["x"], face["y"], face["width"], face["height"]
    )
    if thumb is None:
        raise HTTPException(status_code=404, detail="Could not generate face thumbnail")

    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/people/{person_id}/files", tags=["people"])
async def get_person_files(
    person_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    date_from: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD), inclusive lower bound."),
    date_to: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD), inclusive upper bound."),
):
    """List every media file containing this person, newest first — powers the person detail view. Optionally scoped to a date range via date_from/date_to."""
    person = get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found")

    files = get_files_for_person(person_id, limit=limit, offset=offset, date_from=date_from, date_to=date_to)
    total = count_files_for_person(person_id, date_from=date_from, date_to=date_to)
    return {
        "person": {
            "id": person["id"],
            "name": person["name"],
            "display_name": person["name"] or f"Unknown Person #{person['id']}",
        },
        "total": total,
        "limit": limit,
        "offset": offset,
        "date_from": date_from,
        "date_to": date_to,
        "files": files,
    }


class PersonRenameRequest(BaseModel):
    name: str


@app.patch("/people/{person_id}", tags=["people"])
async def rename_person(person_id: int, body: PersonRenameRequest):
    """Set or update a person's name."""
    person = get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    set_person_name(person_id, name)
    return {"id": person_id, "name": name}


class MergePeopleRequest(BaseModel):
    loser_ids: list[int]


@app.post("/people/{person_id}/merge", tags=["people"])
async def merge_people_endpoint(person_id: int, body: MergePeopleRequest):
    """
    Merge one or more other people into this person (the keeper) —
    every face currently assigned to any loser_id is reassigned to
    person_id, and the loser person records are deleted. See
    database.merge_people() for full semantics — notably, the keeper's
    own name is always left untouched, so merging an unnamed cluster
    into an already-named one (rather than the other way around) is
    what keeps the name.

    404s if the keeper doesn't exist. loser_ids that don't exist (or
    happen to equal person_id) are silently ignored rather than
    raising, matching merge_people()'s own tolerance for that — there's
    no partial-failure state here worth surfacing to the caller.
    """
    person = get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found")

    if not body.loser_ids:
        raise HTTPException(status_code=400, detail="loser_ids cannot be empty")

    reassigned = merge_people(person_id, body.loser_ids)
    return {"keeper_id": person_id, "reassigned": reassigned}


def _parse_csv_param(raw: Optional[str]) -> Optional[list[str]]:
    """
    Split a comma-separated query param into a list of trimmed, non-empty
    values. Returns None if raw is None or entirely empty/whitespace, so
    call sites can pass the result straight through to search_media()'s
    Optional[list[str]] params with no extra "is this actually empty"
    check needed at each call site.
    """
    if not raw:
        return None
    values = [v.strip() for v in raw.split(",") if v.strip()]
    return values or None


@app.get("/search", tags=["search"])
async def search(
    q: str = Query(
        "",
        description=(
            "Free-text search — any combination of keywords/phrase, month, "
            "season, year, city, state, country, or person name(s) in a "
            "single string (e.g. 'birthday Paris summer 2019', 'Patrick "
            "and Tamika', 'Patrick NOT Owen'). Empty returns every file, "
            "newest first."
        ),
    ),
    media_type: Optional[str] = Query(None, description="Filter by type: image or video"),
    video_resolution: Optional[str] = Query(
        None,
        description=(
            "Comma-separated video resolution tiers, only meaningful when "
            "browsing video: '4k', '1080p', '720p', 'sd'. Multiple values "
            "are OR'd together. Supplying this forces video-only results "
            "even if media_type isn't set to 'video'."
        ),
    ),
    video_length: Optional[str] = Query(
        None,
        description=(
            "Comma-separated video length categories, only meaningful when "
            "browsing video: 'live_photo', 'short_clip', 'clip', "
            "'long_video'. Multiple values are OR'd together. If both "
            "video_resolution and video_length are given, they're AND'd "
            "together (e.g. '1080p,4k' + 'short_clip' means (1080p OR 4K) "
            "AND short clip). Supplying this forces video-only results "
            "even if media_type isn't set to 'video'."
        ),
    ),
    date_from: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD), inclusive lower bound."),
    date_to: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD), inclusive upper bound."),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Unified search — the single entry point for browsing the library.
    Parses q into date pieces (year/month/season), recognized person
    name(s) (including "NOT <name>" exclusions), plus leftover free
    text via query_parser.parse_query(), then matches on all of it: a
    date filter (season resolved per-file by hemisphere), a person
    filter (AND across included names, NOT across excluded ones — see
    database._build_person_clause()), a text match against
    caption/city/state/country, or any combination. An empty q with no
    media_type returns the entire library, newest first — this is what
    the frontend calls on load to show everything before any search
    has been typed, rather than requiring a query to see anything.

    Person names are recognized against the current roster of named
    people (database.get_named_people()) — fetched fresh on every
    request rather than cached, so a name becomes searchable
    immediately after PATCH /people/{id} without needing an API
    restart. Unnamed "Unknown Person #N" clusters aren't searchable by
    name for the obvious reason: there's no name text to type.

    video_resolution/video_length are additional optional sub-filters,
    only meaningful for video results — see _build_video_filter_clause()
    in database.py for the exact bucket boundaries (they mirror
    resolutionTier()/lengthCategory() in App.jsx) and how the two facets
    combine. Each is passed as a comma-separated string rather than a
    repeated query key / array param, to sidestep uncertainty about how
    the frontend's axios version serializes array params.

    date_from/date_to are an independent, explicit date-range filter
    (e.g. from a date-picker UI), separate from and AND'd with any
    year/month/season parsed out of q itself — see
    database._build_date_range_clause().
    """
    named_people = get_named_people()
    known_person_names = [p["name"] for p in named_people]

    parsed = parse_query(q, known_person_names=known_person_names)
    video_resolutions = _parse_csv_param(video_resolution)
    video_lengths = _parse_csv_param(video_length)

    files = search_media(
        parsed,
        media_type=media_type,
        video_lengths=video_lengths,
        video_resolutions=video_resolutions,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    total = count_media_search(
        parsed,
        media_type=media_type,
        video_lengths=video_lengths,
        video_resolutions=video_resolutions,
        date_from=date_from,
        date_to=date_to,
    )

    # Attach named people to each result in one batched query, rather
    # than one extra request per visible card — see
    # get_named_people_for_files() for why unnamed clusters are
    # excluded here.
    people_by_file = get_named_people_for_files([f["id"] for f in files])
    for f in files:
        f["people"] = people_by_file.get(f["id"], [])

    return {
        "query": q,
        "total": total,
        "limit": limit,
        "offset": offset,
        "video_resolution": video_resolution,
        "video_length": video_length,
        "date_from": date_from,
        "date_to": date_to,
        "matched_people": parsed.person_names,
        "excluded_people": parsed.excluded_person_names,
        "files": files,
    }