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
import pillow_heif
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
    PREVIEW_DIR,
    PREVIEW_QUALITY,
)
from familyvault.logger import get_logger

log = get_logger(__name__)
pillow_heif.register_heif_opener()

# Registers HEIC/HEIF support with Pillow so Image.open() can read them
# directly — the same registration captioner.py and metadata.py already
# do. Without this, PIL can't open .heic/.heif files at all, and every
# thumbnail attempt for one fails silently inside the try/except below.

# Lets Pillow load an image even if the file ends a few bytes before the
# expected end-of-image marker, rather than refusing outright — see the
# matching setting (and its tradeoff) explained in captioner.py.
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True


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


# ── Preview Path ───────────────────────────────────────────────────────────────

def preview_path(source: Path) -> Path:
    """
    Derive a unique full-resolution preview path from the source file
    path. Same hashing scheme as thumbnail_path() (SHA1, flat two-level
    directory), but stored under PREVIEW_DIR instead of THUMBNAIL_DIR —
    the two are entirely separate caches, so reusing the same hash
    scheme causes no collision between a file's thumbnail and its
    preview.

    Example:
        source: /Volumes/Drive/Photos/IMG_001.HEIC
        result: previews/3a/3a8f...d2.jpg
    """
    digest = hashlib.sha1(str(source).encode()).hexdigest()
    return PREVIEW_DIR / digest[:2] / f"{digest}.jpg"


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


# ── Full-Resolution Previews ───────────────────────────────────────────────────

def generate_preview(source: Path) -> Optional[Path]:
    """
    Generate a full-resolution JPEG preview for an image format browsers
    can't render inline (see config.NON_BROWSER_SAFE_IMAGE_EXTENSIONS —
    currently HEIC/HEIF and TIFF). Used by the /files/{id}/media
    endpoint for the lightbox view: streaming the original bytes of
    these formats into an <img> tag silently fails to render client-side
    even though the file itself streams successfully, since most
    browsers have no built-in decoder for them.

    Unlike generate_thumbnail(), this does no resizing — the point is
    to preserve full resolution for viewing, only the file format
    changes. Results are cached on disk the same way thumbnails are, so
    repeat views (e.g. navigating back to a photo already seen) don't
    reconvert.

    This function assumes the caller has already checked that source's
    extension actually needs conversion — it doesn't check
    NON_BROWSER_SAFE_IMAGE_EXTENSIONS itself, since some callers (e.g.
    a future batch pre-warming command) may want to generate previews
    unconditionally for a known list of files.

    Args:
        source: Path to the source image file.

    Returns:
        Path to the generated preview JPEG, or None if generation
        failed (e.g. corrupt file, unsupported format Pillow can't
        open).
    """
    dest = preview_path(source)

    # Return cached preview if it already exists
    if dest.exists():
        log.debug(f"Preview already exists: {dest.name}")
        return dest

    try:
        from PIL import Image, ImageOps

        dest.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(source) as img:
            # Normalise orientation from EXIF — same as thumbnails
            img = ImageOps.exif_transpose(img)

            # Convert to RGB — handles RGBA, palette, and other modes
            if img.mode != "RGB":
                img = img.convert("RGB")

            # No resizing — full resolution, format conversion only
            img.save(dest, format="JPEG", quality=PREVIEW_QUALITY)

        log.debug(f"Preview generated: {source.name} → {dest.name}")
        return dest

    except Exception as e:
        log.warning(f"Could not generate preview for {source.name}: {e}")
        return None


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
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            # ffmpeg's stderr is often a verbose codec/stream dump; the
            # actual error is almost always in the last few lines, so
            # only the tail is logged to keep this readable.
            reason = stderr[-500:] if stderr else "(no stderr captured)"
            log.warning(f"ffmpeg failed for {source.name} (exit {result.returncode}): {reason}")
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