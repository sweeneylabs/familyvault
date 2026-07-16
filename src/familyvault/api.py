"""
FamilyVault FastAPI Backend
Provides a REST API for accessing the FamilyVault library.
Run with: uvicorn familyvault.api:app --reload --host 0.0.0.0
"""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from familyvault.database import (
    init_db,
    get_all_scans,
    get_scan_files,
    get_file_count,
    search_by_caption,
    count_search_results,
)
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
    version="0.5.0",
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


@app.get("/search", tags=["search"])
async def search(
    q: str = Query(..., min_length=1, description="Search text, matched against captions"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    files = search_by_caption(q, limit=limit, offset=offset)
    total = count_search_results(q)
    return {
        "query": q,
        "total": total,
        "limit": limit,
        "offset": offset,
        "files": files,
    }
