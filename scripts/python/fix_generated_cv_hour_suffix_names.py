from __future__ import annotations

import re
from pathlib import Path

try:
    import sqlite3
except Exception:  # pragma: no cover
    from pysqlite3 import dbapi2 as sqlite3  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
TARGET_ROOTS = [
    PROJECT_ROOT / "documents",
    PROJECT_ROOT / "input" / "Raw_CV",
]
TARGET_COLUMNS = [
    ("job_application_tracking", "cv_source_path"),
    ("job_application_tracking", "cover_letter_path"),
    ("job_application_tracking", "cover_letter_docx_path"),
    ("job_application_tracking", "cover_letter_pdf_path"),
    ("job_fit_scores", "cv_source_path"),
]
HOUR_TOKEN_PATTERNS = [
    re.compile(r"(?i)(?:_|-)\d+(?:_\d+)?h(?:rs?|ours?)?(?:_(?:week|wk|day|month|year|yr))(?=(?:_|-)|$)"),
    re.compile(r"(?i)(?:_|-)\d+h(?:rs?|ours?)?(?=(?:_|-)|$)"),
]


def _normalize_path(value: str) -> str:
    return str(value or "").replace("/", "\\").strip()


def _clean_component(name: str) -> str:
    path_obj = Path(name)
    suffix = path_obj.suffix
    stem = path_obj.stem if suffix else name
    updated = stem
    for pattern in HOUR_TOKEN_PATTERNS:
        updated = pattern.sub("", updated)
    updated = re.sub(r"(?i)(?:_|-)\d+(?:_(?:week|wk|day|month|year|yr))(?=(?:_|-)|$)", "", updated)
    updated = re.sub(r"(?i)(?:_|-)week$", "", updated)
    updated = re.sub(r"[_-]{2,}", "_", updated).strip("_-. ")
    return f"{updated}{suffix}" if suffix else updated


def _sanitize_full_path(path_value: str) -> str:
    raw = _normalize_path(path_value)
    if not raw:
        return ""
    parts = [part for part in raw.split("\\") if part != ""]
    if not parts:
        return ""
    if parts[0].endswith(":"):
        head = [parts[0]]
        tail = parts[1:]
    else:
        head = []
        tail = parts
    rebuilt = head + [_clean_component(part) for part in tail]
    return "\\".join(rebuilt)


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


def _rename_filesystem_entries() -> dict[str, str]:
    renamed: dict[str, str] = {}
    for root in TARGET_ROOTS:
        if not root.exists():
            continue
        entries = sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True)
        for entry in entries:
            old_name = entry.name
            new_name = _clean_component(old_name)
            if not new_name or new_name == old_name:
                continue
            old_abs = _normalize_path(str(entry.resolve()))
            target = _unique_target(entry.with_name(new_name))
            entry.rename(target)
            renamed[old_abs] = _normalize_path(str(target.resolve()))
    return renamed


def _update_db_paths(mapping: dict[str, str]) -> dict[str, int]:
    updates = {f"{table}.{column}": 0 for table, column in TARGET_COLUMNS}
    if not mapping:
        return updates

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        for table, column in TARGET_COLUMNS:
            rows = conn.execute(
                f"SELECT job_post_id, COALESCE({column}, '') AS path_value FROM {table} WHERE COALESCE({column}, '') <> ''"
            ).fetchall()
            for row in rows:
                current = _normalize_path(str(row["path_value"] or ""))
                next_path = mapping.get(current) or _sanitize_full_path(current)
                if not next_path or next_path == current:
                    continue
                conn.execute(
                    f"UPDATE {table} SET {column} = ? WHERE job_post_id = ?",
                    (next_path, int(row["job_post_id"])),
                )
                updates[f"{table}.{column}"] += 1
        conn.commit()
    finally:
        conn.close()
    return updates


def main() -> None:
    mapping = _rename_filesystem_entries()
    updates = _update_db_paths(mapping)
    print(f"DB: {DB_PATH}")
    print(f"filesystem_entries_renamed={len(mapping)}")
    for key, value in updates.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
