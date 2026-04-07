from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

from linkedin_jobs_jd import (
    HEADERS,
    LINKEDIN_NOISE_MARKERS,
    _canonical_job_url,
    _today_utc_date,
    backfill_job_detail_validations,
    connect_sqlite,
    evaluate_missing_fit_scores,
    extract_job_details_from_url,
    init_sqlite,
    save_rows_to_sqlite,
)


FRONTEND_ONLY_LANGUAGES = {"CSS", "HTML", "JavaScript", "TypeScript"}
BACKEND_TITLE_TOKENS = ("backend", "back-end", "backend-leaning")
PAUSE_EXIT_CODE = 2
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAUSE_DIR = PROJECT_ROOT / "tmp_seek_automation" / "pauses"
CHECKPOINT_DIR = PROJECT_ROOT / "tmp_seek_automation" / "checkpoints"


def _current_automation_run_id() -> str:
    return str(os.getenv("AUTOMATION_RUN_ID", "") or "").strip()


def _pause_flag_path(run_id: str) -> Path:
    return PAUSE_DIR / f"run_{run_id}.pause"


def _pause_requested() -> bool:
    run_id = _current_automation_run_id()
    if not run_id:
        return False
    return _pause_flag_path(run_id).exists()


def _checkpoint_path(action_type: str) -> Path:
    run_id = _current_automation_run_id() or "unknown"
    safe_action = str(action_type or "unknown").strip().lower()
    return CHECKPOINT_DIR / f"run_{run_id}_{safe_action}.json"


def _write_checkpoint(payload: dict) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path("repair_recent_jobs")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _pause_and_exit(payload: dict, reason: str) -> None:
    payload = dict(payload)
    payload["pause_reason"] = reason
    payload["paused_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload["run_id"] = _current_automation_run_id()
    checkpoint_path = _write_checkpoint(payload)
    print(f"[PAUSE] reason={reason} checkpoint={checkpoint_path}", flush=True)
    raise SystemExit(PAUSE_EXIT_CODE)


def _load_checkpoint(path: str) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid checkpoint payload")
    return data


def _build_save_args(db_path: Path, recent_days: int, constraint_mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        mode="repair_recent_jobs",
        url=f"repair_recent_jobs://window_days/{recent_days}",
        input_jobs_json="",
        max_jobs=0,
        output_json=str((db_path.parent / "repair_recent_jobs.json").resolve()),
        output_csv=str((db_path.parent / "repair_recent_jobs.csv").resolve()),
        sqlite_db=str(db_path.resolve()),
        constraint_mode=constraint_mode,
    )


def _load_recent_rows(conn, recent_days: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=max(0, recent_days))).isoformat()
    rows = conn.execute(
        """
        SELECT
          jp.id,
          jp.linkedin_job_id,
          jp.job_url,
          jp.job_url_final,
          jp.title,
          jp.company,
          jp.location,
          jp.last_seen_date,
          jp.normalized_work_model,
          jp.normalized_employment_type,
          jp.latest_payload_json,
          COALESCE(jfs.total_score, 0) AS fit_total_score,
          COALESCE(jfs.main_issue, '') AS main_issue,
          COALESCE(jfs.fit_reason_medium, '') AS fit_reason_medium,
          COALESCE(jfs.fit_reason_hard, '') AS fit_reason_hard,
          COALESCE((
            SELECT GROUP_CONCAT(language, ', ')
            FROM job_programming_languages jpl
            WHERE jpl.job_post_id = jp.id
            ORDER BY language
          ), '') AS stored_languages
        FROM job_posts jp
        LEFT JOIN job_fit_scores jfs
          ON jfs.job_post_id = jp.id
         AND jfs.cv_profile = 'full_doc_stlye'
        WHERE COALESCE(NULLIF(TRIM(jp.last_seen_date), ''), jp.first_seen_date) >= ?
        ORDER BY jp.last_seen_date DESC, jp.id DESC
        """,
        (cutoff,),
    ).fetchall()
    return [dict(row) for row in rows]


def _split_languages(raw_value: str) -> set[str]:
    return {token.strip() for token in str(raw_value or "").split(",") if token.strip()}


