from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import (  # noqa: E402
    DB_PATH,
    TUNING_CACHE_DB_PATH,
    TUNING_CACHE_SQLITE_WAL,
    TUNING_ENABLE_INTERVIEW_PREDICTION,
    TUNING_PREDICT_QA_BACKEND,
    TUNING_PREDICT_QA_KEEP_ALIVE,
    TUNING_PREDICT_QA_LOG_DIR,
    TUNING_PREDICT_QA_MAX_JOBS,
    TUNING_PREDICT_QA_MODEL,
    TUNING_PREDICT_QA_OUT_N,
    TUNING_PREDICT_QA_OUTPUT_FORMAT,
    TUNING_PREDICT_QA_QUESTION_BANK_VERSION,
    TUNING_PREDICT_QA_TOP_K,
    TUNING_PREDICT_QA_USE_VET_PASS,
)
from app.services.text_vector_utils import build_hashed_embedding, cosine_similarity, split_text_chunks  # noqa: E402


QUESTION_BANK: list[dict[str, str]] = [
    {"id": "architecture", "question": "How would you explain the architecture trade-offs for this role?"},
    {"id": "ownership", "question": "What project ownership example best matches this job?"},
    {"id": "performance", "question": "Which performance optimization story best fits this JD?"},
    {"id": "debugging", "question": "Describe a debugging or incident response example relevant to this position."},
    {"id": "api_design", "question": "What API design or backend integration example should be highlighted?"},
    {"id": "automation", "question": "Which automation workflow experience is most relevant here?"},
    {"id": "testing", "question": "How would you answer questions about testing and regression prevention?"},
    {"id": "llm", "question": "How should you describe local LLM or AI-assist work for this role?"},
    {"id": "sqlite", "question": "What SQLite or data consistency example is strongest for this JD?"},
    {"id": "delivery", "question": "Which delivery under constraints example best matches the role?"},
    {"id": "learning", "question": "How would you describe learning speed for adjacent stacks in this position?"},
    {"id": "collaboration", "question": "Which collaboration story best proves fit for this job?"},
]


@dataclass
class CandidateJob:
    job_id: int
    title: str
    company: str
    location: str
    jd_text: str
    cv_text: str


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        # English: Keep an append-only JSONL log for repeatable nightly job analysis.
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = self.path.open("a", encoding="utf-8")

    def event(self, payload: dict[str, Any]) -> None:
        # English: Emit one JSON object per line so offline aggregation remains simple.
        self.fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.fp.flush()

    def close(self) -> None:
        # English: Close the file handle safely when the run finishes.
        try:
            self.fp.close()
        except Exception:
            pass


def _resolve_output_root() -> Path:
    # English: Resolve prediction output root inside the workspace for both manual and scheduled runs.
    root = Path(TUNING_PREDICT_QA_LOG_DIR)
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    return root


