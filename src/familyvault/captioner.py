"""
FamilyVault AI Captioner
Generates natural language descriptions of images using Claude vision.
Videos are captioned from a representative frame (reusing the existing
thumbnail frame extraction), since Claude's vision API accepts images only.
"""

from __future__ import annotations

import anthropic
import base64
import io
import os
import pillow_heif
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from familyvault.config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from familyvault.logger import get_logger
from familyvault.thumbnailer import generate_thumbnail

log = get_logger(__name__)

# Registers HEIC/HEIF support with Pillow so Image.open() can read them
# directly, the same way it already reads jpg/png/etc.
pillow_heif.register_heif_opener()

CAPTION_MODEL = "claude-haiku-4-5-20251001"
CAPTION_MAX_TOKENS = 256
CAPTION_PROMPT = (
    "Describe this photo in one or two concise sentences. "
    "Focus on the main subject, people, setting, and mood. "
    "Do not begin with phrases like This image shows or The photo depicts. "
    "Write naturally, as if describing a memory."
)

# Formats Claude's vision API accepts natively.
NATIVE_VISION_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Formats we convert to JPEG in memory before sending, since the API
# doesn't accept them directly.
HEIC_EXTENSIONS = {".heic", ".heif"}

SUPPORTED_VISION_FORMATS = NATIVE_VISION_FORMATS | HEIC_EXTENSIONS


@dataclass
class CaptionResult:
    path: Path
    caption: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.caption is not None and self.error is None


def _encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()

    if suffix in HEIC_EXTENSIONS:
        # Convert HEIC/HEIF to JPEG entirely in memory. Nothing is written
        # to disk — the original file on the library drive is never touched.
        with Image.open(path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=90)
            data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
        return data, "image/jpeg"

    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def _request_caption(image_data: str, media_type: str, result_path: Path) -> CaptionResult:
    """
    Send already-encoded image bytes to Claude vision and return a
    CaptionResult attributed to result_path (which may be a video's
    original path, even though the bytes came from an extracted frame).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return CaptionResult(path=result_path, error="ANTHROPIC_API_KEY not set")

    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=CAPTION_MODEL,
            max_tokens=CAPTION_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": CAPTION_PROMPT,
                        },
                    ],
                }
            ],
        )

        caption = message.content[0].text.strip()
        log.debug(f"Caption generated for {result_path.name}: {caption[:60]}...")
        return CaptionResult(path=result_path, caption=caption)

    except Exception as e:
        log.warning(f"Caption failed for {result_path.name}: {e}")
        return CaptionResult(path=result_path, error=str(e))


def caption_image(path: Path) -> CaptionResult:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return CaptionResult(path=path, error="Unsupported file type")

    if path.suffix.lower() not in SUPPORTED_VISION_FORMATS:
        return CaptionResult(path=path, error=f"Format {path.suffix} not supported for vision")

    image_data, media_type = _encode_image(path)
    return _request_caption(image_data, media_type, path)


def caption_video(path: Path) -> CaptionResult:
    """
    Caption a video by extracting a representative frame (via the existing
    thumbnail pipeline, which uses ffmpeg) and captioning that frame.

    The returned CaptionResult.path is the original video's path, not the
    extracted frame, so results can be matched back to the video record.
    """
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return CaptionResult(path=path, error="Unsupported file type")

    frame = generate_thumbnail(path)
    if frame is None:
        return CaptionResult(path=path, error="Could not extract a video frame")

    image_data, media_type = _encode_image(frame)
    return _request_caption(image_data, media_type, path)


def caption_media(path: Path) -> CaptionResult:
    """Caption an image or video, dispatching based on file extension."""
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return caption_video(path)
    return caption_image(path)


def caption_batch(paths: list[Path], max_images: int = 10) -> list[CaptionResult]:
    """Caption a batch of images only (unchanged from earlier versions)."""
    image_paths = [p for p in paths if p.suffix.lower() in SUPPORTED_VISION_FORMATS]
    limited = image_paths[:max_images]

    log.info(f"Captioning {len(limited)} images (of {len(paths)} provided)")
    results = []
    for path in limited:
        result = caption_image(path)
        results.append(result)
        if result.success:
            log.info(f"{path.name}: {result.caption[:80]}")
        else:
            log.warning(f"{path.name}: {result.error}")

    return results


def caption_media_batch(paths: list[Path], max_items: int = 10) -> list[CaptionResult]:
    """Caption a batch of images and/or videos, dispatching per file."""
    supported = SUPPORTED_VISION_FORMATS | VIDEO_EXTENSIONS
    media_paths = [p for p in paths if p.suffix.lower() in supported]
    limited = media_paths[:max_items]

    log.info(f"Captioning {len(limited)} media files (of {len(paths)} provided)")
    results = []
    for path in limited:
        result = caption_media(path)
        results.append(result)
        if result.success:
            log.info(f"{path.name}: {result.caption[:80]}")
        else:
            log.warning(f"{path.name}: {result.error}")

    return results
