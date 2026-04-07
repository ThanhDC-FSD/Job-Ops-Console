from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from linkedin_jobs_jd import backfill_job_detail_validations, connect_sqlite, init_sqlite


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill LLM-validated job details into SQLite.")
    parser.add_argument("--sqlite-db", default="input/crawled_job/linkedin_jobs_jd.sqlite", help="SQLite DB path")
    parser.add_argument(
        "--recent-days",
        type=int,
        default=0,
        help="Only validate jobs seen in the last N days (0 = all jobs)",
    )
    parser.add_argument("--force", action="store_true", help="Revalidate even when source hash did not change")
    args = parser.parse_args()

    db_path = Path(args.sqlite_db).resolve()
    conn = connect_sqlite(db_path)
    try:
        init_sqlite(conn)
        job_post_ids = None
        if args.recent_days and args.recent_days > 0:
            cutoff = (datetime.now(timezone.utc).date() - timedelta(days=args.recent_days)).isoformat()
            rows = conn.execute(
                """
                SELECT id
                FROM job_posts
                WHERE COALESCE(NULLIF(TRIM(last_seen_date), ''), first_seen_date) >= ?
                ORDER BY id ASC
                """,
                (cutoff,),
            ).fetchall()
            job_post_ids = [int(row["id"]) for row in rows]
            print(f"recent_days={args.recent_days} cutoff={cutoff} selected_job_posts={len(job_post_ids)}")
        stats = backfill_job_detail_validations(conn, job_post_ids=job_post_ids, force=args.force)
    finally:
        conn.close()
    print(stats)


if __name__ == "__main__":
    main()
