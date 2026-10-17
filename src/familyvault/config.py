"""
FamilyVault Configuration
Centralised settings for paths, supported media types, and scanner behaviour.
"""

from pathlib import Path

# ── Project Root ───────────────────────────────────────────────────────────────
# Resolves to the familyvault/ project root regardless of where code is run from.
# src/familyvault/config.py → .parent = familyvault/ → .parent = src/ → .parent = project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Storage Paths ──────────────────────────────────────────────────────────────
DATABASE_DIR  = PROJECT_ROOT / "database"
DATABASE_PATH = DATABASE_DIR / "familyvault.db"
THUMBNAIL_DIR = PROJECT_ROOT / "thumbnails"
PREVIEW_DIR   = PROJECT_ROOT / "previews"
FACE_THUMBNAIL_DIR = PROJECT_ROOT / "face_thumbnails"
LOG_DIR       = PROJECT_ROOT / "logs"

# ── Supported Media Types ──────────────────────────────────────────────────────
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw",
})

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".flv",
    ".webm", ".3gp", ".mts", ".m2ts",
})

SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# Image formats browsers can't decode in an <img> tag, even though
# Pillow can open and re-encode them fine. The /files/{id}/media
# endpoint converts these to a full-resolution JPEG preview on first
# request (see thumbnailer.generate_preview()) rather than streaming
# the original bytes, which would silently fail to render client-side.
# RAW formats (.raw/.cr2/.nef/.arw) are deliberately NOT included here:
# Pillow can't open them at all without an additional dependency
# (rawpy), so they're left streaming as the original file for now —
# same as before this fix.
NON_BROWSER_SAFE_IMAGE_EXTENSIONS = frozenset({
    ".heic", ".heif", ".tiff", ".tif",
})

# ── Scanner Settings ───────────────────────────────────────────────────────────
SCAN_BATCH_SIZE      = 100    # Files processed per batch
SCAN_FOLLOW_SYMLINKS = False  # Never follow symlinks — safety first
SCAN_SKIP_HIDDEN     = True   # Skip dot-files and dot-folders
# ── Thumbnail Settings ─────────────────────────────────────────────────────────
THUMBNAIL_SIZE     = (400, 400)   # Max width x height in pixels
THUMBNAIL_QUALITY  = 85           # JPEG quality (1-95)
THUMBNAIL_FORMAT   = "JPEG"
VIDEO_FRAME_OFFSET = 0.1          # Extract frame at 10% of video duration
# ── Preview Settings ───────────────────────────────────────────────────────────
# Used only for NON_BROWSER_SAFE_IMAGE_EXTENSIONS conversions in the
# lightbox — full resolution, no resizing, so quality is set higher
# than THUMBNAIL_QUALITY since this is the actual viewing experience,
# not a small preview grid image.
PREVIEW_QUALITY = 95              # JPEG quality (1-95)
# ── Duplicate Detection Settings ───────────────────────────────────────────────
DUPLICATE_HASH_SIZE    = 8     # Perceptual hash size (8 = 64-bit hash)
DUPLICATE_MAX_DISTANCE = 4     # Max hamming distance to consider a duplicate (0 = exact)