def _detect_repair_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    try:
        payload = json.loads(str(row.get("latest_payload_json") or "{}"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    full_page_text = str(payload.get("full_page_text") or "")
    about_job = str(payload.get("about_job") or "")
    description = str(payload.get("description") or "")
    lowered_full_page = full_page_text.lower()

    if any(marker.lower() in lowered_full_page for marker in LINKEDIN_NOISE_MARKERS):
        reasons.append("full_page_noise")
    if full_page_text.strip() and not about_job.strip() and not description.strip():
        reasons.append("full_page_only")

    languages = _split_languages(str(row.get("stored_languages") or ""))
    title_lower = str(row.get("title") or "").lower()
    work_model = str(row.get("normalized_work_model") or "").strip().lower()
    employment_type = str(row.get("normalized_employment_type") or "").strip().lower()

    if work_model in {"", "-", "unknown"}:
        reasons.append("missing_work_model")
    if employment_type in {"", "-", "unknown"}:
        reasons.append("missing_employment_type")
    if not languages and (
        any(token in title_lower for token in ("engineer", "developer", "backend", "frontend", "full stack", "ai"))
        or any(token in lowered_full_page for token in ("python", "typescript", "javascript", "java", "golang", "go ", "ruby"))
    ):
        reasons.append("missing_programming_languages")

    if any(token in title_lower for token in BACKEND_TITLE_TOKENS):
        if languages and languages.issubset(FRONTEND_ONLY_LANGUAGES):
            reasons.append("backend_title_frontend_only_languages")

    main_issue = str(row.get("main_issue") or "").lower()
    fit_reason_medium = str(row.get("fit_reason_medium") or "").lower()
    fit_reason_hard = str(row.get("fit_reason_hard") or "").lower()
    fit_total_score = float(row.get("fit_total_score") or 0.0)

    if work_model == "hybrid" and "lacks flexible/remote signals" in fit_reason_medium:
        reasons.append("hybrid_fit_constraint_stale")

    remote_mismatch = (
        "lacks remote signal" in fit_reason_hard
        or "lacks flexible/remote signals" in fit_reason_medium
        or ("remote signal" in main_issue and "constraint" in main_issue)
    )
    if work_model == "on_site" and remote_mismatch:
        reasons.append("on_site_fit_constraint_stale")
    if work_model in {"", "-", "unknown"} and (
        "flexible or remote-friendly setup" in fit_reason_medium
        or "remote-friendly setup" in fit_reason_medium
        or "flexible or remote-friendly setup" in fit_reason_hard
    ):
        reasons.append("missing_work_model_fit_pass_mismatch")
    if fit_total_score > 0 and "http 429" in str(payload.get("error") or "").lower():
        reasons.append("payload_rate_limited")

    return reasons


def _select_candidates(rows: list[dict[str, Any]], targeted_only: bool) -> tuple[list[dict[str, Any]], dict[str, int]]:
    summary = {
        "scanned": len(rows),
        "affected": 0,
        "full_page_noise": 0,
        "full_page_only": 0,
        "missing_work_model": 0,
        "missing_employment_type": 0,
        "missing_programming_languages": 0,
        "backend_title_frontend_only_languages": 0,
        "hybrid_fit_constraint_stale": 0,
        "on_site_fit_constraint_stale": 0,
        "missing_work_model_fit_pass_mismatch": 0,
        "payload_rate_limited": 0,
    }
    candidates: list[dict[str, Any]] = []
    for row in rows:
        reasons = _detect_repair_reasons(row)
        if reasons:
            item = dict(row)
            item["repair_reasons"] = reasons
            candidates.append(item)
            summary["affected"] += 1
            for reason in reasons:
                if reason in summary:
                    summary[reason] += 1
        elif not targeted_only:
            item = dict(row)
            item["repair_reasons"] = ["recent_window"]
            candidates.append(item)
    return candidates, summary


def _refresh_candidate_rows(
    candidates: list[dict[str, Any]],
    *,
    sleep_seconds: float,
    start_index: int = 0,
    refreshed_rows: list[dict[str, Any]] | None = None,
    refresh_failed: int = 0,
    pause_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    session = requests.Session()
    session.headers.update(HEADERS)
    refreshed_rows = list(refreshed_rows or [])
    failed = int(refresh_failed or 0)

    for idx, row in enumerate(candidates, start=1):
        if idx <= start_index:
            continue
        job_url = _canonical_job_url(
            str(row.get("job_url_final") or ""),
            str(row.get("job_url") or ""),
            str(row.get("linkedin_job_id") or ""),
        )
        details: dict[str, Any] = {}
        for attempt in range(1, 4):
            details = extract_job_details_from_url(
                session=session,
                job_url=job_url,
                title_fallback=str(row.get("title") or ""),
                company_fallback=str(row.get("company") or ""),
                location_fallback=str(row.get("location") or ""),
            )
            error_text = str(details.get("error") or "").strip()
            if error_text != "HTTP 429":
                break
            # Add jitter so the requests do not align and trigger burst limits.
            backoff_seconds = min(30.0, float(attempt * 3) + random.uniform(0.25, 1.75))
            print(
                f"[REPAIR] rate_limited {idx}/{len(candidates)} job_id={row.get('linkedin_job_id')} attempt={attempt} wait_s={backoff_seconds:.1f}",
                flush=True,
            )
            time.sleep(backoff_seconds)
        if str(details.get("error") or "").strip():
            failed += 1
            print(
                f"[REPAIR] refresh_failed {idx}/{len(candidates)} job_id={row.get('linkedin_job_id')} error={details.get('error')}",
                flush=True,
            )
            if _pause_requested():
                resume_payload = {
                    "phase": "refresh_candidates",
                    "resume_index": idx,
                    "candidates": candidates,
                    "refreshed_rows": refreshed_rows,
                    "refresh_failed": failed,
                }
                if pause_context:
                    resume_payload.update(pause_context)
                _pause_and_exit(resume_payload, reason="pause_requested_after_refresh_failure")
            continue
        refreshed = {
            "index": str(idx - 1),
            "title": str(row.get("title") or ""),
            "company": str(row.get("company") or ""),
            "location": str(row.get("location") or ""),
            "job_url": job_url,
        }
        refreshed.update(details)
        refreshed_rows.append(refreshed)
        print(
            f"[REPAIR] refreshed {idx}/{len(candidates)} job_id={row.get('linkedin_job_id')} reasons={','.join(row.get('repair_reasons') or [])}",
            flush=True,
        )
        if _pause_requested():
            resume_payload = {
                "phase": "refresh_candidates",
                "resume_index": idx,
                "candidates": candidates,
                "refreshed_rows": refreshed_rows,
                "refresh_failed": failed,
            }
            if pause_context:
                resume_payload.update(pause_context)
            _pause_and_exit(resume_payload, reason="pause_requested_during_refresh")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return refreshed_rows, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Targeted nightly repair for recent LinkedIn job payload/data issues.")
    parser.add_argument("--sqlite-db", default="input/crawled_job/linkedin_jobs_jd.sqlite", help="SQLite DB path")
    parser.add_argument("--cv-path", default="input/full_doc_stlye.txt", help="CV path for fit re-evaluation")
    parser.add_argument("--recent-days", type=int, default=15, help="Recent window in days")
    parser.add_argument("--constraint-mode", default="medium", help="Constraint mode for fit re-evaluation")
    parser.add_argument("--targeted-only", action="store_true", help="Repair only jobs that match heuristics")
    parser.add_argument("--disable-llm", action="store_true", help="Disable LLM detail validation during repair")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Delay between job detail refresh requests")
    parser.add_argument("--max-candidates", type=int, default=60, help="Cap number of jobs refreshed in one run")
    parser.add_argument("--resume-checkpoint", default="", help="Resume from a checkpoint JSON file")
    args = parser.parse_args()

    resume_checkpoint = str(args.resume_checkpoint or "").strip()
    if resume_checkpoint:
        checkpoint = _load_checkpoint(resume_checkpoint)
        phase = str(checkpoint.get("phase") or "").strip().lower()
        db_path = Path(checkpoint.get("db_path") or args.sqlite_db).resolve()
        cv_path = Path(checkpoint.get("cv_path") or args.cv_path).resolve()
        recent_days = max(1, int(checkpoint.get("recent_days") or args.recent_days))
        constraint_mode = str(checkpoint.get("constraint_mode") or args.constraint_mode or "medium")
        targeted_only = bool(checkpoint.get("targeted_only", args.targeted_only))
        disable_llm = bool(checkpoint.get("disable_llm", args.disable_llm))
        sleep_seconds = float(checkpoint.get("sleep_seconds") or args.sleep_seconds)
        candidates = list(checkpoint.get("candidates") or [])
        refreshed_rows = list(checkpoint.get("refreshed_rows") or [])
        refresh_failed = int(checkpoint.get("refresh_failed") or 0)
        resume_index = int(checkpoint.get("resume_index") or 0)
        if phase not in {"refresh_candidates", "pre_save"}:
            raise ValueError(f"Unsupported resume phase: {phase}")
        if phase == "refresh_candidates":
            refreshed_rows, refresh_failed = _refresh_candidate_rows(
                candidates,
                sleep_seconds=max(0.0, sleep_seconds),
                start_index=resume_index,
                refreshed_rows=refreshed_rows,
                refresh_failed=refresh_failed,
                pause_context={
                    "db_path": str(db_path),
                    "cv_path": str(cv_path),
                    "recent_days": recent_days,
                    "constraint_mode": constraint_mode,
                    "targeted_only": targeted_only,
                    "disable_llm": disable_llm,
                    "sleep_seconds": sleep_seconds,
                },
            )
        if _pause_requested():
            resume_payload = {
                "phase": "pre_save",
                "db_path": str(db_path),
                "cv_path": str(cv_path),
                "recent_days": recent_days,
                "constraint_mode": constraint_mode,
                "targeted_only": targeted_only,
                "disable_llm": disable_llm,
                "sleep_seconds": sleep_seconds,
                "candidates": candidates,
                "refreshed_rows": refreshed_rows,
                "refresh_failed": refresh_failed,
            }
            _pause_and_exit(resume_payload, reason="pause_requested_before_save")
        args.sqlite_db = str(db_path)
        args.cv_path = str(cv_path)
        args.recent_days = int(recent_days)
        args.constraint_mode = constraint_mode
        args.targeted_only = bool(targeted_only)
        args.disable_llm = bool(disable_llm)
        args.sleep_seconds = float(sleep_seconds)
    else:
        db_path = Path(args.sqlite_db).resolve()
        cv_path = Path(args.cv_path).resolve()
        recent_days = max(1, int(args.recent_days))
        targeted_only = bool(args.targeted_only)

    if not resume_checkpoint:
        conn = connect_sqlite(db_path)
        try:
            init_sqlite(conn)
            recent_rows = _load_recent_rows(conn, recent_days)
        finally:
            conn.close()

        candidates, summary = _select_candidates(recent_rows, targeted_only=targeted_only)
        max_candidates = max(1, int(args.max_candidates))
        if len(candidates) > max_candidates:
            candidates = candidates[:max_candidates]
            print(f"[REPAIR] limiting candidates to first {max_candidates} of {summary['affected']} (ordered by last_seen_date)", flush=True)
        print(
            f"[REPAIR] scanned={summary['scanned']} affected={summary['affected']} "
            f"noise={summary['full_page_noise']} full_page_only={summary['full_page_only']} "
            f"missing_work_model={summary['missing_work_model']} "
            f"missing_languages={summary['missing_programming_languages']} "
            f"backend_lang={summary['backend_title_frontend_only_languages']} "
            f"hybrid_fit={summary['hybrid_fit_constraint_stale']} on_site_fit={summary['on_site_fit_constraint_stale']} "
            f"fit_pass_mismatch={summary['missing_work_model_fit_pass_mismatch']} rate_limited={summary['payload_rate_limited']}",
            flush=True,
        )

        if not candidates:
            print("[REPAIR] no candidates matched repair heuristics", flush=True)
            return 0

        refreshed_rows, refresh_failed = _refresh_candidate_rows(
            candidates,
            sleep_seconds=max(0.0, float(args.sleep_seconds)),
            pause_context={
                "db_path": str(db_path),
                "cv_path": str(cv_path),
                "recent_days": recent_days,
                "constraint_mode": str(args.constraint_mode or "medium"),
                "targeted_only": targeted_only,
                "disable_llm": bool(args.disable_llm),
                "sleep_seconds": float(args.sleep_seconds),
            },
        )
        if not refreshed_rows:
            print(f"[REPAIR] no rows refreshed successfully refresh_failed={refresh_failed}", flush=True)
            return 0
        if _pause_requested():
            resume_payload = {
                "phase": "pre_save",
                "db_path": str(db_path),
                "cv_path": str(cv_path),
                "recent_days": recent_days,
                "constraint_mode": str(args.constraint_mode or "medium"),
                "targeted_only": targeted_only,
                "disable_llm": bool(args.disable_llm),
                "sleep_seconds": float(args.sleep_seconds),
                "candidates": candidates,
                "refreshed_rows": refreshed_rows,
                "refresh_failed": refresh_failed,
            }
            _pause_and_exit(resume_payload, reason="pause_requested_before_save")

    original_disable_llm = os.environ.get("DETAIL_VALIDATION_DISABLE_LLM")
    if args.disable_llm:
        os.environ["DETAIL_VALIDATION_DISABLE_LLM"] = "1"

    try:
        db_stats = save_rows_to_sqlite(
            refreshed_rows,
            db_path,
            _build_save_args(db_path, recent_days=recent_days, constraint_mode=str(args.constraint_mode or "medium")),
            _today_utc_date(),
        )

        conn = connect_sqlite(db_path)
        try:
            init_sqlite(conn)
            detail_stats = backfill_job_detail_validations(
                conn,
                job_post_ids=list(db_stats.get("touched_job_post_ids") or []),
                force=True,
            )
        finally:
            conn.close()

        fit_stats = evaluate_missing_fit_scores(
            db_path=db_path,
            cv_path=cv_path,
            include_existing=True,
            constraint_mode=str(args.constraint_mode or "medium"),
            job_post_ids=list(db_stats.get("touched_job_post_ids") or []),
        )
    finally:
        if args.disable_llm:
            if original_disable_llm is None:
                os.environ.pop("DETAIL_VALIDATION_DISABLE_LLM", None)
            else:
                os.environ["DETAIL_VALIDATION_DISABLE_LLM"] = original_disable_llm

    print(
        f"[REPAIR] refreshed_ok={len(refreshed_rows)} refresh_failed={refresh_failed} "
        f"revalidated={detail_stats.get('updated', 0)} refit={fit_stats.get('evaluated', 0)} "
        f"touched_job_posts={len(list(db_stats.get('touched_job_post_ids') or []))}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
