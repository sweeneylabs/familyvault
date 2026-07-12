"""
Tests for src/familyvault/logger.py
Run with: python -m pytest tests/test_logger.py -v
"""

import logging
from pathlib import Path

from familyvault.logger import get_logger
from familyvault.config import LOG_DIR, PROJECT_ROOT


def test_get_logger_returns_logger():
    log = get_logger("test.basic")
    assert isinstance(log, logging.Logger)


def test_logger_name_is_set():
    log = get_logger("test.name")
    assert log.name == "test.name"


def test_logger_has_two_handlers():
    log = get_logger("test.handlers")
    assert len(log.handlers) == 2


def test_logger_default_name():
    log = get_logger()
    assert log.name == "familyvault"


def test_same_logger_returned_on_second_call():
    log1 = get_logger("test.singleton")
    log2 = get_logger("test.singleton")
    assert log1 is log2


def test_log_dir_created():
    get_logger("test.logdir")
    assert LOG_DIR.is_dir()


def test_log_file_created():
    get_logger("test.logfile")
    log_file = LOG_DIR / "familyvault.log"
    assert log_file.exists()


def test_log_dir_is_under_project_root():
    assert LOG_DIR.is_relative_to(PROJECT_ROOT)


def test_logger_writes_to_file(tmp_path):
    log = get_logger("test.write")
    log.debug("test debug message")
    log_file = LOG_DIR / "familyvault.log"
    contents = log_file.read_text(encoding="utf-8")
    assert "test debug message" in contents


def test_console_handler_level_is_info():
    log = get_logger("test.console.level")
    stream_handlers = [
        h for h in log.handlers if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert stream_handlers[0].level == logging.INFO


def test_file_handler_level_is_debug():
    log = get_logger("test.file.level")
    file_handlers = [
        h for h in log.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers[0].level == logging.DEBUG