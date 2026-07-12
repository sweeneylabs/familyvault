"""
FamilyVault Thumbnail Generator
Generates JPEG thumbnails for images and videos.
Thumbnails are stored in the thumbnails/ directory under a hashed path.
Original files are never modified.
"""

from __future__ import annotations

import hashlib
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from familyvault.config import (
    THUMBNAIL_DIR,
    THUMBNAIL_SIZE,
    THUMBNAIL_QUALITY,
    THUMBNAIL_FORMAT,
    VIDEO_FRAME_OFFSET,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from familyvault.logger import get_logger

log = get_logger(__name__)


# ── Thumbnail Path ─────────────────────────────────────────────────────────────

def thumbnail_path(source: Path) -> Path:
    """
    Derive a unique thumbnail path from the source file path.
    Uses a SHA1 hash to avoid collisions and keep the directory flat.

    Example:
        source: /Volumes/Drive/Photos/IMG_001.jpg
        result: thumbnails/3a/3a8f...d2.jpg
    """
    digest = hashlib.sha1(str(source).encode()).hexdigest()
    return THUMBNAIL_DIR / digest[:2] / f"{digest}.jpg"


# ── Image Thumbnails ───────────────────────────────────────────────────────────

def _generate_image_thumbnail(source: Path, dest: Path) -> bool:
    """Generate a thumbnail for an image file using Pillow."""
    try:
        from PIL import Image, ImageOps

        dest.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(source) as img:
            # Normalise orientation from EXIF before resizing
            img = ImageOps.exif_transpose(img)

            # Convert to RGB — handles RGBA, palette, and other modes
            if img.mode != "RGB":
                img = img.convert("RGB")

            img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
            img.save(dest, format=THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY)

        log.debug(f"Image thumbnail: {source.name} → {dest.name}")
        return True

    except Exception as e:
        log.warning(f"Could not generate image thumbnail for {source.name}: {e}")
        return False


# ── Video Thumbnails ───────────────────────────────────────────────────────────

def _get_video_duration(source: Path) -> Optional[float]:
    """Return video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _generate_video_thumbnail(source: Path, dest: Path) -> bool:
    """Extract a frame from a video and save it as a JPEG thumbnail."""
    try:
        if not shutil.which("ffmpeg"):
            log.warning("ffmpeg not found — skipping video thumbnail")
            return False

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Determine seek position
        duration = _get_video_duration(source)
        seek = round(duration * VIDEO_FRAME_OFFSET, 2) if duration else 0

        # Extract frame with ffmpeg
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(seek),
                "-i", str(source),
                "-vframes", "1",
                "-vf", f"scale={THUMBNAIL_SIZE[0]}:{THUMBNAIL_SIZE[1]}:force_original_aspect_ratio=decrease",
                "-q:v", "2",
                str(dest),
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0 or not dest.exists():
            log.warning(f"ffmpeg failed for {source.name}")
            return False

        log.debug(f"Video thumbnail: {source.name} → {dest.name}")
        return True

    except Exception as e:
        log.warning(f"Could not generate video thumbnail for {source.name}: {e}")
        return False


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_thumbnail(source: Path) -> Optional[Path]:
    """
    Generate a thumbnail for an image or video file.

    Args:
        source: Path to the source media file.

    Returns:
        Path to the generated thumbnail, or None if generation failed
        or the file type is not supported.
    """
    ext = source.suffix.lower()
    dest = thumbnail_path(source)

    # Return cached thumbnail if it already exists
    if dest.exists():
        log.debug(f"Thumbnail already exists: {dest.name}")
        return dest

    if ext in IMAGE_EXTENSIONS:
        success = _generate_image_thumbnail(source, dest)
    elif ext in VIDEO_EXTENSIONS:
        success = _generate_video_thumbnail(source, dest)
    else:
        log.debug(f"Unsupported extension for thumbnailing: {ext}")
        return None

    return dest if success else None