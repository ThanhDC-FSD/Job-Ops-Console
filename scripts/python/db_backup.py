from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from logging_utils import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup a SQLite database file.")
    parser.add_argument("--source", required=True, help="Source SQLite file.")
    parser.add_argument("--target", required=True, help="Target backup path.")
    return parser.parse_args()


def main() -> None:
    logger = setup_logging("DB.Backup", log_dir="components")
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        logger.error(
            "Backup failed | source_missing=%s",
            source,
            extra={"event": "missing_source"},
        )
        raise FileNotFoundError(f"Source database not found: {source}")
    shutil.copy2(source, target)
    logger.info(
        "Backup complete | source=%s target=%s",
        source,
        target,
        extra={"event": "complete"},
    )


if __name__ == "__main__":
    main()
