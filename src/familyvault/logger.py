"""
FamilyVault Logging
Configures a logger that writes to both the console and a rotating log file.
Import and use throughout the project with: from familyvault.logger import get_logger
"""

import logging
import logging.handlers
from pathlib import Path

from familyvault.config import LOG_DIR

# ── Settings ───────────────────────────────────────────────────────────────────
LOG_FILE_NAME   = "familyvault.log"
LOG_MAX_BYTES   = 5 * 1024 * 1024  # 5 MB per log file
LOG_BACKUP_COUNT = 3               # Keep 3 rotated files
LOG_FORMAT      = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _build_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Create and configure a logger with a console handler and a rotating file handler.
    Called once per named logger — subsequent calls return the cached instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if called more than once
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # ── Console handler (INFO and above) ──────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # ── File handler (DEBUG and above, rotating) ──────────────────────────────
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / LOG_FILE_NAME

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "familyvault") -> logging.Logger:
    """
    Return a configured logger for the given name.

    Usage:
        from familyvault.logger import get_logger
        log = get_logger(__name__)
        log.info("Scanner started")
    """
    return _build_logger(name)