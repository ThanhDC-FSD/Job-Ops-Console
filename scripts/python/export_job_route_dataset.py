from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _default_repo_root() -> Path:
    colab_repo = Path("/content/Job-Ops-Console")
    if colab_repo.exists():
        return colab_repo
    return Path.cwd()


DEFAULT_REPO_ROOT = _default_repo_root()
DEFAULT_DB_PATH = DEFAULT_REPO_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
DEFAULT_OUT_DIR = DEFAULT_REPO_ROOT / "artifacts" / "ml" / "job_route"
LINKEDIN_HOST_TOKENS = ("linkedin.com", "lnkd.in", "onsiteapply", "easyapply")
TEXT_KEYS = (
    "description",
    "job_description",
    "jobDescription",
    "full_description",
    "jd_text",
    "summary",
)


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _extract_apply_url(payload: dict[str, Any]) -> str:
    return str(payload.get("apply_url") or payload.get("external_apply_url") or "").strip()


def _extract_public_apply_mode(payload: dict[str, Any]) -> str:
    return str(payload.get("public_apply_mode") or "").strip().lower()


def _is_easy_apply_url(url: str) -> bool:
    low = str(url or "").strip().lower()
    if not low:
        return False
    return any(token in low for token in LINKEDIN_HOST_TOKENS)


