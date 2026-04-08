from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import TUNING_CACHE_DB_PATH, TUNING_CACHE_SQLITE_WAL, TUNING_PREDICT_QA_LOG_DIR

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class JsonlLogger:
    """Append-only JSONL logger for prediction runs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = self.path.open("a", encoding="utf-8")

    def event(self, payload: dict[str, Any]) -> None:
        """Write one JSON object per line for easy offline aggregation."""
        self.fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.fp.flush()

    def close(self) -> None:
        """Close the underlying file handle safely."""
        try:
            self.fp.close()
        except Exception:
            pass


def resolve_output_root() -> Path:
    """Resolve the configured prediction output directory inside the workspace."""
    root = Path(TUNING_PREDICT_QA_LOG_DIR)
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    return root


def now_stamp() -> str:
    """Return a sortable timestamp for run directories."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def open_cache_db() -> sqlite3.Connection:
    """Open the shared cache database used by prediction runs."""
    cache_path = Path(TUNING_CACHE_DB_PATH)
    if not cache_path.is_absolute():
        cache_path = (PROJECT_ROOT / cache_path).resolve()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cache_path), timeout=30.0)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v BLOB, ts INTEGER)")
    if TUNING_CACHE_SQLITE_WAL:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def cache_get_json(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    """Read a cached JSON payload for a stable input hash."""
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    if not row or row[0] in (None, ""):
        return None
    try:
        parsed = json.loads(str(row[0]))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def cache_put_json(conn: sqlite3.Connection, key: str, payload: dict[str, Any]) -> None:
    """Persist JSON payload in the shared cache for unchanged inputs."""
    ts = int(time.time())
    conn.execute(
        "INSERT INTO kv(k, v, ts) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, ts = excluded.ts",
        (key, json.dumps(payload, ensure_ascii=False), ts),
    )
    conn.commit()


def build_prediction_cache_key(*parts: str) -> str:
    """Build a compact cache key from stable hash inputs."""
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"predict_qa:{digest}"


def shutdown_after_completion() -> None:
    """Request a delayed Windows shutdown after outputs are safely written."""
    if os.name != "nt":
        return
    subprocess.run(
        [
            "shutdown",
            "/s",
            "/t",
            "60",
            "/c",
            "Interview Q&A prediction completed.",
        ],
        check=False,
    )
