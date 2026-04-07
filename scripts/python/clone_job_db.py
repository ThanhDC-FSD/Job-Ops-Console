from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone the crawled job database so the backend/CD workflow can target a schema-specific copy."
    )
    parser.add_argument(
        "--source",
        default="input/crawled_job/linkedin_jobs_jd.sqlite",
        help="Existing SQLite file that contains the crawled job schema.",
    )
    parser.add_argument(
        "--target",
        default="apps/backend/app/job_ops_schema.sqlite",
        help="Path to the new copy that the API/CD workflow should read/write.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target file if it already exists.",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Run VACUUM after copying in order to rebuild the schema cleanly.",
    )
    args = parser.parse_args()

    source_path = Path(args.source).expanduser().resolve()
    target_path = Path(args.target).expanduser().resolve()

    if not source_path.exists():
        raise SystemExit(f"[ERROR] Source database not found: {source_path}")

    if target_path.exists():
        if args.force:
            target_path.unlink()
        else:
            raise SystemExit(
                f"[ERROR] Target already exists. Use --force to replace: {target_path}"
            )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    print(f"[INFO] Cloned {source_path} -> {target_path}")

    if args.vacuum:
        import sqlite3

        with sqlite3.connect(target_path) as conn:
            conn.execute("VACUUM;")
        print(f"[INFO] VACUUM completed for {target_path}")


if __name__ == "__main__":
    main()
