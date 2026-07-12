"""
FamilyVault Media Scanner
Walks a directory tree and identifies supported media files.
Usage: from familyvault.scanner import scan
"""

from dataclasses import dataclass, field
from pathlib import Path

from familyvault.config import (
    SUPPORTED_EXTENSIONS,
    SCAN_BATCH_SIZE,
    SCAN_FOLLOW_SYMLINKS,
    SCAN_SKIP_HIDDEN,
)
from familyvault.logger import get_logger

log = get_logger(__name__)


# ── Data Classes ───────────────────────────────────────────────────────────────

@dataclass
class MediaFile:
    """Represents a single discovered media file."""
    path: Path
    extension: str
    size_bytes: int

    @property
    def is_image(self) -> bool:
        from familyvault.config import IMAGE_EXTENSIONS
        return self.extension in IMAGE_EXTENSIONS

    @property
    def is_video(self) -> bool:
        from familyvault.config import VIDEO_EXTENSIONS
        return self.extension in VIDEO_EXTENSIONS


@dataclass
class ScanResult:
    """Summary of a completed scan."""
    root: Path
    media_files: list[MediaFile] = field(default_factory=list)
    skipped_count: int = 0
    error_count: int = 0

    @property
    def total_count(self) -> int:
        return len(self.media_files)

    @property
    def image_count(self) -> int:
        return sum(1 for f in self.media_files if f.is_image)

    @property
    def video_count(self) -> int:
        return sum(1 for f in self.media_files if f.is_video)

    @property
    def total_size_bytes(self) -> int:
        return sum(f.size_bytes for f in self.media_files)

    def summary(self) -> str:
        mb = self.total_size_bytes / (1024 * 1024)
        return (
            f"Scan complete — {self.total_count} media files found "
            f"({self.image_count} images, {self.video_count} videos, "
            f"{mb:.1f} MB) | "
            f"skipped: {self.skipped_count} | errors: {self.error_count}"
        )


# ── Scanner ────────────────────────────────────────────────────────────────────

def _is_hidden(path: Path) -> bool:
    """Return True if any part of the path is a hidden file or folder."""
    return any(part.startswith(".") for part in path.parts)


def scan(root: Path) -> ScanResult:
    """
    Recursively scan root for supported media files.

    Args:
        root: Directory to scan.

    Returns:
        ScanResult containing all discovered MediaFile objects and counts.

    Raises:
        NotADirectoryError: If root does not exist or is not a directory.
    """
    if not root.exists():
        raise NotADirectoryError(f"Path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {root}")

    log.info(f"Starting scan: {root}")
    result = ScanResult(root=root)
    batch: list[MediaFile] = []

    for entry in root.rglob("*"):
        # Skip symlinks if configured
        if not SCAN_FOLLOW_SYMLINKS and entry.is_symlink():
            result.skipped_count += 1
            log.debug(f"Skipped symlink: {entry}")
            continue

        # Skip hidden files and folders
        if SCAN_SKIP_HIDDEN and _is_hidden(entry.relative_to(root)):
            result.skipped_count += 1
            log.debug(f"Skipped hidden: {entry}")
            continue

        # Skip directories
        if not entry.is_file():
            continue

        # Skip unsupported extensions
        ext = entry.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            result.skipped_count += 1
            continue

        # Collect media file
        try:
            size = entry.stat().st_size
            media_file = MediaFile(path=entry, extension=ext, size_bytes=size)
            batch.append(media_file)

            if len(batch) >= SCAN_BATCH_SIZE:
                result.media_files.extend(batch)
                log.debug(f"Batch of {len(batch)} files collected")
                batch.clear()

        except OSError as e:
            result.error_count += 1
            log.warning(f"Could not read file {entry}: {e}")

    # Flush remaining batch
    if batch:
        result.media_files.extend(batch)
        log.debug(f"Final batch of {len(batch)} files collected")

    log.info(result.summary())
    return result