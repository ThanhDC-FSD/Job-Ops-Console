from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = PROJECT_ROOT / "apps" / "backend" / "app" / "logs"


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


def setup_logging(component: str, *, log_dir: str = "components", run_id: str | None = None) -> logging.Logger:
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger(component)

    run_id = (run_id or os.getenv("JOB_OPS_RUN_ID", "")).strip() or datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    formatter = _StandardFormatter(
        fmt="ts=%(asctime)s level=%(levelname)s component=%(name)s event=%(event)s run_id=%(run_id)s trace_id=%(trace_id)s job_id=%(job_id)s message=\"%(message)s\""
    )
    default_filter = _DefaultFieldsFilter(run_id)

    root.setLevel(logging.INFO)

    log_folder = LOG_ROOT / log_dir
    log_folder.mkdir(parents=True, exist_ok=True)
    file_path = log_folder / f"{component.replace('.', '_')}_{run_id}.log"

    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(default_filter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    console.addFilter(default_filter)
    root.addHandler(console)

    return logging.getLogger(component)
