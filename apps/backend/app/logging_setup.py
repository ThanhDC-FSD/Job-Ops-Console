from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "backend.log"
ERROR_LOG_FILE = LOG_DIR / "backend.error.log"
COMPONENT_DIR = LOG_DIR / "components"

COMPONENT_LOGGERS = {
    "job_ops.api": "api.log",
    "job_ops.automation": "automation.log",
    "job_ops.cv_rewrite": "cv_rewrite.log",
    "job_ops.service.job": "job_service.log",
    "job_ops.scheduler": "scheduler.log",
}


class _StandardFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created).astimezone()
        return dt.isoformat(timespec="seconds")


class _DefaultFieldsFilter(logging.Filter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id or "-"

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "event"):
            record.event = "-"
        if not hasattr(record, "run_id"):
            record.run_id = self.run_id
        if not hasattr(record, "job_id"):
            record.job_id = "-"
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


def clear_logs_directory() -> None:
    if not LOG_DIR.exists():
        return
    for child in LOG_DIR.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            continue


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    COMPONENT_DIR.mkdir(parents=True, exist_ok=True)

    fmt = _StandardFormatter(
        fmt="ts=%(asctime)s level=%(levelname)s component=%(name)s event=%(event)s run_id=%(run_id)s trace_id=%(trace_id)s job_id=%(job_id)s message=\"%(message)s\""
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    default_filter = _DefaultFieldsFilter(os.getenv("JOB_OPS_RUN_ID", "").strip())
    root.addFilter(default_filter)

    def _collect_existing_files() -> set[str]:
        files: set[str] = set()
        for handler in root.handlers:
            if isinstance(handler, RotatingFileHandler):
                files.add(str(getattr(handler, "baseFilename", "")))
        for logger_name in COMPONENT_LOGGERS.keys():
            logger = logging.getLogger(logger_name)
            for handler in logger.handlers:
                if isinstance(handler, RotatingFileHandler):
                    files.add(str(getattr(handler, "baseFilename", "")))
        return files

    existing_files = _collect_existing_files()
    has_console = any(isinstance(handler, logging.StreamHandler) for handler in root.handlers)

    if not has_console:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        console.addFilter(default_filter)
        root.addHandler(console)

    if str(LOG_FILE.resolve()) not in existing_files:
        file_handler = RotatingFileHandler(
            filename=str(LOG_FILE),
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(fmt)
        file_handler.addFilter(default_filter)
        root.addHandler(file_handler)

    if str(ERROR_LOG_FILE.resolve()) not in existing_files:
        error_handler = RotatingFileHandler(
            filename=str(ERROR_LOG_FILE),
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(fmt)
        error_handler.addFilter(default_filter)
        root.addHandler(error_handler)

    existing_files = _collect_existing_files()

    for logger_name, file_name in COMPONENT_LOGGERS.items():
        target_path = COMPONENT_DIR / file_name
        target_resolved = str(target_path.resolve())
        if target_resolved in existing_files:
            continue
        logger = logging.getLogger(logger_name)
        handler = RotatingFileHandler(
            filename=str(target_path),
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(fmt)
        handler.addFilter(default_filter)
        logger.addHandler(handler)
