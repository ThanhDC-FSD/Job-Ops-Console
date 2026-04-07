from __future__ import annotations

import re
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
TARGET_ROOTS = [
    PROJECT_ROOT / "input" / "Raw_CV",
    PROJECT_ROOT / "documents",
]
TOKEN_PATTERN = re.compile(r"(?i)(^|[_-])job_\d+(?=[_-]|$)")


def _sanitize_component(name: str) -> str:
    path_obj = Path(name)
    suffix = path_obj.suffix
    stem = path_obj.stem if suffix else name
    updated = TOKEN_PATTERN.sub(r"\1", stem)
    updated = re.sub(r"[_-]{2,}", "_", updated).strip("_-. ")
    if not updated:
        updated = "renamed"
    return f"{updated}{suffix}" if suffix else updated


def _unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.stem
    suffix = path.suffix
    idx = 2
    while True:
        candidate = path.with_name(f"{base}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _rename_filesystem_entries() -> dict[str, str]:
    renamed: dict[str, str] = {}
    for root in TARGET_ROOTS:
        if not root.exists():
            continue
        entries = sorted(root.rglob("*"), key=lambda p: (len(p.parts), p.is_dir()), reverse=True)
        for entry in entries:
            old_name = entry.name
            new_name = _sanitize_component(old_name)
            if new_name == old_name:
                continue
            old_abs = str(entry.resolve())
            target = _unique_target(entry.with_name(new_name))
            entry.rename(target)
            renamed[old_abs] = str(target.resolve())
    return renamed


def _sanitize_full_path(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("/", "\\")
    parts = normalized.split("\\")
    if len(parts) <= 1:
        return _sanitize_component(normalized)
    drive, rest = parts[0], parts[1:]
    rebuilt = [drive] + [_sanitize_component(x) for x in rest]
    return "\\".join(rebuilt)


def _update_sqlite_paths() -> dict[str, int]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    updates = {
        "job_application_tracking.cv_source_path": 0,
        "job_application_tracking.cv_folder_name": 0,
        "job_fit_scores.cv_source_path": 0,
    }
    try:
        rows = conn.execute(
            """
            SELECT job_post_id, cv_source_path, cv_folder_name
            FROM job_application_tracking
            WHERE COALESCE(cv_source_path, '') LIKE '%job_%'
               OR COALESCE(cv_folder_name, '') LIKE '%job_%'
            """
        ).fetchall()
        for row in rows:
            job_post_id = int(row["job_post_id"])
            cv_source_path = str(row["cv_source_path"] or "")
            cv_folder_name = str(row["cv_folder_name"] or "")
            next_path = _sanitize_full_path(cv_source_path)
            next_folder = _sanitize_component(cv_folder_name) if cv_folder_name else ""
            if next_path and next_path != cv_source_path:
                conn.execute(
                    "UPDATE job_application_tracking SET cv_source_path = ? WHERE job_post_id = ?",
                    (next_path, job_post_id),
                )
                updates["job_application_tracking.cv_source_path"] += 1
            if next_folder and next_folder != cv_folder_name:
                conn.execute(
                    "UPDATE job_application_tracking SET cv_folder_name = ? WHERE job_post_id = ?",
                    (next_folder, job_post_id),
                )
                updates["job_application_tracking.cv_folder_name"] += 1

        rows = conn.execute(
            """
            SELECT job_post_id, cv_source_path
            FROM job_fit_scores
            WHERE COALESCE(cv_source_path, '') LIKE '%job_%'
            """
        ).fetchall()
        for row in rows:
            job_post_id = int(row["job_post_id"])
            cv_source_path = str(row["cv_source_path"] or "")
            next_path = _sanitize_full_path(cv_source_path)
            if next_path and next_path != cv_source_path:
                conn.execute(
                    "UPDATE job_fit_scores SET cv_source_path = ? WHERE job_post_id = ?",
                    (next_path, job_post_id),
                )
                updates["job_fit_scores.cv_source_path"] += 1

        conn.commit()
        return updates
    finally:
        conn.close()


def _count_db_paths_with_local_job_token() -> dict[str, int]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        result = {}
        result["job_application_tracking.cv_source_path"] = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM job_application_tracking WHERE COALESCE(cv_source_path, '') LIKE '%job_%'"
            ).fetchone()["c"]
        )
        result["job_application_tracking.cv_folder_name"] = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM job_application_tracking WHERE COALESCE(cv_folder_name, '') LIKE '%job_%'"
            ).fetchone()["c"]
        )
        result["job_fit_scores.cv_source_path"] = int(
            conn.execute("SELECT COUNT(*) AS c FROM job_fit_scores WHERE COALESCE(cv_source_path, '') LIKE '%job_%'").fetchone()[
                "c"
            ]
        )
        return result
    finally:
        conn.close()


def main() -> None:
    before = _count_db_paths_with_local_job_token()
    renamed = _rename_filesystem_entries()
    updated = _update_sqlite_paths()
    after = _count_db_paths_with_local_job_token()

    print(f"DB: {DB_PATH}")
    print(f"filesystem_entries_renamed={len(renamed)}")
    print("db_rows_updated:")
    for key, value in updated.items():
        print(f"  - {key}: {value}")
    print("db_paths_with_job_token:")
    for key in sorted(before.keys()):
        print(f"  - {key}: {before[key]} -> {after[key]}")


if __name__ == "__main__":
    main()
