from __future__ import annotations

import re
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
DOCUMENTS_ROOT = PROJECT_ROOT / "documents"
DATE_TOKEN_PATTERN = re.compile(r"^(?P<base>.+)_(?P<date>\d{6})_(?P<seq>\d{2})$")
PREFIX_DATE_TOKEN_PATTERN = re.compile(r"^(?P<prefix>CV)_(?P<date>\d{6})_(?P<seq>\d{2})_(?P<base>.+)$", re.IGNORECASE)
DATE_FOLDER_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_folder_name(token: str) -> str:
    yy = int(token[0:2])
    year = 2000 + yy
    month = token[2:4]
    day = token[4:6]
    return f"{year:04d}-{month}-{day}"


def _unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    idx = 2
    while True:
        candidate = path.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _normalized(value: str) -> str:
    return str(value or "").replace("/", "\\").strip()


def _rename_documents() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not DOCUMENTS_ROOT.exists():
        return mapping

    for entry in sorted(DOCUMENTS_ROOT.glob("*")):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in {".pdf", ".docx"}:
            continue
        match = DATE_TOKEN_PATTERN.match(entry.stem)
        prefix_match = PREFIX_DATE_TOKEN_PATTERN.match(entry.stem)
        if prefix_match:
            base = prefix_match.group("base").strip("_.- ")
            date_folder = _date_folder_name(prefix_match.group("date"))
            target_dir = DOCUMENTS_ROOT / date_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_target(target_dir / f"{base}{entry.suffix.lower()}")
            old_abs = str(entry.resolve())
            entry.rename(target)
            mapping[_normalized(old_abs)] = _normalized(str(target.resolve()))
            continue
        if not match:
            continue
        base = match.group("base").strip("_.- ")
        date_folder = _date_folder_name(match.group("date"))
        target_dir = DOCUMENTS_ROOT / date_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_target(target_dir / f"{base}{entry.suffix.lower()}")
        old_abs = str(entry.resolve())
        entry.rename(target)
        mapping[_normalized(old_abs)] = _normalized(str(target.resolve()))
    for day_dir in sorted(DOCUMENTS_ROOT.iterdir()):
        if not day_dir.is_dir() or not DATE_FOLDER_PATTERN.match(day_dir.name):
            continue
        for entry in sorted(day_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in {".pdf", ".docx"}:
                continue
            if entry.stem.lower().startswith("cv_"):
                continue
            target = _unique_target(day_dir / f"CV_{entry.name}")
            old_abs = str(entry.resolve())
            entry.rename(target)
            mapping[_normalized(old_abs)] = _normalized(str(target.resolve()))
    return mapping


def _update_db_paths(mapping: dict[str, str]) -> dict[str, int]:
    updates = {
        "job_application_tracking.cv_source_path": 0,
        "job_fit_scores.cv_source_path": 0,
    }
    if not mapping:
        return updates

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT job_post_id, cv_source_path
            FROM job_application_tracking
            WHERE COALESCE(cv_source_path, '') <> ''
            """
        ).fetchall()
        for row in rows:
            current = _normalized(str(row["cv_source_path"] or ""))
            next_path = mapping.get(current)
            if not next_path or next_path == current:
                continue
            conn.execute(
                "UPDATE job_application_tracking SET cv_source_path = ? WHERE job_post_id = ?",
                (next_path, int(row["job_post_id"])),
            )
            updates["job_application_tracking.cv_source_path"] += 1

        rows = conn.execute(
            """
            SELECT job_post_id, cv_source_path
            FROM job_fit_scores
            WHERE COALESCE(cv_source_path, '') <> ''
            """
        ).fetchall()
        for row in rows:
            current = _normalized(str(row["cv_source_path"] or ""))
            next_path = mapping.get(current)
            if not next_path or next_path == current:
                continue
            conn.execute(
                "UPDATE job_fit_scores SET cv_source_path = ? WHERE job_post_id = ?",
                (next_path, int(row["job_post_id"])),
            )
            updates["job_fit_scores.cv_source_path"] += 1

        conn.commit()
    finally:
        conn.close()
    return updates


def main() -> None:
    mapping = _rename_documents()
    updates = _update_db_paths(mapping)
    print(f"DB: {DB_PATH}")
    print(f"documents_renamed={len(mapping)}")
    for key, value in updates.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
