"""
FamilyVault Metadata Extraction
Extracts EXIF data from images and technical metadata from videos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from familyvault.config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from familyvault.logger import get_logger

log = get_logger(__name__)


# ── Data Class ─────────────────────────────────────────────────────────────────

@dataclass
class MediaMetadata:
    """Metadata extracted from a single media file."""
    path: Path

    # Shared
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None

    # Image EXIF
    taken_at: Optional[str] = None        # ISO 8601 string e.g. "2023-06-15T14:30:00"
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None

    # Video
    codec: Optional[str] = None
    frame_rate: Optional[float] = None
    bit_rate: Optional[int] = None

    @property
    def has_gps(self) -> bool:
        return self.gps_lat is not None and self.gps_lon is not None

    @property
    def has_datetime(self) -> bool:
        return self.taken_at is not None

    @property
    def has_dimensions(self) -> bool:
        return self.width is not None and self.height is not None

    @property
    def megapixels(self) -> Optional[float]:
        if self.has_dimensions:
            return round((self.width * self.height) / 1_000_000, 1)
        return None


# ── GPS Helpers ────────────────────────────────────────────────────────────────

def _to_decimal(values) -> Optional[float]:
    """Convert an EXIF GPS rational tuple (degrees, minutes, seconds) to decimal degrees."""
    try:
        d, m, s = values
        return float(d) + float(m) / 60 + float(s) / 3600
    except Exception:
        return None


def _extract_gps(exif_data: dict) -> tuple[Optional[float], Optional[float]]:
    """Extract GPS latitude and longitude from raw EXIF data."""
    try:
        from PIL.ExifTags import TAGS, GPSTAGS

        gps_tag_id = next(
            (k for k, v in TAGS.items() if v == "GPSInfo"), None
        )
        if gps_tag_id is None or gps_tag_id not in exif_data:
            return None, None

        gps_info = {
            GPSTAGS.get(k, k): v
            for k, v in exif_data[gps_tag_id].items()
        }

        lat = _to_decimal(gps_info.get("GPSLatitude"))
        lon = _to_decimal(gps_info.get("GPSLongitude"))

        if lat is None or lon is None:
            return None, None

        if gps_info.get("GPSLatitudeRef") == "S":
            lat = -lat
        if gps_info.get("GPSLongitudeRef") == "W":
            lon = -lon

        return round(lat, 6), round(lon, 6)

    except Exception:
        return None, None


# ── Datetime Helper ────────────────────────────────────────────────────────────

def _parse_exif_datetime(raw: str) -> Optional[str]:
    """Convert EXIF datetime string '2023:06:15 14:30:00' to ISO 8601."""
    try:
        from datetime import datetime
        dt = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
        return dt.isoformat()
    except Exception:
        return None


# ── Extractors ─────────────────────────────────────────────────────────────────

def _extract_image_metadata(path: Path) -> MediaMetadata:
    """Extract metadata from an image file using Pillow."""
    from PIL import Image
    from PIL.ExifTags import TAGS

    meta = MediaMetadata(path=path)

    try:
        with Image.open(path) as img:
            meta.width, meta.height = img.size

            raw_exif = img._getexif()
            if raw_exif is None:
                return meta

            exif = {TAGS.get(k, k): v for k, v in raw_exif.items()}

            # Datetime
            for field in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                if field in exif:
                    meta.taken_at = _parse_exif_datetime(str(exif[field]))
                    if meta.taken_at:
                        break

            # Camera
            meta.camera_make = str(exif["Make"]).strip() if "Make" in exif else None
            meta.camera_model = str(exif["Model"]).strip() if "Model" in exif else None

            # GPS
            meta.gps_lat, meta.gps_lon = _extract_gps(raw_exif)

    except Exception as e:
        log.warning(f"Could not extract image metadata from {path.name}: {e}")

    return meta


def _extract_video_metadata(path: Path) -> MediaMetadata:
    """Extract metadata from a video file using pymediainfo."""
    from pymediainfo import MediaInfo

    meta = MediaMetadata(path=path)

    try:
        info = MediaInfo.parse(path)

        for track in info.tracks:
            if track.track_type == "Video":
                meta.width = int(track.width) if track.width else None
                meta.height = int(track.height) if track.height else None
                meta.codec = track.codec_id or track.format or None
                try:
                    meta.frame_rate = float(track.frame_rate) if track.frame_rate else None
                except (ValueError, TypeError):
                    meta.frame_rate = None

            if track.track_type == "General":
                try:
                    duration_ms = float(track.duration) if track.duration else None
                    meta.duration_seconds = round(duration_ms / 1000, 2) if duration_ms else None
                except (ValueError, TypeError):
                    meta.duration_seconds = None
                try:
                    meta.bit_rate = int(track.overall_bit_rate) if track.overall_bit_rate else None
                except (ValueError, TypeError):
                    meta.bit_rate = None

    except Exception as e:
        log.warning(f"Could not extract video metadata from {path.name}: {e}")

    return meta


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_metadata(path: Path) -> Optional[MediaMetadata]:
    """
    Extract metadata from an image or video file.

    Args:
        path: Path to the media file.

    Returns:
        MediaMetadata if the file type is supported, None otherwise.
    """
    ext = path.suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        return _extract_image_metadata(path)
    elif ext in VIDEO_EXTENSIONS:
        return _extract_video_metadata(path)
    else:
        log.debug(f"Unsupported extension for metadata extraction: {ext}")
        return None