from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def mark_run(
    db_path: Path,
    *,
    run_id: int,
    status: str,
    note: str,
    force_finished: bool,
) -> bool:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        row = conn.execute(
            "SELECT detail_json, finished_at FROM automation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return False
        detail_raw = row[0] or "{}"
        try:
            detail = json.loads(detail_raw)
        except Exception:
            detail = {}
        detail.update(
            {
                "progress_message": note,
                "stale_run_recovered": True,
                "stale_run_recovered_at": now_iso,
            }
        )
        finished_at = now_iso if force_finished or not row[1] else row[1]
        conn.execute(
            """
            UPDATE automation_runs
            SET status = ?, detail_json = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, json.dumps(detail, ensure_ascii=False), finished_at, run_id),
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark stale automation runs as cancelled/failed in one or more SQLite DBs.")
    parser.add_argument("--db", action="append", required=True, help="SQLite DB path. Repeat to update multiple DBs.")
    parser.add_argument("--run-id", type=int, required=True, help="Automation run id to update.")
    parser.add_argument("--status", default="cancelled", help="New status, e.g. cancelled or failed.")
    parser.add_argument(
        "--note",
        default="Marked stale manually. Previous run never finished; lock/process state should be considered recovered.",
        help="Progress note stored into detail_json.",
    )
    parser.add_argument("--force-finished", action="store_true", help="Set finished_at to now even if it was empty.")
    args = parser.parse_args()

    updated = 0
    for raw_db in args.db:
        db_path = Path(raw_db).expanduser().resolve()
        if not db_path.exists():
            print(f"[WARN] DB not found: {db_path}")
            continue
        changed = mark_run(
            db_path,
            run_id=int(args.run_id),
            status=str(args.status).strip(),
            note=str(args.note).strip(),
            force_finished=bool(args.force_finished),
        )
        if changed:
            updated += 1
            print(f"[OK] Updated run {args.run_id} in {db_path}")
        else:
            print(f"[WARN] Run {args.run_id} not found in {db_path}")

    return 0 if updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
