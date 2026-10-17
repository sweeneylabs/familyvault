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

from PIL import Image, ImageFile, UnidentifiedImageError

from familyvault.config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from familyvault.logger import get_logger
from familyvault.thumbnailer import generate_thumbnail

log = get_logger(__name__)

# Registers HEIC/HEIF support with Pillow so Image.open() can read them
# directly, the same way it already reads jpg/png/etc.
pillow_heif.register_heif_opener()

# By default, Pillow refuses to load an image if the file ends before
# the expected end-of-image marker — even if only a handful of bytes
# are missing off the very end, well past where the actual pixel data
# was already fully written (a common result of an interrupted copy or
# transfer). This makes Pillow do its best with what's there instead of
# refusing outright. Tradeoff: for a file missing a large chunk of data
# (not just a trailing few bytes), this can produce a partial/garbled
# image rather than an error — which would get captioned as if it were
# a normal photo, with no failure signal. Acceptable here since a
# caption is a soft, low-stakes description, not something safety- or
# accuracy-critical.
ImageFile.LOAD_TRUNCATED_IMAGES = True

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

# Anthropic's documented long-edge resize threshold: images larger than
# this get downscaled server-side anyway, so resizing here first loses
# no detail Claude would actually use, while substantially cutting
# payload size (and, incidentally, cost — see
# https://docs.claude.com/en/docs/build-with-claude/vision). This also
# reliably keeps images well under the API's 10MB base64 payload limit;
# a 1568px-long-edge JPEG at quality 90 is nowhere close to 10MB even
# for a very detailed photo, so no additional size-checking loop is needed.
_MAX_DIMENSION = 1568
_JPEG_QUALITY = 90


@dataclass
class CaptionResult:
    path: Path
    caption: Optional[str] = None
    error: Optional[str] = None
    # True only for failures known to be unrecoverable -- retrying will
    # never help (e.g. the file isn't a recognizable image format at
    # all). Used by `caption --auto` to decide whether to call
    # database.mark_file_skipped() automatically rather than leaving
    # the file to be retried by every future run. Defaults to False
    # (transient / unknown) -- see caption_image()/caption_video() for
    # exactly which failure sites set this True, and why video frame
    # extraction failures deliberately never do.
    permanent: bool = False

    @property
    def success(self) -> bool:
        return self.caption is not None and self.error is None


def _encode_image(path: Path) -> tuple[str, str]:
    """
    Load an image file and return (base64_data, media_type) ready to
    send to Claude's vision API.

    Every image — regardless of source format — is decoded through
    Pillow, normalized to RGB, downscaled if needed, and re-encoded as
    a clean JPEG. This isn't just for HEIC (which Pillow can't read at
    all without the register_heif_opener() call above): it also guards
    against two real failure modes seen across a library spanning many
    cameras, phones, and scanners over the years:

      - Nonstandard or subtly malformed JPEGs that the API rejects
        outright with an opaque "Could not process image" error, even
        though the file opens and displays fine locally (odd color
        profiles, unusual JFIF variants, etc.). Round-tripping through
        Pillow either produces a clean, standard JPEG the API accepts,
        or raises a clear local exception instead of an opaque remote
        one — either way, a real diagnosis instead of a dead end.
      - Large images (10MB+, common from modern phone cameras)
        exceeding the vision API's base64 payload limit outright.

    Raises whatever exception Pillow raises if the file can't be opened
    or processed at all — callers are expected to catch this themselves
    and turn it into a CaptionResult error rather than letting a single
    bad file crash an entire batch run.

    Args:
        path: Path to the source image (or an extracted video frame).

    Returns:
        (base64_data, media_type) — media_type is always "image/jpeg",
        since every image is re-encoded as JPEG regardless of its
        original format.
    """
    with Image.open(path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.size) > _MAX_DIMENSION:
            img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
        data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    return data, "image/jpeg"


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
        return CaptionResult(path=path, error="Unsupported file type", permanent=True)

    if path.suffix.lower() not in SUPPORTED_VISION_FORMATS:
        return CaptionResult(path=path, error=f"Format {path.suffix} not supported for vision", permanent=True)

    try:
        image_data, media_type = _encode_image(path)
    except UnidentifiedImageError as e:
        # Pillow couldn't recognize this as image data in any format at
        # all -- not a truncation or size issue, something more
        # fundamental (corrupt beyond repair, or not actually an image
        # despite the extension -- e.g. a mislabeled video file). No
        # amount of retrying changes that.
        log.warning(f"Not a recognizable image file {path.name}: {e}")
        return CaptionResult(path=path, error=f"Not a recognizable image file: {e}", permanent=True)
    except Exception as e:
        # Anything else (OSError from a flaky external drive, etc.) is
        # left as transient/unknown by default -- safer to retry an
        # extra time than to permanently write off a file that might
        # just have hit a bad moment.
        log.warning(f"Could not read/prepare image {path.name}: {e}")
        return CaptionResult(path=path, error=f"Could not read/prepare image: {e}")

    return _request_caption(image_data, media_type, path)


def caption_video(path: Path) -> CaptionResult:
    """
    Caption a video by extracting a representative frame (via the existing
    thumbnail pipeline, which uses ffmpeg) and captioning that frame.

    The returned CaptionResult.path is the original video's path, not the
    extracted frame, so results can be matched back to the video record.
    """
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return CaptionResult(path=path, error="Unsupported file type", permanent=True)

    frame = generate_thumbnail(path)
    if frame is None:
        # Deliberately NOT marked permanent. "Could not extract a video
        # frame" covers both genuine, unrecoverable file corruption
        # (e.g. a missing moov atom) and causes that could plausibly be
        # transient (an external drive momentarily unresponsive, an
        # ffmpeg timeout under system load). generate_thumbnail() only
        # returns None/not-None today -- it doesn't yet surface which
        # of those happened, even though thumbnailer.py logs the real
        # ffmpeg reason. Without that detail here, auto-marking these
        # permanent risks writing off a video that would succeed on a
        # later retry -- so these are always left for manual review via
        # `familyvault skip-file`, using the reason from the log line.
        return CaptionResult(path=path, error="Could not extract a video frame")

    try:
        image_data, media_type = _encode_image(frame)
    except UnidentifiedImageError as e:
        log.warning(f"Not a recognizable image file (extracted frame) for {path.name}: {e}")
        return CaptionResult(path=path, error=f"Not a recognizable image file: {e}", permanent=True)
    except Exception as e:
        log.warning(f"Could not read/prepare extracted frame for {path.name}: {e}")
        return CaptionResult(path=path, error=f"Could not read/prepare video frame: {e}")

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