"""
FamilyVault AI Captioner
Generates natural language descriptions of images using Claude vision.
"""

from __future__ import annotations

import anthropic
import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from familyvault.config import IMAGE_EXTENSIONS
from familyvault.logger import get_logger

log = get_logger(__name__)

CAPTION_MODEL = "claude-haiku-4-5-20251001"
CAPTION_MAX_TOKENS = 256
CAPTION_PROMPT = (
    "Describe this photo in one or two concise sentences. "
    "Focus on the main subject, people, setting, and mood. "
    "Do not begin with phrases like This image shows or The photo depicts. "
    "Write naturally, as if describing a memory."
)

SUPPORTED_VISION_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@dataclass
class CaptionResult:
    path: Path
    caption: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.caption is not None and self.error is None


def _encode_image(path: Path) -> tuple[str, str]:
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(path.suffix.lower(), "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return data, media_type


def caption_image(path: Path) -> CaptionResult:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return CaptionResult(path=path, error="Unsupported file type")

    if path.suffix.lower() not in SUPPORTED_VISION_FORMATS:
        return CaptionResult(path=path, error=f"Format {path.suffix} not supported for vision")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return CaptionResult(path=path, error="ANTHROPIC_API_KEY not set")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        image_data, media_type = _encode_image(path)

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
        log.debug(f"Caption generated for {path.name}: {caption[:60]}...")
        return CaptionResult(path=path, caption=caption)

    except Exception as e:
        log.warning(f"Caption failed for {path.name}: {e}")
        return CaptionResult(path=path, error=str(e))


def caption_batch(paths: list[Path], max_images: int = 10) -> list[CaptionResult]:
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