def _url_host(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    return (parsed.netloc or "").strip().lower()


def _truncate(text: str, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _collect_text_candidates(value: Any, out: list[str]) -> None:
    if value in (None, ""):
        return
    if isinstance(value, str):
        out.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_text_candidates(item, out)
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key or "") in TEXT_KEYS:
                _collect_text_candidates(nested, out)
            elif isinstance(nested, (dict, list)):
                _collect_text_candidates(nested, out)


def _extract_description(payload: dict[str, Any], *, limit: int) -> str:
    values: list[str] = []
    for key in TEXT_KEYS:
        if key in payload:
            _collect_text_candidates(payload.get(key), values)
    if not values:
        _collect_text_candidates(payload, values)
    merged = " ".join(v.strip() for v in values if str(v or "").strip())
    return _truncate(merged, limit)


def _effective_easy_apply(
    *,
    normalized_easy_apply: int,
    validated_easy_apply: int,
    payload: dict[str, Any],
) -> int:
    if int(validated_easy_apply or 0) == 1:
        return 1
    if int(normalized_easy_apply or 0) == 1:
        return 1
    public_apply_mode = _extract_public_apply_mode(payload)
    if public_apply_mode == "onsite":
        return 1
    apply_url = _extract_apply_url(payload)
    if _is_easy_apply_url(apply_url):
        return 1
    if str(payload.get("easy_apply") or "").strip() in {"1", "true", "True"}:
        return 1
    return 0


def _label_row(row: sqlite3.Row, payload: dict[str, Any]) -> tuple[str, str]:
    manual_review_required = int(row["manual_review_required"] or 0)
    normalized_easy_apply = int(row["normalized_easy_apply"] or 0)
    validated_easy_apply = int(row["validated_easy_apply"] or 0)
    public_apply_mode = _extract_public_apply_mode(payload)
    apply_url = _extract_apply_url(payload)
    effective_easy = _effective_easy_apply(
        normalized_easy_apply=normalized_easy_apply,
        validated_easy_apply=validated_easy_apply,
        payload=payload,
    )

    if manual_review_required == 1:
        return "manual_review_candidate", "manual_review_required=1"
    if effective_easy == 1 and public_apply_mode != "offsite":
        return "easy_apply", "effective_easy_apply=1"
    if public_apply_mode == "offsite":
        return "offsite", "public_apply_mode=offsite"
    if apply_url and not _is_easy_apply_url(apply_url):
        return "offsite", "external_apply_url"
    return "", "ambiguous_or_unlabeled"


def _build_model_text(row: sqlite3.Row, payload: dict[str, Any], *, description_chars: int) -> str:
    apply_url = _extract_apply_url(payload)
    lines = [
        f"title: {str(row['title'] or '').strip()}",
        f"company: {str(row['company'] or '').strip()}",
        f"location: {str(row['location'] or '').strip()}",
        f"work_model: {str(row['normalized_work_model'] or '').strip()}",
        f"employment_type: {str(row['normalized_employment_type'] or '').strip()}",
        f"posted_time: {str(row['latest_posted_time'] or '').strip()}",
        f"public_apply_mode: {_extract_public_apply_mode(payload)}",
        f"apply_url_host: {_url_host(apply_url)}",
        f"job_url_host: {_url_host(str(row['job_url_final'] or row['job_url'] or '').strip())}",
        f"description: {_extract_description(payload, limit=description_chars)}",
    ]
    return "\n".join(lines).strip()


def _iter_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    query = """
        SELECT
          jp.id,
          jp.title,
          jp.company,
          jp.location,
          COALESCE(jp.normalized_work_model, '') AS normalized_work_model,
          COALESCE(jp.normalized_employment_type, '') AS normalized_employment_type,
          COALESCE(jp.normalized_easy_apply, 0) AS normalized_easy_apply,
          COALESCE(jdv.easy_apply, 0) AS validated_easy_apply,
          COALESCE(jat.manual_review_required, 0) AS manual_review_required,
          COALESCE(jat.manual_review_note, '') AS manual_review_note,
          COALESCE(jp.job_url, '') AS job_url,
          COALESCE(jp.job_url_final, '') AS job_url_final,
          COALESCE(jp.latest_posted_time, '') AS latest_posted_time,
          COALESCE(jp.latest_payload_json, '') AS latest_payload_json
        FROM job_posts jp
        LEFT JOIN job_detail_validations jdv ON jdv.job_post_id = jp.id
        LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
        WHERE COALESCE(jp.latest_payload_json, '') <> ''
          AND COALESCE(jp.title, '') <> ''
          AND COALESCE(jp.company, '') <> ''
    """
    return list(conn.execute(query).fetchall())


def _assign_split(job_id: int, *, train_ratio: float, val_ratio: float, seed: int) -> str:
    rng = random.Random(seed + int(job_id))
    value = rng.random()
    if value < train_ratio:
        return "train"
    if value < train_ratio + val_ratio:
        return "val"
    return "test"


def export_dataset(
    *,
    sqlite_db: Path,
    out_dir: Path,
    description_chars: int,
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "job_route_dataset.csv"
    jsonl_path = out_dir / "job_route_dataset.jsonl"
    summary_path = out_dir / "job_route_dataset_summary.json"

    with sqlite3.connect(str(sqlite_db)) as conn:
        rows = _iter_rows(conn)

    label_counts: Counter[str] = Counter()
    skip_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for row in rows:
        payload = _safe_json_loads(row["latest_payload_json"])
        label, reason = _label_row(row, payload)
        if not label:
            skip_counts[reason] += 1
            continue
        record = {
            "job_id": int(row["id"] or 0),
            "label": label,
            "label_reason": reason,
            "split": _assign_split(int(row["id"] or 0), train_ratio=train_ratio, val_ratio=val_ratio, seed=seed),
            "title": str(row["title"] or "").strip(),
            "company": str(row["company"] or "").strip(),
            "location": str(row["location"] or "").strip(),
            "normalized_work_model": str(row["normalized_work_model"] or "").strip(),
            "normalized_employment_type": str(row["normalized_employment_type"] or "").strip(),
            "normalized_easy_apply": int(row["normalized_easy_apply"] or 0),
            "validated_easy_apply": int(row["validated_easy_apply"] or 0),
            "manual_review_required": int(row["manual_review_required"] or 0),
            "manual_review_note": str(row["manual_review_note"] or "").strip(),
            "job_url": str(row["job_url"] or "").strip(),
            "job_url_final": str(row["job_url_final"] or "").strip(),
            "latest_posted_time": str(row["latest_posted_time"] or "").strip(),
            "public_apply_mode": _extract_public_apply_mode(payload),
            "apply_url": _extract_apply_url(payload),
            "apply_url_host": _url_host(_extract_apply_url(payload)),
            "text": _build_model_text(row, payload, description_chars=description_chars),
        }
        records.append(record)
        label_counts[label] += 1

    fieldnames = list(records[0].keys()) if records else []
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "sqlite_db": str(sqlite_db),
        "total_rows_scanned": len(rows),
        "total_labeled_rows": len(records),
        "label_counts": dict(sorted(label_counts.items())),
        "skip_counts": dict(sorted(skip_counts.items())),
        "split_counts": dict(sorted(Counter(r["split"] for r in records).items())),
        "description_chars": int(description_chars),
        "train_ratio": float(train_ratio),
        "val_ratio": float(val_ratio),
        "test_ratio": float(max(0.0, 1.0 - train_ratio - val_ratio)),
        "seed": int(seed),
        "csv_path": str(csv_path),
        "jsonl_path": str(jsonl_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export labeled dataset for job-route classifier training. "
            "Defaults auto-detect Google Colab at /content/Job-Ops-Console when available."
        )
    )
    parser.add_argument(
        "--sqlite-db",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite DB path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for CSV/JSONL dataset. Default: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument("--description-chars", type=int, default=1600, help="Max JD/payload chars appended to the training text.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train split ratio.")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic split seed.")
    args = parser.parse_args()

    sqlite_db = Path(args.sqlite_db)
    out_dir = Path(args.out_dir)
    summary = export_dataset(
        sqlite_db=sqlite_db,
        out_dir=out_dir,
        description_chars=max(200, int(args.description_chars)),
        train_ratio=max(0.5, min(0.95, float(args.train_ratio))),
        val_ratio=max(0.0, min(0.3, float(args.val_ratio))),
        seed=int(args.seed),
    )
    summary["repo_root"] = str(DEFAULT_REPO_ROOT)
    summary["resolved_sqlite_db"] = str(sqlite_db.resolve())
    summary["resolved_out_dir"] = str(out_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
