from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable


TABLES_TO_CHECK = [
    "job_posts",
    "job_observations",
    "job_application_tracking",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare SQLite database snapshots before/after sync.")
    parser.add_argument("--dev-before", required=True, help="Dev DB snapshot before sync.")
    parser.add_argument("--cd-before", required=True, help="CD DB snapshot before sync.")
    parser.add_argument("--dev-after", required=True, help="Dev DB after sync.")
    parser.add_argument("--cd-after", required=True, help="CD DB after sync.")
    return parser.parse_args()


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def row_counts(path: Path, tables: Iterable[str]) -> dict[str, int]:
    counts = {}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
            row = cursor.fetchone()
            counts[table] = row["cnt"] if row else -1
    except sqlite3.Error as exc:
        counts["error"] = -1
        print(f"[ERROR] Counting rows in {table} failed: {exc}")
    finally:
        conn.close()
    return counts


def print_counts(label: str, counts: dict[str, int]) -> None:
    print(f"[COUNTS] {label}")
    for table, count in counts.items():
        print(f"  {table}: {count}")


def main() -> None:
    args = parse_args()
    dev_before = Path(args.dev_before).expanduser().resolve()
    cd_before = Path(args.cd_before).expanduser().resolve()
    dev_after = Path(args.dev_after).expanduser().resolve()
    cd_after = Path(args.cd_after).expanduser().resolve()

    for path in (dev_before, cd_before, dev_after, cd_after):
        if not path.exists():
            raise FileNotFoundError(f"Missing database file: {path}")

    print("[HASH] dev_before:", file_hash(dev_before))
    print("[HASH] cd_before :", file_hash(cd_before))
    print("[HASH] dev_after :", file_hash(dev_after))
    print("[HASH] cd_after  :", file_hash(cd_after))

    counts_dev_before = row_counts(dev_before, TABLES_TO_CHECK)
    counts_cd_before = row_counts(cd_before, TABLES_TO_CHECK)
    counts_dev_after = row_counts(dev_after, TABLES_TO_CHECK)
    counts_cd_after = row_counts(cd_after, TABLES_TO_CHECK)

    print_counts("dev_before", counts_dev_before)
    print_counts("cd_before", counts_cd_before)
    print_counts("dev_after", counts_dev_after)
    print_counts("cd_after", counts_cd_after)


if __name__ == "__main__":
    main()