def _now_stamp() -> str:
    # English: Keep output folders sortable by time.
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _open_cache_db() -> sqlite3.Connection:
    # English: Reuse the tuning cache DB so prediction results stay cheap on repeated nightly runs.
    cache_path = Path(TUNING_CACHE_DB_PATH)
    if not cache_path.is_absolute():
        cache_path = (PROJECT_ROOT / cache_path).resolve()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cache_path), timeout=30.0)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v BLOB, ts INTEGER)")
    if TUNING_CACHE_SQLITE_WAL:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _cache_get_json(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    # English: Read cached JSON payload for a stable prediction input hash.
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    if not row or row[0] in (None, ""):
        return None
    try:
        parsed = json.loads(str(row[0]))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _cache_put_json(conn: sqlite3.Connection, key: str, payload: dict[str, Any]) -> None:
    # English: Persist prediction output so the next nightly run can skip unchanged inputs.
    ts = int(time.time())
    conn.execute(
        "INSERT INTO kv(k, v, ts) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, ts = excluded.ts",
        (key, json.dumps(payload, ensure_ascii=False), ts),
    )
    conn.commit()


def _load_jobs(*, db_path: Path, cv_path: Path, limit: int, recent_days: int, job_ids: list[int], cv_text: str | None = None) -> list[CandidateJob]:
    # English: Load candidate jobs with JD text from SQLite without changing existing job workflows.
    if cv_text is None:
        cv_text = cv_path.read_text(encoding="utf-8", errors="ignore") if cv_path.exists() else ""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        params: list[Any] = []
        where_parts = ["COALESCE(TRIM(jjc.jd_text), '') <> ''"]
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            where_parts.append(f"jp.id IN ({placeholders})")
            params.extend(int(x) for x in job_ids)
        else:
            cutoff = (datetime.now().date() - timedelta(days=max(0, recent_days))).isoformat()
            where_parts.append("COALESCE(NULLIF(TRIM(jp.last_seen_date), ''), jp.first_seen_date) >= ?")
            params.append(cutoff)
        params.append(max(1, limit))
        rows = conn.execute(
            f"""
            SELECT
              jp.id,
              COALESCE(jp.title, '') AS title,
              COALESCE(jp.company, '') AS company,
              COALESCE(jp.location, '') AS location,
              COALESCE(jjc.jd_text, '') AS jd_text
            FROM job_posts jp
            JOIN (
              SELECT jo.job_post_id, MAX(jo.id) AS latest_observation_id
              FROM job_observations jo
              GROUP BY jo.job_post_id
            ) latest ON latest.job_post_id = jp.id
            JOIN job_jd_contents jjc ON jjc.observation_id = latest.latest_observation_id
            WHERE {" AND ".join(where_parts)}
            ORDER BY COALESCE(jp.last_seen_date, '') DESC, jp.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [
            CandidateJob(
                job_id=int(row["id"]),
                title=str(row["title"] or "").strip(),
                company=str(row["company"] or "").strip(),
                location=str(row["location"] or "").strip(),
                jd_text=str(row["jd_text"] or "").strip(),
                cv_text=cv_text,
            )
            for row in rows
        ]
    finally:
        conn.close()


def _decode_jd_texts(encoded_texts: list[str]) -> list[str]:
    decoded: list[str] = []
    for raw in encoded_texts or []:
        if not raw or not isinstance(raw, str):
            continue
        try:
            text = base64.b64decode(raw, validate=True).decode('utf-8', errors='ignore')
        except Exception:
            continue
        trimmed = str(text or "").strip()
        if trimmed:
            decoded.append(trimmed)
    return decoded


def _custom_job_id(text: str, index: int) -> int:
    hashed = hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]
    numeric = int(hashed, 16) if hashed else index
    candidate = (numeric & 0x7FFFFFFF) + index
    return candidate if candidate > 0 else index


def _build_custom_jobs(jd_texts: list[str], cv_text: str) -> list[CandidateJob]:
    jobs: list[CandidateJob] = []
    for idx, text in enumerate(jd_texts, start=1):
        jobs.append(
            CandidateJob(
                job_id=_custom_job_id(text, idx),
                title=f"Custom JD #{idx}",
                company="Manual input",
                location="Manual input",
                jd_text=text,
                cv_text=cv_text,
            )
        )
    return jobs


def _rank_question_bank(job: CandidateJob, *, top_k: int, out_n: int) -> list[dict[str, str]]:
    # English: Use cheap embedding similarity to shortlist interview question themes for this JD plus CV pair.
    query_text = "\n".join([job.title, job.company, job.jd_text[:4000], job.cv_text[:2500]]).strip()
    query_vec = build_hashed_embedding(query_text)
    ranked: list[tuple[float, dict[str, str]]] = []
    for item in QUESTION_BANK:
        score = cosine_similarity(query_vec, build_hashed_embedding(item["question"]))
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    shortlisted = [item for _score, item in ranked[: max(1, top_k)]]
    return shortlisted[: max(1, out_n)]


def _retrieve_evidence_chunks(job: CandidateJob, questions: list[dict[str, str]]) -> list[dict[str, Any]]:
    # English: Retrieve a small set of JD/CV evidence chunks per shortlisted question to ground generation.
    chunks: list[dict[str, Any]] = []
    for source_name, text in [("jd", job.jd_text), ("cv", job.cv_text)]:
        for idx, chunk in enumerate(split_text_chunks(text, max_chars=700, overlap_chars=100)):
            if chunk.strip():
                chunks.append({"source": source_name, "chunk_id": f"{source_name}_{idx}", "text": chunk})
    if not chunks:
        return []
    selected: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for question in questions:
        qvec = build_hashed_embedding(question["question"])
        ranked = sorted(
            (
                (cosine_similarity(qvec, build_hashed_embedding(chunk["text"])), chunk)
                for chunk in chunks
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for _score, chunk in ranked[:3]:
            chunk_id = str(chunk["chunk_id"])
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            selected.append(chunk)
    return selected


def _build_generation_prompt(job: CandidateJob, questions: list[dict[str, str]], evidence_chunks: list[dict[str, Any]]) -> str:
    # English: Keep the generation prompt compact and evidence-linked for weak CPU-only local inference.
    evidence_lines = []
    for chunk in evidence_chunks:
        evidence_lines.append(f"[{chunk['chunk_id']}] ({chunk['source']}) {str(chunk['text'])[:500]}")
    question_lines = [f"- {item['question']}" for item in questions]
    return (
        "Return JSON only with shape "
        "{\"qa\":[{\"question\":\"...\",\"answer\":\"...\",\"evidence_ids\":[\"jd_0\"],\"confidence\":\"high|medium|low\"}]}"
        "\nUse only the evidence below and never invent experience not present in CV/JD.\n\n"
        f"ROLE:\nTitle: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n\n"
        "SHORTLISTED_QUESTIONS:\n"
        + "\n".join(question_lines)
        + "\n\nEVIDENCE:\n"
        + "\n".join(evidence_lines)
    )


def _build_vet_prompt(generated: dict[str, Any], evidence_chunks: list[dict[str, Any]]) -> str:
    # English: Run a second low-temperature pass to downgrade unsupported claims and keep answers grounded.
    evidence_lines = [f"[{chunk['chunk_id']}] {str(chunk['text'])[:500]}" for chunk in evidence_chunks]
    return (
        "Review the generated interview Q&A. Return JSON only with the same shape. "
        "Remove unsupported claims, keep evidence_ids valid, and lower confidence when evidence is weak.\n\n"
        f"CANDIDATE_QA:\n{json.dumps(generated, ensure_ascii=False)}\n\n"
        "EVIDENCE:\n"
        + "\n".join(evidence_lines)
    )


def _ollama_chat(*, model: str, prompt: str, keep_alive: str) -> dict[str, Any]:
    # English: Call Ollama chat API and return raw response for timing and token metrics logging.
    base_url = (os.getenv("OLLAMA_BASE_URL") or os.getenv("LLM_UPSTREAM_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json" if TUNING_PREDICT_QA_OUTPUT_FORMAT == "json" else None,
        "options": {"temperature": 0},
        "keep_alive": keep_alive,
        "stream": False,
    }
    response = requests.post(f"{base_url}/api/chat", json=payload, timeout=600)
    response.raise_for_status()
    return response.json()


def _llama_cpp_chat(*, model: str, prompt: str) -> dict[str, Any]:
    # English: Support llama.cpp OpenAI-compatible API when the local backend is not Ollama.
    base_url = str(os.getenv("LLAMA_CPP_BASE_URL") or "http://127.0.0.1:8080/v1").rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=600)
    response.raise_for_status()
    body = response.json()
    content = (
        body.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "{}")
    )
    return {
        "message": {"content": content},
        "total_duration": 0,
        "load_duration": 0,
        "eval_duration": 0,
        "prompt_eval_count": int(body.get("usage", {}).get("prompt_tokens") or 0),
        "eval_count": int(body.get("usage", {}).get("completion_tokens") or 0),
    }


def _chat_backend(*, model: str, prompt: str) -> dict[str, Any]:
    # English: Dispatch local interview prediction calls to the configured backend without changing existing gateway flows.
    backend = TUNING_PREDICT_QA_BACKEND
    if backend == "ollama":
        return _ollama_chat(model=model, prompt=prompt, keep_alive=TUNING_PREDICT_QA_KEEP_ALIVE)
    if backend == "llama_cpp":
        return _llama_cpp_chat(model=model, prompt=prompt)
    raise ValueError(f"Unsupported prediction backend: {backend}")


def _shutdown_after_completion() -> None:
    # English: Allow a manual prediction run to power off the machine after artifacts are safely written.
    if os.name != "nt":
        return
    cmd = [
        "shutdown",
        "/s",
        "/t",
        "60",
        "/c",
        "Interview Q&A prediction completed.",
    ]
    subprocess.run(cmd, check=False)


def _parse_json_message(response_json: dict[str, Any]) -> dict[str, Any]:
    # English: Parse JSON content from local LLM responses while preserving empty-fallback behavior.
    content = str((response_json.get("message") or {}).get("content") or "{}").strip()
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {"qa": []}
    return parsed if isinstance(parsed, dict) else {"qa": []}


def _predict_job(job: CandidateJob, *, cache_conn: sqlite3.Connection, output_dir: Path, logger: JsonlLogger) -> dict[str, Any]:
    # English: Generate and optionally vet nightly interview Q&A for one job using cached evidence-aware prompts.
    questions = _rank_question_bank(job, top_k=TUNING_PREDICT_QA_TOP_K, out_n=TUNING_PREDICT_QA_OUT_N)
    evidence_chunks = _retrieve_evidence_chunks(job, questions)
    cache_key = "|".join(
        [
            "predict_qa",
            str(job.job_id),
            TUNING_PREDICT_QA_MODEL,
            TUNING_PREDICT_QA_BACKEND,
            TUNING_PREDICT_QA_QUESTION_BANK_VERSION,
            hashlib.sha256(job.cv_text.encode("utf-8")).hexdigest(),
            hashlib.sha256(job.jd_text.encode("utf-8")).hexdigest(),
        ]
    )
    cached = _cache_get_json(cache_conn, cache_key)
    if cached is not None:
        logger.event({"stage": "predict_qa", "job_id": job.job_id, "cache_hit": True, "out_n": len(cached.get("qa", []))})
        return cached

    prompt = _build_generation_prompt(job, questions, evidence_chunks)
    started = time.perf_counter()
    generated_raw = _chat_backend(model=TUNING_PREDICT_QA_MODEL, prompt=prompt)
    generated = _parse_json_message(generated_raw)
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
    vet_metrics = {}
    if TUNING_PREDICT_QA_USE_VET_PASS:
        vet_prompt = _build_vet_prompt(generated, evidence_chunks)
        vet_started = time.perf_counter()
        vet_raw = _chat_backend(model=TUNING_PREDICT_QA_MODEL, prompt=vet_prompt)
        vetted = _parse_json_message(vet_raw)
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
        "questions": questions,
        "evidence_chunks": [{"chunk_id": chunk["chunk_id"], "source": chunk["source"]} for chunk in evidence_chunks],
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
    _cache_put_json(cache_conn, cache_key, result)
    out_path = output_dir / f"job_{job.job_id}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly interview Q&A prediction using local Qwen/Ollama backends.")
    parser.add_argument("--mode", default="nightly")
    parser.add_argument("--job-id", action="append", dest="job_ids", type=int, default=[])
    parser.add_argument("--jd-text-base64", action="append", dest="jd_text_base64", default=[])
    parser.add_argument("--limit", type=int, default=TUNING_PREDICT_QA_MAX_JOBS)
    parser.add_argument("--recent-days", type=int, default=14)
    parser.add_argument("--cv-path", default="input/full_doc_stlye.txt")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--shutdown-when-completed", action="store_true")
    args = parser.parse_args()

    if not TUNING_ENABLE_INTERVIEW_PREDICTION and not args.force:
        print("[PREDICT] skipped disabled_by_flag", flush=True)
        return 0

    db_path = Path(DB_PATH).resolve()
    cv_path = Path(args.cv_path)
    if not cv_path.is_absolute():
        cv_path = (PROJECT_ROOT / cv_path).resolve()
    cv_text = cv_path.read_text(encoding="utf-8", errors="ignore") if cv_path.exists() else ""

    output_dir = _resolve_output_root() / _now_stamp()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonlLogger(output_dir / "events.jsonl")
    cache_conn = _open_cache_db()
    try:
        jobs = _load_jobs(
            db_path=db_path,
            cv_path=cv_path,
            limit=max(1, int(args.limit)),
            recent_days=max(0, int(args.recent_days)),
            job_ids=list(args.job_ids or []),
            cv_text=cv_text,
        )
        custom_jd_texts = _decode_jd_texts(list(args.jd_text_base64 or []))
        custom_jobs = _build_custom_jobs(custom_jd_texts, cv_text)
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
            print(
                f"[PREDICT] completed {idx}/{len(jobs)} job_id={job.job_id} qa_n={len(result.get('qa', []))}",
                flush=True,
            )
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.shutdown_when_completed:
            print("[PREDICT] shutdown requested after completion", flush=True)
            _shutdown_after_completion()
        return 0
    finally:
        try:
            cache_conn.close()
        except Exception:
            pass
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
