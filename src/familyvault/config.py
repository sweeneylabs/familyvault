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

# ── Scanner Settings ───────────────────────────────────────────────────────────
SCAN_BATCH_SIZE      = 100    # Files processed per batch
SCAN_FOLLOW_SYMLINKS = False  # Never follow symlinks — safety first
SCAN_SKIP_HIDDEN     = True   # Skip dot-files and dot-folders