"""
FamilyVault Face Detection
Detects faces in images using InsightFace (buffalo_l model pack) and
extracts a 512-dimensional embedding for each one — entirely offline,
no data ever leaves the machine. Embeddings are the input to a later
clustering pass that groups faces into people (not implemented yet;
see the face recognition planning doc for the full roadmap).

Phase 1 scope: images only. Video face recognition is deferred — the
same representative-frame approach captioner.py uses for video
captions could extend this later, but isn't wired up yet.
"""

from __future__ import annotations

import numpy as np
import pillow_heif
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
from PIL import Image, ImageOps, ImageFile, UnidentifiedImageError

from familyvault.config import IMAGE_EXTENSIONS, FACE_THUMBNAIL_DIR
from familyvault.logger import get_logger

log = get_logger(__name__)

pillow_heif.register_heif_opener()
ImageFile.LOAD_TRUNCATED_IMAGES = True

DET_SIZE = (640, 640)
MODEL_PACK = "buffalo_l"

# Lazy singleton — FaceAnalysis.prepare() loads five ONNX models from
# disk, expensive enough (a couple seconds) that it should happen once
# per process, not once per file. Same lazy-load-once pattern
# reverse_geocoder uses in location.py.
_app = None


def _get_app():
    global _app
    if _app is None:
        import insightface
        log.info(f"Loading InsightFace model pack '{MODEL_PACK}'...")
        _app = insightface.app.FaceAnalysis(
            name=MODEL_PACK,
            providers=["CPUExecutionProvider"],
        )
        _app.prepare(ctx_id=0, det_size=DET_SIZE)
        log.info("InsightFace ready.")
    return _app


@dataclass
class FaceDetection:
    """A single detected face within one image."""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    embedding: bytes              # 512 float32 values, raw bytes (np.tobytes())
    age: Optional[int] = None
    gender: Optional[str] = None  # "M" or "F", per InsightFace's genderage model


@dataclass
class FaceDetectionResult:
    path: Path
    faces: list[FaceDetection] = field(default_factory=list)
    error: Optional[str] = None
    # Same meaning as CaptionResult.permanent in captioner.py — True
    # only for failures where retrying will never help. "Zero faces
    # found" is a valid, successful result, not an error.
    permanent: bool = False

    @property
    def success(self) -> bool:
        return self.error is None


def _load_bgr_array(path: Path) -> np.ndarray:
    """
    Load an image as a BGR numpy array — the format InsightFace expects
    (same convention as cv2.imread's default).

    Goes through Pillow rather than cv2.imread directly, for the same
    reasons captioner.py does: cv2.imread can't read HEIC/HEIF at all
    (returns None silently, no error raised), and Pillow handles far
    more source formats and oddities reliably. EXIF orientation is
    corrected before detection, same as thumbnailer.py — an unrotated
    sideways photo would otherwise confuse or miss face detection
    entirely.
    """
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        rgb_array = np.array(img)

    return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)


def detect_faces(path: Path) -> FaceDetectionResult:
    """
    Detect every face in a single image and extract its embedding.

    Detection and embedding generation happen in the same InsightFace
    pass — no separate recognition step is needed.

    Args:
        path: Path to the source image.

    Returns:
        FaceDetectionResult — .faces is empty (not an error) for a
        genuine photo with no people in it.
    """
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return FaceDetectionResult(path=path, error="Unsupported file type", permanent=True)

    try:
        img_bgr = _load_bgr_array(path)
    except UnidentifiedImageError as e:
        log.warning(f"Not a recognizable image file {path.name}: {e}")
        return FaceDetectionResult(path=path, error=f"Not a recognizable image file: {e}", permanent=True)
    except Exception as e:
        log.warning(f"Could not read/prepare image {path.name}: {e}")
        return FaceDetectionResult(path=path, error=f"Could not read/prepare image: {e}")

    try:
        app = _get_app()
        raw_faces = app.get(img_bgr)
    except Exception as e:
        log.warning(f"Face detection failed for {path.name}: {e}")
        return FaceDetectionResult(path=path, error=f"Face detection failed: {e}")

    faces = []
    for f in raw_faces:
        x1, y1, x2, y2 = f.bbox.astype(int)
        gender = None
        if getattr(f, "gender", None) is not None:
            gender = "M" if int(f.gender) == 1 else "F"
        age = int(f.age) if getattr(f, "age", None) is not None else None

        faces.append(FaceDetection(
            x=int(x1),
            y=int(y1),
            width=int(x2 - x1),
            height=int(y2 - y1),
            confidence=float(f.det_score),
            embedding=np.asarray(f.embedding, dtype=np.float32).tobytes(),
            age=age,
            gender=gender,
        ))

    log.debug(f"Detected {len(faces)} face(s) in {path.name}")
    return FaceDetectionResult(path=path, faces=faces)


def crop_face(path: Path, x: int, y: int, width: int, height: int, padding: float = 0.3):
    """
    Crop a face region out of a source image, with padding, for use as
    a preview thumbnail (e.g. export-face-previews, and later the
    People UI's face crops). Applies the same EXIF-orientation
    correction detect_faces() applies before running detection, since
    (x, y, width, height) were computed against that corrected
    orientation — cropping against the raw, unrotated image would grab
    the wrong region for any photo with EXIF rotation.

    Args:
        path: Path to the source image.
        x, y, width, height: The face's bounding box, as stored on the
            faces table (already relative to the EXIF-corrected image).
        padding: Fraction of the face's width/height to pad on each
            side, so the crop shows a bit of context around the face
            rather than a tight box. 0.3 means each side gets 30% of
            that dimension added.

    Returns:
        A PIL Image, downscaled to fit within 300x300.
    """
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img_w, img_h = img.size

        pad_x = int(width * padding)
        pad_y = int(height * padding)
        left = max(0, x - pad_x)
        top = max(0, y - pad_y)
        right = min(img_w, x + width + pad_x)
        bottom = min(img_h, y + height + pad_y)

        crop = img.crop((left, top, right, bottom))
        crop.thumbnail((300, 300), Image.LANCZOS)
        return crop.copy()


def face_thumbnail_path(face_id: int) -> Path:
    """
    Derive a cache path for a face crop thumbnail. Sharded into
    subfolders of 1000 to avoid one enormous flat directory — same
    reasoning as thumbnailer.py's thumbnail_path() sharding, just
    keyed by face id (already a stable, unique identifier) instead of
    a hash of the source path.
    """
    bucket = face_id // 1000
    return FACE_THUMBNAIL_DIR / str(bucket) / f"{face_id}.jpg"


def get_or_create_face_thumbnail(face_id: int, path: Path, x: int, y: int, width: int, height: int) -> Path | None:
    """
    Return the cached face-crop thumbnail for a face, generating and
    caching it on first request — mirrors thumbnailer.generate_thumbnail()'s
    cache-on-first-request pattern. Without this, the People grid would
    re-open and re-crop the source image on every single page load for
    every person, which would be slow for a library on an external drive.

    Returns:
        Path to the cached JPEG, or None if the crop couldn't be
        generated (e.g. source file missing or unreadable).
    """
    dest = face_thumbnail_path(face_id)
    if dest.exists():
        return dest

    try:
        crop = crop_face(path, x, y, width, height)
        dest.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dest, format="JPEG", quality=85)
        return dest
    except Exception as e:
        log.warning(f"Could not generate face thumbnail for face #{face_id}: {e}")
        return None