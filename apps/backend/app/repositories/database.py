import sqlite3
import logging
from contextlib import contextmanager
from typing import Iterator

from app.config import (
    DB_PATH,
    ENABLE_SQLITE_WAL_TUNING,
    SQLITE_BUSY_TIMEOUT_MS,
    TUNING_SQLITE_CACHE_SIZE,
)


class Database:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(DB_PATH if db_path is None else db_path)
        self.logger = logging.getLogger("job_ops.db")

    @contextmanager
    def connect(self, *, timeout: float = 30.0, busy_timeout_ms: int | None = None) -> Iterator[sqlite3.Connection]:
        timeout = max(0.1, float(timeout))
        busy_timeout = int(busy_timeout_ms if busy_timeout_ms is not None else SQLITE_BUSY_TIMEOUT_MS or timeout * 1000)
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute(f"PRAGMA busy_timeout = {busy_timeout};")
            if ENABLE_SQLITE_WAL_TUNING:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                try:
                    conn.execute(f"PRAGMA cache_size = {int(TUNING_SQLITE_CACHE_SIZE)};")
                    conn.execute("PRAGMA temp_store = MEMORY;")
                except Exception as exc:
                    self.logger.warning("SQLite PRAGMA tuning failed | error=%s", exc)
            yield conn
            conn.commit()
        finally:
            conn.close()
