"""
FamilyVault Duplicate Detection
Detects exact and near-duplicate images using file hashing and perceptual hashing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from familyvault.config import (
    DUPLICATE_HASH_SIZE,
    DUPLICATE_MAX_DISTANCE,
    IMAGE_EXTENSIONS,
)
from familyvault.logger import get_logger

log = get_logger(__name__)


# ── Data Classes ───────────────────────────────────────────────────────────────

@dataclass
class DuplicateGroup:
    """A group of files that are duplicates of each other."""
    files: list[Path]
    similarity: str   # "exact" or "perceptual"

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def keeper(self) -> Path:
        """Return the file we'd suggest keeping — oldest by name, then path."""
        return sorted(self.files)[0]

    @property
    def duplicates(self) -> list[Path]:
        """Return all files except the suggested keeper."""
        return [f for f in sorted(self.files) if f != self.keeper]


@dataclass
class DuplicateReport:
    """Summary of a duplicate detection run."""
    scanned: int = 0
    groups: list[DuplicateGroup] = field(default_factory=list)
    errors: int = 0

    @property
    def total_groups(self) -> int:
        return len(self.groups)

    @property
    def total_duplicates(self) -> int:
        """Total number of redundant files (not counting keepers)."""
        return sum(g.count - 1 for g in self.groups)

    @property
    def exact_groups(self) -> list[DuplicateGroup]:
        return [g for g in self.groups if g.similarity == "exact"]

    @property
    def perceptual_groups(self) -> list[DuplicateGroup]:
        return [g for g in self.groups if g.similarity == "perceptual"]

    def summary(self) -> str:
        return (
            f"Duplicate scan complete — {self.scanned} files scanned | "
            f"{self.total_groups} duplicate groups found "
            f"({len(self.exact_groups)} exact, {len(self.perceptual_groups)} perceptual) | "
            f"{self.total_duplicates} redundant files | "
            f"{self.errors} errors"
        )


# ── Hashing ────────────────────────────────────────────────────────────────────

def file_hash(path: Path) -> Optional[str]:
    """
    Compute a SHA256 hash of the file contents.
    Used for exact duplicate detection.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        log.warning(f"Could not hash {path.name}: {e}")
        return None


def perceptual_hash(path: Path) -> Optional[object]:
    """
    Compute a perceptual hash (pHash) of an image.
    Used for near-duplicate detection — resistant to resize and recompression.
    """
    try:
        import imagehash
        from PIL import Image
        with Image.open(path) as img:
            return imagehash.phash(img, hash_size=DUPLICATE_HASH_SIZE)
    except Exception as e:
        log.warning(f"Could not compute perceptual hash for {path.name}: {e}")
        return None


# ── Detection ──────────────────────────────────────────────────────────────────

def find_duplicates(paths: list[Path]) -> DuplicateReport:
    """
    Scan a list of file paths for exact and perceptual duplicates.

    Strategy:
        1. Group files by SHA256 — these are byte-for-byte identical.
        2. For remaining image files, group by perceptual hash distance.

    Args:
        paths: List of media file paths to scan.

    Returns:
        DuplicateReport with all detected duplicate groups.
    """
    report = DuplicateReport(scanned=len(paths))

    if not paths:
        return report

    # ── Pass 1: Exact duplicates (all file types) ──────────────────────────────
    log.info(f"Pass 1: exact duplicate check on {len(paths)} files")
    exact_map: dict[str, list[Path]] = {}
    remaining: list[Path] = []

    for path in paths:
        digest = file_hash(path)
        if digest is None:
            report.errors += 1
            continue
        exact_map.setdefault(digest, []).append(path)

    exact_duplicates: set[str] = set()
    for digest, group in exact_map.items():
        if len(group) > 1:
            report.groups.append(DuplicateGroup(files=group, similarity="exact"))
            exact_duplicates.add(digest)
            log.debug(f"Exact duplicate group: {[p.name for p in group]}")
        else:
            remaining.extend(group)

    log.info(f"Pass 1 complete — {len(report.exact_groups)} exact groups found")

    # ── Pass 2: Perceptual duplicates (images only) ────────────────────────────
    images = [p for p in remaining if p.suffix.lower() in IMAGE_EXTENSIONS]
    log.info(f"Pass 2: perceptual duplicate check on {len(images)} images")

    hash_map: list[tuple[object, Path]] = []

    for path in images:
        phash = perceptual_hash(path)
        if phash is None:
            report.errors += 1
            continue
        hash_map.append((phash, path))

    # Compare each hash against all others — O(n²) but fine for typical libraries
    used: set[int] = set()
    for i, (hash_a, path_a) in enumerate(hash_map):
        if i in used:
            continue
        group = [path_a]
        for j, (hash_b, path_b) in enumerate(hash_map):
            if i == j or j in used:
                continue
            try:
                distance = hash_a - hash_b
                if distance <= DUPLICATE_MAX_DISTANCE:
                    group.append(path_b)
                    used.add(j)
            except Exception:
                continue
        if len(group) > 1:
            used.add(i)
            report.groups.append(DuplicateGroup(files=group, similarity="perceptual"))
            log.debug(f"Perceptual duplicate group: {[p.name for p in group]}")

    log.info(f"Pass 2 complete — {len(report.perceptual_groups)} perceptual groups found")
    log.info(report.summary())
    return report