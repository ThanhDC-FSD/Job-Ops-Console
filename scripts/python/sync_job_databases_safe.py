from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path


ACTIVE_STATUSES = {"queued", "running"}


def has_active_runs(db_path: Path) -> bool:
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM automation_runs
                WHERE LOWER(COALESCE(status, '')) IN ('queued', 'running')
                """
            ).fetchone()
            return bool((row[0] if row else 0) > 0)
    except sqlite3.OperationalError:
        return False


def sync_sqlite(source_path: Path, target_path: Path, *, retries: int = 3) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=10.0) as source_conn:
                with sqlite3.connect(str(target_path), timeout=10.0) as target_conn:
                    source_conn.backup(target_conn)
                    target_conn.execute("PRAGMA wal_checkpoint(FULL);")
            return
        except Exception as exc:  # pragma: no cover - runtime dependent
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(1.0 * attempt)
    if last_error is not None:
        raise last_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely sync the crawl/dev SQLite database into the API/CD schema copy via SQLite backup."
    )
    parser.add_argument(
        "--source",
        default="input/crawled_job/linkedin_jobs_jd.sqlite",
        help="Source SQLite database (usually the crawl/dev DB).",
    )
    parser.add_argument(
        "--target",
        default="apps/backend/app/job_ops_schema.sqlite",
        help="Target SQLite database (usually the API/CD copy).",
    )
    parser.add_argument(
        "--skip-if-source-active",
        action="store_true",
        help="Skip syncing when the source DB still has queued/running automation runs.",
    )
    args = parser.parse_args()

    source_path = Path(args.source).expanduser().resolve()
    target_path = Path(args.target).expanduser().resolve()

    if not source_path.exists():
        print(f"[ERROR] Source database not found: {source_path}")
        return 1

    if args.skip_if_source_active and has_active_runs(source_path):
        print(f"[SKIP] Active automation runs detected in source DB: {source_path}")
        return 0

    sync_sqlite(source_path, target_path)
    print(f"[OK] SQLite backup sync complete: {source_path} -> {target_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
