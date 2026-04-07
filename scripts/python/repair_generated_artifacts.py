from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.database import Database
from app.repositories.job_repository import JobRepository
from app.services.job_service import JobService


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair generated CV artifacts for recent jobs.")
    parser.add_argument("--sqlite-db", default="input/crawled_job/linkedin_jobs_jd.sqlite", help="SQLite DB path")
    parser.add_argument("--limit", type=int, default=300, help="Max jobs to inspect")
    parser.add_argument("--recent-days", type=int, default=15, help="Recent window in days")
    parser.add_argument("--constraint-mode", default="medium", help="Constraint mode for preview hydration")
    parser.add_argument("--only-missing", action="store_true", help="Inspect only jobs missing generated artifact paths")
    args = parser.parse_args()

    service = JobService(JobRepository(Database(str(Path(args.sqlite_db).resolve()))))
    result = service.repair_generated_artifacts(
        limit=max(1, int(args.limit)),
        only_missing=bool(args.only_missing),
        constraint_mode=str(args.constraint_mode or "medium"),
        recent_days=max(0, int(args.recent_days)),
    )
    print(
        f"[ARTIFACT REPAIR] processed={result.get('processed', 0)} "
        f"still_missing={result.get('jobs_still_missing_fields', 0)} "
        f"recent_days={result.get('recent_days', 0)}",
        flush=True,
    )
    sample_items = list(result.get("items") or [])[:10]
    for item in sample_items:
        print(
            "[ARTIFACT REPAIR] item="
            + json.dumps(
                {
                    "job_post_id": int(item.get("job_post_id") or 0),
                    "company": str(item.get("company") or ""),
                    "title": str(item.get("title") or ""),
                    "missing_fields": list(item.get("missing_fields") or []),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
