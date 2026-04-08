from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import (  # noqa: E402
    DB_PATH,
    TUNING_ENABLE_INTERVIEW_PREDICTION,
    TUNING_PREDICT_QA_BACKEND,
    TUNING_PREDICT_QA_MAX_JOBS,
    TUNING_PREDICT_QA_MODEL,
    TUNING_PREDICT_QA_OUT_N,
    TUNING_PREDICT_QA_QUESTION_BANK_VERSION,
    TUNING_PREDICT_QA_TOP_K,
    TUNING_PREDICT_QA_USE_VET_PASS,
)

from .contracts import CandidateJob
from .job_loader import build_custom_jobs, decode_jd_texts, load_jobs
from .llm import chat_backend
from .prompts import build_generation_prompt, build_vet_prompt
from .ranking import rank_question_bank, retrieve_evidence_chunks
from .reporting import write_job_result, write_summary
from .schema import parse_json_message, validate_prediction_payload
from .storage import (
    JsonlLogger,
    build_prediction_cache_key,
    cache_get_json,
    cache_put_json,
    now_stamp,
    open_cache_db,
    resolve_output_root,
    shutdown_after_completion,
)


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the CLI parser used by the prediction entrypoint."""
    parser = argparse.ArgumentParser(description="Nightly interview Q&A prediction using local Qwen backends.")
    parser.add_argument("--mode", default="nightly")
    parser.add_argument("--job-id", action="append", dest="job_ids", type=int, default=[])
    parser.add_argument("--jd-text-base64", action="append", dest="jd_text_base64", default=[])
    parser.add_argument("--limit", type=int, default=TUNING_PREDICT_QA_MAX_JOBS)
    parser.add_argument("--recent-days", type=int, default=14)
    parser.add_argument("--cv-path", default="input/full_doc_stlye.txt")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--shutdown-when-completed", action="store_true")
    return parser


def _predict_job(job: CandidateJob, *, cache_conn: Any, output_dir: Path, logger: JsonlLogger) -> dict[str, Any]:
    """Generate interview Q&A for one job with cached light-ranking inputs."""
    questions = rank_question_bank(job, top_k=TUNING_PREDICT_QA_TOP_K, out_n=TUNING_PREDICT_QA_OUT_N)
    evidence_chunks = retrieve_evidence_chunks(job, questions)
    evidence_ids = {chunk.chunk_id for chunk in evidence_chunks}
    cache_key = build_prediction_cache_key(
        str(job.job_id),
        TUNING_PREDICT_QA_MODEL,
        TUNING_PREDICT_QA_BACKEND,
        TUNING_PREDICT_QA_QUESTION_BANK_VERSION,
        hashlib.sha256(job.cv_text.encode("utf-8")).hexdigest(),
        hashlib.sha256(job.jd_text.encode("utf-8")).hexdigest(),
    )
    cached = cache_get_json(cache_conn, cache_key)
    if cached is not None:
        logger.event({"stage": "predict_qa", "job_id": job.job_id, "cache_hit": True, "out_n": len(cached.get("qa", []))})
        return cached

    prompt = build_generation_prompt(job, questions, evidence_chunks)
    started = time.perf_counter()
    generated_raw = chat_backend(backend=TUNING_PREDICT_QA_BACKEND, model=TUNING_PREDICT_QA_MODEL, prompt=prompt)
    generated = validate_prediction_payload(parse_json_message(generated_raw), valid_evidence_ids=evidence_ids)
    total_ms = (time.perf_counter() - started) * 1000.0
    logger.event(
        {
            "stage": "predict_generate",
            "job_id": job.job_id,
            "cache_hit": False,
            "total_ms": round(total_ms, 3),
            "prompt_eval_count": int(generated_raw.get("prompt_eval_count") or 0),
            "eval_count": int(generated_raw.get("eval_count") or 0),
            "total_duration": int(generated_raw.get("total_duration") or 0),
            "load_duration": int(generated_raw.get("load_duration") or 0),
            "eval_duration": int(generated_raw.get("eval_duration") or 0),
        }
    )

    vetted = generated
    vet_metrics: dict[str, Any] = {}
    if TUNING_PREDICT_QA_USE_VET_PASS and generated.get("qa"):
        vet_prompt = build_vet_prompt(generated, evidence_chunks)
        vet_started = time.perf_counter()
        vet_raw = chat_backend(backend=TUNING_PREDICT_QA_BACKEND, model=TUNING_PREDICT_QA_MODEL, prompt=vet_prompt)
        vetted = validate_prediction_payload(parse_json_message(vet_raw), valid_evidence_ids=evidence_ids)
        vet_metrics = {
            "vet_total_ms": round((time.perf_counter() - vet_started) * 1000.0, 3),
            "vet_total_duration": int(vet_raw.get("total_duration") or 0),
            "vet_eval_duration": int(vet_raw.get("eval_duration") or 0),
            "vet_prompt_eval_count": int(vet_raw.get("prompt_eval_count") or 0),
            "vet_eval_count": int(vet_raw.get("eval_count") or 0),
        }
        logger.event({"stage": "predict_vet", "job_id": job.job_id, **vet_metrics})

    result = {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "backend": TUNING_PREDICT_QA_BACKEND,
        "model": TUNING_PREDICT_QA_MODEL,
        "question_bank_version": TUNING_PREDICT_QA_QUESTION_BANK_VERSION,
        "questions": [item.to_dict() for item in questions],
        "evidence_chunks": [chunk.to_public_dict() for chunk in evidence_chunks],
        "qa": vetted.get("qa", []),
        "metrics": {
            "generate_total_ms": round(total_ms, 3),
            "generate_total_duration": int(generated_raw.get("total_duration") or 0),
            "generate_load_duration": int(generated_raw.get("load_duration") or 0),
            "generate_eval_duration": int(generated_raw.get("eval_duration") or 0),
            "generate_prompt_eval_count": int(generated_raw.get("prompt_eval_count") or 0),
            "generate_eval_count": int(generated_raw.get("eval_count") or 0),
            **vet_metrics,
        },
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    cache_put_json(cache_conn, cache_key, result)
    write_job_result(output_dir, result)
    return result


def run_from_namespace(args: argparse.Namespace) -> int:
    """Execute the prediction workflow from parsed CLI arguments."""
    if not TUNING_ENABLE_INTERVIEW_PREDICTION and not args.force:
        print("[PREDICT] skipped disabled_by_flag", flush=True)
        return 0

    db_path = Path(DB_PATH).resolve()
    cv_path = Path(args.cv_path)
    if not cv_path.is_absolute():
        cv_path = (PROJECT_ROOT / cv_path).resolve()
    cv_text = cv_path.read_text(encoding="utf-8", errors="ignore") if cv_path.exists() else ""

    output_dir = resolve_output_root() / now_stamp()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonlLogger(output_dir / "events.jsonl")
    cache_conn = open_cache_db()
    try:
        jobs = load_jobs(
            db_path=db_path,
            cv_path=cv_path,
            limit=max(1, int(args.limit)),
            recent_days=max(0, int(args.recent_days)),
            job_ids=list(args.job_ids or []),
            cv_text=cv_text,
        )
        custom_jd_texts = decode_jd_texts(list(args.jd_text_base64 or []))
        custom_jobs = build_custom_jobs(custom_jd_texts, cv_text)
        jobs.extend(custom_jobs)
        if not jobs:
            print("[PREDICT] skipped no jobs requested", flush=True)
            return 0
        summary: dict[str, Any] = {
            "mode": str(args.mode),
            "job_count": len(jobs),
            "backend": TUNING_PREDICT_QA_BACKEND,
            "model": TUNING_PREDICT_QA_MODEL,
            "custom_job_count": len(custom_jobs),
            "output_dir": str(output_dir),
            "generated_files": [],
        }
        print(f"[PREDICT] jobs={len(jobs)} backend={TUNING_PREDICT_QA_BACKEND} model={TUNING_PREDICT_QA_MODEL}", flush=True)
        for idx, job in enumerate(jobs, start=1):
            result = _predict_job(job, cache_conn=cache_conn, output_dir=output_dir, logger=logger)
            summary["generated_files"].append(f"job_{job.job_id}.json")
            print(f"[PREDICT] completed {idx}/{len(jobs)} job_id={job.job_id} qa_n={len(result.get('qa', []))}", flush=True)
        write_summary(output_dir, summary)
        if args.shutdown_when_completed:
            print("[PREDICT] shutdown requested after completion", flush=True)
            shutdown_after_completion()
        return 0
    finally:
        try:
            cache_conn.close()
        except Exception:
            pass
        logger.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for manual and scheduled interview prediction runs."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_from_namespace(args)
