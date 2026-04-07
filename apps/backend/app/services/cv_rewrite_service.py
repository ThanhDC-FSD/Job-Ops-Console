from __future__ import annotations

import json
import logging
import os
import re
import hashlib
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import (
    DB_PATH,
    ENABLE_ASYNC_RENDER,
    ENABLE_HEALTHCHECK,
    ENABLE_TIMING_LOGS,
    ENABLE_PROMPT_BUDGET,
    TUNING_DEFER_RENDER,
    TUNING_ENABLE_CONTEXT_PACK,
    TUNING_ENABLE_JSONL_METRICS,
    TUNING_ENABLE_PERSISTED_CACHE,
    TUNING_ENABLE_PERSISTED_CONTEXT_CACHE,
    TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE,
    TUNING_ENABLE_RERANK_FOR_CV_REWRITE,
    TUNING_FORCE_HEURISTIC_FALLBACK_ON_ERROR,
    TUNING_GATEWAY_WARMUP,
    TUNING_LOG_RETRIEVAL_METRICS,
    TUNING_MAX_PROMPT_TOKENS,
    TUNING_PROMPT_RESERVED_TOKENS,
    TUNING_PROMPT_CV_MAX_CHARS,
    TUNING_PROMPT_GUIDE_MAX_CHARS,
    TUNING_PROMPT_JD_MAX_CHARS,
    TUNING_RETRIEVAL_MIN_GAP,
    TUNING_RETRIEVAL_MIN_SCORE,
    TUNING_RERANK_TOP_K,
    TUNING_RETRIEVAL_TOP_K,
    TUNING_TOP_K_CONTEXT,
    TUNING_CONTEXT_PACK_MAX_CHUNKS,
    TUNING_CACHE_DB_PATH,
    TUNING_CACHE_SQLITE_WAL,
    TUNING_TOKENIZER_BACKEND,
    TUNING_LOG_DIR,
    TUNING_LOG_DIR_WIN,
)
from app.controllers.local_llm_controller import ChatCompletionsRequest, process_chat_completions_request
from app.services.text_vector_utils import build_hashed_embedding, cosine_similarity, split_text_chunks

SHOWCASE_VIDEO_URL = "https://github.com/ThanhDC-FSD/Job-Ops-Console/blob/showcase/showcase_assets/video/job_ops_project_showcase.mp4"


class _JsonlMetricsLogger:
    def __init__(self, path: Path) -> None:
        # English: Keep an append-only handle for JSONL metrics to reduce overhead on weak machines.
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self._path.open("a", encoding="utf-8")

    def event(self, payload: dict[str, Any]) -> None:
        # English: Each event is a single JSON object per line for easy aggregation.
        self._fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._fp.flush()

    def close(self) -> None:
        # English: Close the file handle to avoid leaks.
        try:
            self._fp.close()
        except Exception:
            pass


@dataclass
class CvRewriteResult:
    run_folder: str
    cv_path: str
    portfolio_path: str
    cover_letter_path: str
    cover_letter_docx_path: str
    cover_letter_pdf_path: str
    fit_report_path: str
    docx_path: str
    pdf_path: str
    headline: str
    summary: str
    experience_summary: str
    llm_model: str
    llm_backend: str
    llm_usage: dict[str, Any]
    cv_text: str
    portfolio_text: str
    cover_letter_text: str
    fit_report_text: str
    documents_date_folder: str
    company_folder_name: str
    version_number: int
    output_slug: str
    output_basename: str


@dataclass
class ContextSelectionTrace:
    text: str
    total_ms: float
    rerank_ms: float
    candidate_count: int
    selected_count: int
    cache_hit: bool
    selection_mode: str
    fallback_reason: str
    retrieval_candidate_count: int
    top_score: float | None
    top_gap: float | None


class CvRewriteService:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.raw_cv_root = project_root / "input" / "Raw_CV"
        self.documents_root = project_root / "documents"
        self.logger = logging.getLogger("job_ops.cv_rewrite")
        self.env_file = project_root / ".env"
        self._gateway_health_checked = False
        self._gateway_health_state = "not_checked"
        self._ctx_cache: dict[str, str] = {}
        self._ctx_cache_limit = 256
        self._metrics_logger: _JsonlMetricsLogger | None = None
        self._cache_conn: sqlite3.Connection | None = None
        self._tokenizer_cache: dict[str, Any] = {}
        if TUNING_GATEWAY_WARMUP:
            try:
                self._ensure_gateway_ready(os.getenv("LLM_GATEWAY_BASE_URL", "http://127.0.0.1:8101/v1"))
            except Exception:
                # best-effort warmup; keep behavior unchanged
                pass

    def run(
        self,
        *,
        cv_master_path: Path,
        jd_path: Path,
        guide_path: Path,
        user_prompt: str,
        output_slug: str,
        llm_model: str,
        temperature: float,
        render_docx: bool,
        render_pdf: bool,
        run_fit_report: bool,
    ) -> CvRewriteResult:
        if (ENABLE_ASYNC_RENDER or TUNING_DEFER_RENDER) and (render_docx or render_pdf):
            self.logger.info(
                "Render deferred by flag | render_docx=%s render_pdf=%s",
                render_docx,
                render_pdf,
            )
            render_docx = False
            render_pdf = False
        cv_master = cv_master_path.read_text(encoding="utf-8", errors="ignore")
        jd_text = jd_path.read_text(encoding="utf-8", errors="ignore")
        guide_text = guide_path.read_text(encoding="utf-8", errors="ignore")
        return self.run_with_text(
            cv_master=cv_master,
            jd_text=jd_text,
            guide_text=guide_text,
            jd_source_name=jd_path.name,
            user_prompt=user_prompt,
            output_slug=output_slug,
            llm_model=llm_model,
            temperature=temperature,
            render_docx=render_docx,
            render_pdf=render_pdf,
            run_fit_report=run_fit_report,
        )

    def run_with_text(
        self,
        *,
        cv_master: str,
        jd_text: str,
        guide_text: str,
        jd_source_name: str,
        job_context: dict[str, Any] | None = None,
        user_prompt: str,
        output_slug: str,
        llm_model: str,
        temperature: float,
        render_docx: bool,
        render_pdf: bool,
        run_fit_report: bool,
    ) -> CvRewriteResult:
        t_start = time.perf_counter()
        self.logger.info(
            "Rewrite run_with_text start | jd_source=%s output_slug=%s model=%s render_docx=%s render_pdf=%s fit_report=%s",
            jd_source_name,
            output_slug,
            llm_model,
            render_docx,
            render_pdf,
            run_fit_report,
        )

        jd_slug = self._slugify(output_slug.strip() or Path(jd_source_name).stem)
        run_folder = self._next_run_folder(jd_slug)
        run_folder_name = run_folder.name
        output_basename = self._build_output_basename(
            cv_master=cv_master,
            job_context=job_context or {},
            run_folder=run_folder,
        )
        documents_date_folder = self._documents_date_folder()
        company_name = str((job_context or {}).get("company") or "").strip()
        company_folder = self._build_company_folder_name(company_name)
        version_number = int((job_context or {}).get("_artifact_version_number") or 1)
        job_title = str((job_context or {}).get("title") or "").strip()

        t_llm_start = time.perf_counter()
        llm_payload = self._call_llm(
            cv_master=cv_master,
            jd_text=jd_text,
            guide_text=guide_text,
            user_prompt=user_prompt,
            llm_model=llm_model,
            temperature=temperature,
            jd_name=jd_source_name,
            job_context=job_context or {},
        )
        llm_elapsed = time.perf_counter() - t_llm_start

        headline = str(llm_payload.get("headline", "")).strip()
        summary = str(llm_payload.get("summary", "")).strip()
        cv_text = str(llm_payload.get("cv_text", "")).strip()
        if not summary:
            summary = self._compose_local_summary(
                title=str((job_context or {}).get("title") or "").strip(),
                jd_text=jd_text,
                cv_master=cv_master,
            )
        if not headline:
            headline = str((job_context or {}).get("title") or "").strip() or self._build_local_headline(jd_text=jd_text)
        if not cv_text:
            cv_text = self._apply_cv_patch(
                cv_master=cv_master,
                headline=headline,
                summary=summary,
            )
        experience_summary = str(llm_payload.get("experience_summary", "")).strip()
        if not cv_text:
            raise ValueError("LLM output missing 'cv_text'.")
        if not experience_summary:
            experience_summary = self._extract_experience_summary(cv_text=cv_text)
        if not headline:
            headline = self._extract_headline(cv_text=cv_text, job_context=job_context or {})
        if not summary:
            summary = self._extract_summary(cv_text=cv_text)

        cover_letter = str(llm_payload.get("cover_letter", "")).strip()
        if not cover_letter:
            cover_letter = self._compose_local_cover_letter(
                title=job_title or headline,
                company=company_name,
                summary=summary,
                jd_text=jd_text,
            )

        portfolio_text = self._build_portfolio_tagged_text(
            title=str((job_context or {}).get("title") or "").strip(),
            company=str((job_context or {}).get("company") or "").strip(),
            location=str((job_context or {}).get("location") or "").strip(),
            posted_date=str((job_context or {}).get("linkedin_posted_date") or "").strip(),
            headline=headline,
            summary=summary,
            experience_summary=experience_summary,
        ).strip()
        fit_report_text = ""

        t_fit_start = time.perf_counter()
        if run_fit_report:
            with tempfile.TemporaryDirectory(prefix="job_ops_cv_fit_") as temp_dir:
                temp_root = Path(temp_dir)
                jd_temp_path = temp_root / f"jd_{jd_slug}.txt"
                cv_temp_path = temp_root / f"CV_{jd_slug}.txt"
                fit_report_out = temp_root / f"{jd_slug}_fit_report.md"
                jd_temp_path.write_text(jd_text + "\n", encoding="utf-8")
                cv_temp_path.write_text(cv_text + "\n", encoding="utf-8")
                self._run_subprocess(
                    [
                        str(self._venv_python()),
                        str(self.project_root / "scripts" / "python" / "evaluate_cv_fit.py"),
                        "--jd",
                        str(jd_temp_path),
                        "--cv",
                        str(cv_temp_path),
                        "--report",
                        str(fit_report_out),
                    ]
                )
                if fit_report_out.exists():
                    fit_report_text = fit_report_out.read_text(encoding="utf-8", errors="ignore").strip()
        fit_elapsed = time.perf_counter() - t_fit_start

        prompt_metrics = {}
        if isinstance(llm_payload, dict):
            prompt_metrics = llm_payload.get("_prompt_metrics", {}) or {}
        self._emit_jsonl_metrics(
            scenario="cv_rewrite_preview",
            timings={
                "total_ms": (time.perf_counter() - t_start) * 1000,
                "llm_ms": llm_elapsed * 1000,
                "fit_ms": fit_elapsed * 1000,
                "render_ms": 0.0,
            },
            prompt_metrics=prompt_metrics,
        )

        self.logger.info(
            "Rewrite run_with_text done | run_folder=%s version=%s materialized=false timings={\"llm\": %.3f, \"fit_report\": %.3f, \"total\": %.3f}",
            run_folder_name,
            version_number,
            llm_elapsed,
            fit_elapsed,
            time.perf_counter() - t_start,
        )

        return CvRewriteResult(
            run_folder=run_folder_name,
            cv_path="",
            portfolio_path="",
            cover_letter_path="",
            cover_letter_docx_path="",
            cover_letter_pdf_path="",
            fit_report_path="",
            docx_path="",
            pdf_path="",
            headline=headline,
            summary=summary,
            experience_summary=experience_summary,
            llm_model=str(llm_payload.get("_llm_model") or llm_model or "").strip(),
            llm_backend=str(llm_payload.get("_llm_backend") or self._resolve_llm_backend(llm_payload.get("_usage", {}))).strip(),
            llm_usage=llm_payload.get("_usage", {}),
            cv_text=cv_text,
            portfolio_text=portfolio_text,
            cover_letter_text=cover_letter,
            fit_report_text=fit_report_text,
            documents_date_folder=documents_date_folder,
            company_folder_name=company_folder,
            version_number=version_number,
            output_slug=jd_slug,
            output_basename=output_basename,
        )

    @staticmethod
    def _build_portfolio_output_basename(output_basename: str) -> str:
        suffix = str(output_basename or "").strip()
        if suffix.startswith("CV_"):
            suffix = suffix[len("CV_"):]
        return f"PORTFOLIO_{suffix}" if suffix else "PORTFOLIO"

    def _build_portfolio_tagged_text(
        self,
        *,
        title: str,
        company: str,
        location: str,
        posted_date: str,
        headline: str,
        summary: str,
        experience_summary: str,
    ) -> str:
        meta_line = " | ".join([x for x in [company, location, posted_date] if x])
        lines = [
            "<center><bold><size:18>PORTFOLIO SHOWCASE</size></bold></center>",
            "",
            f"<bold><size:15>{headline or title or 'Portfolio'}</size></bold>",
        ]
        if meta_line:
            lines.append(f"<italic>{meta_line}</italic>")
        lines.extend(
            [
                "",
                "<green><bold>Overview</bold></green>",
                "This portfolio summary was generated from tailored CV artifacts for this application.",
                "",
            ]
        )
        if summary:
            lines.extend(["<green><bold>Professional Summary</bold></green>", summary, ""])
        if experience_summary:
            lines.extend(["<green><bold>Experience Highlights</bold></green>", experience_summary, ""])
        lines.extend(
            [
                "<green><bold>Project Showcase Video</bold></green>",
                SHOWCASE_VIDEO_URL,
                "",
                "<green><bold>Public Showcase Repository</bold></green>",
                "https://github.com/ThanhDC-FSD/Job-Ops-Console/tree/showcase",
                "",
                "<green><bold>Selected Code Snippets</bold></green>",
                "Backend API: showcase_assets/code/backend_api_excerpt.md",
                "CV workflow: showcase_assets/code/cv_generation_excerpt.md",
                "Frontend analytics: showcase_assets/code/frontend_analytics_excerpt.md",
                "Learning quiz: showcase_assets/code/learning_quiz_excerpt.md",
            ]
        )
        return "\n".join(lines).strip()

    def _call_llm(
        self,
        *,
        cv_master: str,
        jd_text: str,
        guide_text: str,
        user_prompt: str,
        llm_model: str,
        temperature: float,
        jd_name: str,
        job_context: dict[str, Any],
    ) -> dict[str, Any]:
        base_url = os.getenv("LLM_GATEWAY_BASE_URL", "http://127.0.0.1:8101/v1").rstrip("/")
        self._ensure_gateway_ready(base_url)
        shared_token = str(os.getenv("INTERNAL_LLM_SHARED_TOKEN", "") or "").strip()
        allow_no_key = self._allow_no_key_for_base_url(base_url)
        job_id = int((job_context or {}).get("job_id") or 0)
        title = str((job_context or {}).get("title") or "").strip()
        company = str((job_context or {}).get("company") or "").strip()
        retrieval_query = "\n".join([title, company, user_prompt, jd_name]).strip()
        prompt_build_started = time.perf_counter()
        jd_trace = self._select_relevant_jd_context_trace(
            job_id=job_id,
            jd_text=jd_text,
            query_text=retrieval_query,
            limit=min(TUNING_TOP_K_CONTEXT, 6),
        )
        jd_context = self._budget_guard("jd", jd_trace.text, TUNING_PROMPT_JD_MAX_CHARS)
        cv_trace = self._select_relevant_cv_context_trace(
            cv_master=cv_master,
            query_text="\n".join([retrieval_query, jd_context]).strip(),
            limit=min(TUNING_TOP_K_CONTEXT, 8),
        )
        cv_context = self._budget_guard("cv", cv_trace.text, TUNING_PROMPT_CV_MAX_CHARS)
        guide_context = self._trim_text(self._compact_guide_text(guide_text), max_chars=TUNING_PROMPT_GUIDE_MAX_CHARS)
        budgeted_blocks, prompt_tokens = self._apply_prompt_budget(
            blocks=[jd_context, cv_context, guide_context],
        )
        jd_context = budgeted_blocks[0] if len(budgeted_blocks) > 0 else ""
        cv_context = budgeted_blocks[1] if len(budgeted_blocks) > 1 else ""
        guide_context = budgeted_blocks[2] if len(budgeted_blocks) > 2 else ""
        prompt_chars = len(user_prompt) + len(jd_context) + len(cv_context) + len(guide_context)
        est_tokens = prompt_tokens if prompt_tokens else self._estimate_tokens(prompt_chars)
        cache_summary = f"jd:{'hit' if jd_trace.cache_hit else 'miss'},cv:{'hit' if cv_trace.cache_hit else 'miss'}"
        retrieval_ms = jd_trace.total_ms + cv_trace.total_ms
        rerank_ms = jd_trace.rerank_ms + cv_trace.rerank_ms
        fallback_reason = ";".join(
            [
                reason
                for reason in [str(jd_trace.fallback_reason or "").strip(), str(cv_trace.fallback_reason or "").strip()]
                if reason
            ]
        )
        prompt_build_ms = (time.perf_counter() - prompt_build_started) * 1000
        self._log_stage_metric(
            "prompt_build",
            total_ms=round(prompt_build_ms, 3),
            prompt_chars=prompt_chars,
            est_tokens=est_tokens,
            selected_context_count=jd_trace.selected_count + cv_trace.selected_count,
            retrieval_candidate_count=jd_trace.retrieval_candidate_count + cv_trace.retrieval_candidate_count,
            cache_summary=cache_summary,
            feature_flags=self._feature_flag_snapshot(),
        )
        self._log_stage_metric(
            "context_select",
            total_ms=round(retrieval_ms, 3),
            jd_ms=round(jd_trace.total_ms, 3),
            cv_ms=round(cv_trace.total_ms, 3),
            jd_candidates=jd_trace.candidate_count,
            cv_candidates=cv_trace.candidate_count,
            jd_selected=jd_trace.selected_count,
            cv_selected=cv_trace.selected_count,
            retrieval_enabled=int(TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE),
            fallback_reason=fallback_reason,
        )

        system_prompt = (
            "You are tailoring a CV with minimal output cost.\n"
            "Use only evidence from MASTER_CV.\n"
            "Do not invent tools, dates, ownership, scope, or achievements.\n"
            "Use JD_DB_TEXT only as targeting context.\n"
            "Output English only.\n"
            "Return JSON only with keys: headline, summary, notes.\n"
            "headline: short role headline, max 90 chars.\n"
            "summary: 2 or 3 concise bullet lines, each starting with '- '.\n"
            "notes: short list of adaptation notes."
        )
        user_content = (
            f"USER_PROMPT:\n{user_prompt}\n\n"
            f"JD_FILE_NAME: {jd_name}\n\n"
            "JOB_CONTEXT:\n"
            f"{json.dumps(job_context or {}, ensure_ascii=False)}\n\n"
            "GUIDE:\n"
            f"{guide_context}\n\n"
            "MASTER_CV:\n"
            f"{cv_context}\n\n"
            "JD_DB_TEXT:\n"
            f"{jd_context}\n"
        )
        prompt_tokens = self._count_tokens(system_prompt + "\n\n" + user_content)

        llm_url = f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if shared_token:
            headers["Authorization"] = f"Bearer {shared_token}"
            headers["X-Internal-LLM-Token"] = shared_token
        self.logger.info("LLM request start | url=%s model=%s jd_name=%s", llm_url, llm_model, jd_name)
        payload = {
            "model": llm_model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        parsed_base_url = urlparse(llm_url)
        is_loopback_gateway = (parsed_base_url.hostname or "").strip().lower() in {"127.0.0.1", "localhost"} and (
            parsed_base_url.port in {8101, 8102}
        )
        if is_loopback_gateway:
            self.logger.info("LLM request using in-process gateway | model=%s jd_name=%s", llm_model, jd_name)
            llm_started = time.perf_counter()
            data = process_chat_completions_request(
                ChatCompletionsRequest(**payload),
                authorization=(f"Bearer {shared_token}" if shared_token else None),
                x_internal_llm_token=(shared_token or None),
            )
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            try:
                parsed = self._parse_llm_json(content)
            except Exception as exc:
                if allow_no_key:
                    self.logger.warning("In-process gateway returned invalid JSON, using embedded fallback")
                    return self._local_fallback_llm(
                        job_context=job_context,
                        cv_master=cv_master,
                        jd_text=jd_text,
                        reason="gateway_invalid_json",
                    )
                raise ValueError(f"LLM did not return valid JSON: {content[:400]}") from exc
            parsed["_usage"] = data.get("usage", {})
            parsed["_llm_backend"] = self._resolve_llm_backend(parsed["_usage"])
            parsed["_llm_model"] = str(parsed["_usage"].get("upstream_model") or data.get("model") or llm_model or "").strip()
            parsed["_prompt_metrics"] = {
                "prompt_chars": prompt_chars,
                "est_tokens": est_tokens,
                "prompt_tokens": prompt_tokens,
                "selected_context_count": jd_trace.selected_count + cv_trace.selected_count,
                "retrieval_candidate_count": jd_trace.retrieval_candidate_count + cv_trace.retrieval_candidate_count,
                "cache_summary": cache_summary,
                "fallback_reason": fallback_reason or str(parsed["_usage"].get("fallback_reason") or ""),
                "gateway_health_state": self._gateway_health_state,
                "retrieval_ms": round(retrieval_ms, 3),
                "rerank_ms": round(rerank_ms, 3),
                "llm_ms": round((time.perf_counter() - llm_started) * 1000, 3),
                "context_pack_hit": jd_trace.selection_mode.startswith("context_pack"),
            }
            self.logger.info("LLM request done | usage=%s", parsed["_usage"])
            return parsed
        try:
            llm_started = time.perf_counter()
            resp = requests.post(
                llm_url,
                headers=headers,
                json=payload,
                timeout=180,
            )
        except Exception as exc:
            if allow_no_key:
                self.logger.warning(
                    "LLM HTTP unavailable, using embedded local fallback | url=%s error=%s",
                    llm_url,
                    str(exc),
                )
                return self._local_fallback_llm(
                    job_context=job_context,
                    cv_master=cv_master,
                    jd_text=jd_text,
                    reason="http_unavailable",
                )
            raise ValueError(f"LLM request failed: {exc}") from exc
        if resp.status_code >= 400:
            self.logger.error("LLM request failed | status=%s body=%s", resp.status_code, resp.text[:1200])
            if allow_no_key:
                self.logger.warning("LLM API returned error, using embedded local fallback | status=%s", resp.status_code)
                return self._local_fallback_llm(
                    job_context=job_context,
                    cv_master=cv_master,
                    jd_text=jd_text,
                    reason=f"http_status_{resp.status_code}",
                )
            raise ValueError(f"LLM API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        try:
            parsed = self._parse_llm_json(content)
        except Exception as exc:
            if allow_no_key:
                self.logger.warning("LLM gateway returned invalid JSON, using embedded fallback")
                return self._local_fallback_llm(
                    job_context=job_context,
                    cv_master=cv_master,
                    jd_text=jd_text,
                    reason="gateway_invalid_json",
                )
            raise ValueError(f"LLM did not return valid JSON: {content[:400]}") from exc
        parsed["_usage"] = data.get("usage", {})
        parsed["_llm_backend"] = self._resolve_llm_backend(parsed["_usage"])
        parsed["_llm_model"] = str(parsed["_usage"].get("upstream_model") or data.get("model") or llm_model or "").strip()
        parsed["_prompt_metrics"] = {
            "prompt_chars": prompt_chars,
            "est_tokens": est_tokens,
            "prompt_tokens": prompt_tokens,
            "selected_context_count": jd_trace.selected_count + cv_trace.selected_count,
            "retrieval_candidate_count": jd_trace.retrieval_candidate_count + cv_trace.retrieval_candidate_count,
            "cache_summary": cache_summary,
            "fallback_reason": fallback_reason or str(parsed["_usage"].get("fallback_reason") or ""),
            "gateway_health_state": self._gateway_health_state,
            "retrieval_ms": round(retrieval_ms, 3),
            "rerank_ms": round(rerank_ms, 3),
            "llm_ms": round((time.perf_counter() - llm_started) * 1000, 3),
            "context_pack_hit": jd_trace.selection_mode.startswith("context_pack"),
        }
        self.logger.info("LLM request done | usage=%s", parsed["_usage"])
        return parsed

    def _ensure_gateway_ready(self, base_url: str) -> None:
        if self._gateway_health_checked or not ENABLE_HEALTHCHECK:
            return
        self._gateway_health_checked = True
        try:
            parsed = urlparse(base_url)
            is_loopback = (parsed.hostname or "").lower() in {"127.0.0.1", "localhost"}
            if not is_loopback:
                self._gateway_health_state = "skipped_non_loopback"
                return
            health_url = f"{base_url}/health"
            resp = requests.get(health_url, timeout=3)
            if resp.status_code >= 400:
                self._gateway_health_state = f"http_{resp.status_code}"
                self.logger.warning("LLM gateway health check returned %s | url=%s", resp.status_code, health_url)
            else:
                self._gateway_health_state = "ok"
        except Exception as exc:
            self._gateway_health_state = f"error:{exc.__class__.__name__}"
            self.logger.warning("LLM gateway health check failed | url=%s error=%s", base_url, exc)

    @staticmethod
    def _trim_text(value: str, *, max_chars: int) -> str:
        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0].strip()

    def _budget_guard(self, label: str, text: str, max_chars: int) -> str:
        """Apply prompt budget per block with logging for visibility."""
        if not ENABLE_PROMPT_BUDGET:
            return str(text or "").strip()
        trimmed = self._trim_text(text, max_chars=max_chars)
        if len(trimmed) < len(str(text or "")):
            self.logger.info(
                "Prompt block trimmed | block=%s max_chars=%s original=%s trimmed=%s",
                label,
                max_chars,
                len(text or ""),
                len(trimmed),
            )
        return trimmed

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]

    def _apply_cv_patch(self, *, cv_master: str, headline: str, summary: str) -> str:
        base = str(cv_master or "").strip()
        if not base:
            return self._compose_local_cv(cv_master=base, title=headline)
        lines = base.splitlines()
        rebuilt: list[str] = []
        headline_done = False
        in_summary = False
        summary_inserted = False
        summary_lines = [line.rstrip() for line in str(summary or "").splitlines() if line.strip()]
        for line in lines:
            stripped = line.strip()
            lower = self._strip_cv_tags(stripped).lower()
            if (
                not headline_done
                and stripped.startswith("<center>")
                and stripped.endswith("</center>")
                and "|" not in stripped
            ):
                rebuilt.append(f"<center>{headline}</center>")
                headline_done = True
                continue
            if "professional summary" in lower:
                rebuilt.append(line)
                if summary_lines and not summary_inserted:
                    rebuilt.extend(summary_lines)
                    summary_inserted = True
                in_summary = True
                continue
            if in_summary:
                if any(marker in lower for marker in ("work experience", "technical skills", "education", "projects")):
                    in_summary = False
                    rebuilt.append(line)
                continue
            rebuilt.append(line)
        if summary_lines and not summary_inserted:
            rebuilt.extend(["", "<bold><green>Professional Summary</green></bold>", *summary_lines])
        return "\n".join(rebuilt).strip() + "\n"

    @staticmethod
    def _parse_llm_json(content: str) -> dict[str, Any]:
        raw = str(content or "").strip()
        if not raw:
            raise ValueError("empty_llm_content")
        try:
            parsed = json.loads(raw)
        except Exception:
            fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
            candidate = fence_match.group(1).strip() if fence_match else ""
            if not candidate:
                start = raw.find("{")
                end = raw.rfind("}")
                if start >= 0 and end > start:
                    candidate = raw[start : end + 1]
            if not candidate:
                raise
            parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("llm_json_not_object")
        return parsed

    def _compact_guide_text(self, guide_text: str) -> str:
        lines = [str(line).strip() for line in str(guide_text or "").splitlines() if str(line).strip()]
        selected: list[str] = []
        keywords = ("invent", "json", "english", "tag", "truth", "evidence", "bullet")
        for line in lines:
            lowered = line.lower()
            if any(keyword in lowered for keyword in keywords):
                selected.append(line)
            if len(selected) >= 8:
                break
        if not selected:
            selected = lines[:8]
        return self._trim_text("\n".join(selected), max_chars=500)

    @staticmethod
    def _estimate_tokens(char_count: int) -> int:
        # Keep a deterministic token estimate for budget logs when a tokenizer is unavailable.
        count = max(0, int(char_count or 0))
        return max(1, int(round(count / 4.0))) if count else 0

    def _resolve_log_root(self) -> Path:
        # English: Resolve tuning log root for the current OS.
        if os.name == "nt":
            return Path(TUNING_LOG_DIR_WIN or (Path.home() / "tuning_logs"))
        return Path(TUNING_LOG_DIR or "/home/user/tuning_logs")

    def _resolve_jsonl_path(self) -> Path | None:
        # English: Allow the benchmark harness to pin an explicit metrics path.
        explicit = str(os.getenv("TUNING_JSONL_PATH", "") or "").strip()
        if explicit:
            return Path(explicit)
        if not TUNING_ENABLE_JSONL_METRICS:
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._resolve_log_root() / "etl_cv_rewrite" / stamp / "events.jsonl"

    def _ensure_metrics_logger(self) -> _JsonlMetricsLogger | None:
        # English: Initialize JSONL metrics logger lazily to avoid overhead when disabled.
        if not TUNING_ENABLE_JSONL_METRICS:
            return None
        if self._metrics_logger:
            return self._metrics_logger
        path = self._resolve_jsonl_path()
        if not path:
            return None
        self._metrics_logger = _JsonlMetricsLogger(path)
        return self._metrics_logger

    def _open_cache_db(self) -> sqlite3.Connection | None:
        # English: Use a lightweight SQLite cache for persisted context packs and token counts.
        if not (TUNING_ENABLE_PERSISTED_CACHE or TUNING_ENABLE_PERSISTED_CONTEXT_CACHE or TUNING_ENABLE_CONTEXT_PACK):
            return None
        if self._cache_conn:
            return self._cache_conn
        cache_path = Path(TUNING_CACHE_DB_PATH)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cache_path), timeout=30.0)
        conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v BLOB, ts INTEGER)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS context_pack (job_id INTEGER, content_hash TEXT, pack_json TEXT, PRIMARY KEY(job_id, content_hash))"
        )
        if TUNING_CACHE_SQLITE_WAL:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        self._cache_conn = conn
        return conn

    def _cache_get(self, key: str) -> str | None:
        # English: Read a cached value from the persisted cache if enabled.
        conn = self._open_cache_db()
        if not conn:
            return None
        row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def _cache_put(self, key: str, value: str) -> None:
        # English: Upsert a cached value into the persisted cache if enabled.
        conn = self._open_cache_db()
        if not conn:
            return
        ts = int(time.time())
        conn.execute(
            "INSERT INTO kv(k, v, ts) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, ts = excluded.ts",
            (key, value, ts),
        )
        conn.commit()

    def _load_context_pack(self, *, job_id: int, jd_text: str) -> str | None:
        # English: Load a precomputed context pack from the persisted cache.
        if not TUNING_ENABLE_CONTEXT_PACK:
            return None
        content_hash = self._hash_text(jd_text)
        conn = self._open_cache_db()
        if not conn:
            return None
        row = conn.execute(
            "SELECT pack_json FROM context_pack WHERE job_id = ? AND content_hash = ?",
            (job_id, content_hash),
        ).fetchone()
        raw = str(row[0]) if row and str(row[0]) else ""
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return str(parsed.get("text") or "").strip() or None
        except Exception:
            return raw.strip() or None

    def _store_context_pack(self, *, job_id: int, jd_text: str, pack_json: str) -> None:
        # English: Store a context pack so offline ETL can reuse it.
        conn = self._open_cache_db()
        if not conn:
            return
        content_hash = self._hash_text(jd_text)
        conn.execute(
            "INSERT OR REPLACE INTO context_pack(job_id, content_hash, pack_json) VALUES (?, ?, ?)",
            (job_id, content_hash, pack_json),
        )
        conn.commit()

    def _build_context_pack_text(self, *, jd_text: str, candidates: list[str]) -> str:
        # English: Build a compact context pack with summary + key chunks for weak CPU-only online usage.
        summary = self._trim_text(str(jd_text or ""), max_chars=360)
        keywords = ", ".join(self._extract_keywords(jd_text, limit=6))
        chosen = [chunk for chunk in candidates if chunk][: max(1, TUNING_CONTEXT_PACK_MAX_CHUNKS)]
        parts = ["SUMMARY:", summary]
        if keywords:
            parts.extend(["", "KEYWORDS:", keywords])
        if chosen:
            parts.append("")
            parts.append("TOP_CHUNKS:")
            parts.extend(chosen)
        return "\n".join(parts).strip()

    def build_context_pack_for_job(self, *, job_id: int, jd_text: str) -> str:
        # English: Public helper for offline ETL or benchmark setup to precompute context packs.
        candidates = split_text_chunks(jd_text)
        pack_text = self._build_context_pack_text(jd_text=jd_text, candidates=candidates)
        pack_json = json.dumps({"text": pack_text}, ensure_ascii=False)
        self._store_context_pack(job_id=job_id, jd_text=jd_text, pack_json=pack_json)
        return pack_json

    def _count_tokens(self, text: str) -> int:
        # English: Use a real tokenizer when available, fall back to a conservative char estimate.
        content = str(text or "")
        backend = (TUNING_TOKENIZER_BACKEND or "auto").lower()
        if backend in {"auto", "tiktoken"}:
            try:
                import tiktoken

                cache_key = "tiktoken_o200k"
                encoder = self._tokenizer_cache.get(cache_key)
                if encoder is None:
                    encoder = tiktoken.get_encoding("o200k_base")
                    self._tokenizer_cache[cache_key] = encoder
                return len(encoder.encode(content))
            except Exception:
                if backend == "tiktoken":
                    return self._estimate_tokens(len(content))
        if backend in {"auto", "hf", "hf_tokenizers", "hf_tokenizer"}:
            try:
                from tokenizers import Tokenizer

                cache_key = "hf_tokenizer"
                tokenizer = self._tokenizer_cache.get(cache_key)
                if tokenizer is None:
                    tokenizer_path = str(os.getenv("HF_TOKENIZER_JSON", "") or "").strip()
                    if not tokenizer_path:
                        return self._estimate_tokens(len(content))
                    tokenizer = Tokenizer.from_file(tokenizer_path)
                    self._tokenizer_cache[cache_key] = tokenizer
                return len(tokenizer.encode(content).ids)
            except Exception:
                return self._estimate_tokens(len(content))
        return self._estimate_tokens(len(content))

    def _apply_prompt_budget(self, *, blocks: list[str]) -> tuple[list[str], int]:
        # English: Enforce a hard token budget with deterministic truncation order.
        if not ENABLE_PROMPT_BUDGET:
            token_total = sum(self._count_tokens(block) for block in blocks)
            return blocks, token_total
        budget = max(0, TUNING_MAX_PROMPT_TOKENS - TUNING_PROMPT_RESERVED_TOKENS)
        used = 0
        selected: list[str] = []
        for block in blocks:
            block_tokens = self._count_tokens(block)
            if used + block_tokens <= budget:
                selected.append(block)
                used += block_tokens
                continue
            if used < budget:
                # English: Truncate the current block to fit the remaining budget.
                remaining = max(0, budget - used)
                approx_chars = max(1, int((remaining / max(1, block_tokens)) * len(block)))
                trimmed = self._trim_text(block, max_chars=approx_chars)
                selected.append(trimmed)
                used += self._count_tokens(trimmed)
            break
        return selected, used

    def _feature_flag_snapshot(self) -> str:
        # Render flags into a short stable string for structured logs.
        return ",".join(
            [
                f"retrieval={int(TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE)}",
                f"rerank={int(TUNING_ENABLE_RERANK_FOR_CV_REWRITE)}",
                f"persisted_cache={int(TUNING_ENABLE_PERSISTED_CONTEXT_CACHE)}",
                f"context_pack={int(TUNING_ENABLE_CONTEXT_PACK)}",
                f"log_retrieval={int(TUNING_LOG_RETRIEVAL_METRICS)}",
                f"force_fallback={int(TUNING_FORCE_HEURISTIC_FALLBACK_ON_ERROR)}",
                f"top_k={int(TUNING_RETRIEVAL_TOP_K)}",
                f"rerank_k={int(TUNING_RERANK_TOP_K)}",
                f"max_prompt_tokens={int(TUNING_MAX_PROMPT_TOKENS)}",
                f"tokenizer={TUNING_TOKENIZER_BACKEND}",
            ]
        )

    def _log_stage_metric(self, stage: str, **fields: Any) -> None:
        # Emit machine-readable metrics without changing the existing control flow.
        if not (ENABLE_TIMING_LOGS or TUNING_LOG_RETRIEVAL_METRICS):
            return
        rendered = " ".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in fields.items())
        self.logger.info("stage=%s %s", stage, rendered)

    def _emit_jsonl_metrics(self, *, scenario: str, timings: dict[str, float], prompt_metrics: dict[str, Any]) -> None:
        # English: Emit a single JSONL metrics record for repeatable benchmarks.
        logger = self._ensure_metrics_logger()
        if not logger:
            return
        cache_summary = str(prompt_metrics.get("cache_summary") or "")
        event = {
            "scenario": scenario,
            "total_ms": round(timings.get("total_ms", 0.0), 3),
            "llm_ms": round(timings.get("llm_ms", 0.0), 3),
            "retrieval_ms": round(float(prompt_metrics.get("retrieval_ms") or 0.0), 3),
            "rerank_ms": round(float(prompt_metrics.get("rerank_ms") or 0.0), 3),
            "fit_ms": round(timings.get("fit_ms", 0.0), 3),
            "render_ms": round(timings.get("render_ms", 0.0), 3),
            "prompt_tokens": int(prompt_metrics.get("prompt_tokens") or 0),
            "prompt_chars": int(prompt_metrics.get("prompt_chars") or 0),
            "selected_context_count": int(prompt_metrics.get("selected_context_count") or 0),
            "retrieval_candidates": int(prompt_metrics.get("retrieval_candidate_count") or 0),
            "cache_hit": {
                "context_pack": bool(prompt_metrics.get("context_pack_hit")),
                "context_selection": ("hit" in cache_summary),
                "rewrite_result": False,
                "tokenizer": TUNING_TOKENIZER_BACKEND not in {"fallback_chars", "fallback"},
            },
            "cache_summary": cache_summary,
            "fallback_reason": str(prompt_metrics.get("fallback_reason") or ""),
            "flags_effective": self._feature_flag_snapshot(),
        }
        logger.event(event)

    @staticmethod
    def _keyword_overlap_score(query_text: str, candidate_text: str) -> float:
        # Use a small lexical overlap signal as a cheap CPU-only reranker.
        query_tokens = {token.lower() for token in re.findall(r"[a-zA-Z0-9+#./_-]{2,}", str(query_text or ""))}
        candidate_tokens = {token.lower() for token in re.findall(r"[a-zA-Z0-9+#./_-]{2,}", str(candidate_text or ""))}
        if not query_tokens or not candidate_tokens:
            return 0.0
        return len(query_tokens.intersection(candidate_tokens)) / max(1, len(query_tokens))

    def _rank_context_candidates(
        self,
        *,
        query_text: str,
        candidates: list[str],
        limit: int,
    ) -> tuple[list[str], int, dict[str, Any]]:
        # English: Keep retrieval small so the prompt stays bounded on weak CPU-only machines.
        started = time.perf_counter()
        query_vector = build_hashed_embedding(query_text)
        scored: list[tuple[float, float, str]] = []
        for candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            semantic_score = cosine_similarity(query_vector, build_hashed_embedding(text))
            lexical_score = self._keyword_overlap_score(query_text, text)
            scored.append((semantic_score, lexical_score, text))
        if not scored:
            return [], 0, {"rerank_ms": 0.0, "selection_mode": "retrieval_empty", "top_score": None, "top_gap": None}
        scored.sort(key=lambda item: (item[0], item[1], len(item[2])), reverse=True)
        top_score = scored[0][0] if scored else None
        top_gap = (scored[0][0] - scored[1][0]) if len(scored) > 1 else None
        top_k = max(1, min(int(TUNING_RETRIEVAL_TOP_K), len(scored)))
        semantic_selected = [text for _semantic, _lexical, text in scored[:top_k]]

        if not TUNING_ENABLE_RERANK_FOR_CV_REWRITE:
            selected = semantic_selected[: max(1, min(limit, TUNING_RERANK_TOP_K))]
            return (
                selected,
                len(scored),
                {
                    "rerank_ms": 0.0,
                    "selection_mode": "retrieval_semantic",
                    "top_score": top_score,
                    "top_gap": top_gap,
                    "rerank_skipped_reason": "rerank_disabled",
                },
            )

        if top_score is not None and top_score >= TUNING_RETRIEVAL_MIN_SCORE:
            if top_gap is not None and top_gap >= TUNING_RETRIEVAL_MIN_GAP:
                selected = semantic_selected[: max(1, min(limit, TUNING_RERANK_TOP_K))]
                return (
                    selected,
                    len(scored),
                    {
                        "rerank_ms": 0.0,
                        "selection_mode": "retrieval_semantic",
                        "top_score": top_score,
                        "top_gap": top_gap,
                        "rerank_skipped_reason": "confident_top",
                    },
                )

        rerank_started = time.perf_counter()
        rerank_pool = scored[:top_k]
        rerank_pool.sort(key=lambda item: (item[1], item[0], len(item[2])), reverse=True)
        selected = [text for _semantic, _lexical, text in rerank_pool[: max(1, min(limit, TUNING_RERANK_TOP_K))]]
        rerank_ms = (time.perf_counter() - rerank_started) * 1000
        return (
            selected,
            len(scored),
            {
                "rerank_ms": rerank_ms,
                "selection_mode": "retrieval_rerank",
                "top_score": top_score,
                "top_gap": top_gap,
            },
        )

    def _legacy_jd_context_trace(
        self,
        *,
        job_id: int,
        jd_text: str,
        query_text: str,
        limit: int = 6,
    ) -> ContextSelectionTrace:
        # Preserve the original scoring behavior so new retrieval paths can fall back safely.
        started = time.perf_counter()
        cache_key = f"jdctx::{job_id}:{self._hash_text(jd_text)}:{limit}"
        cached = self._ctx_cache.get(cache_key)
        if cached:
            return ContextSelectionTrace(
                text=cached,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=0.0,
                candidate_count=0,
                selected_count=max(1, min(limit, len([part for part in cached.split('\n\n') if part.strip()]))),
                cache_hit=True,
                selection_mode="legacy_heuristic_cache",
                fallback_reason="",
                retrieval_candidate_count=0,
                top_score=None,
                top_gap=None,
            )
        if TUNING_ENABLE_PERSISTED_CONTEXT_CACHE or TUNING_ENABLE_PERSISTED_CACHE:
            persisted = self._cache_get(cache_key)
            if persisted:
                self._store_ctx_cache(cache_key, persisted)
                return ContextSelectionTrace(
                    text=persisted,
                    total_ms=(time.perf_counter() - started) * 1000,
                    rerank_ms=0.0,
                    candidate_count=0,
                    selected_count=max(1, min(limit, len([part for part in persisted.split('\n\n') if part.strip()]))),
                    cache_hit=True,
                    selection_mode="legacy_heuristic_persisted_cache",
                    fallback_reason="",
                    retrieval_candidate_count=0,
                    top_score=None,
                    top_gap=None,
                )
        query_vector = build_hashed_embedding(query_text)
        chunks: list[tuple[float, str]] = []
        if job_id > 0:
            try:
                conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT chunk_text, embedding_json
                    FROM job_text_embeddings
                    WHERE job_post_id = ? AND content_type = 'jd'
                    ORDER BY chunk_index ASC
                    """,
                    (job_id,),
                ).fetchall()
                conn.close()
                for row in rows:
                    try:
                        vector = json.loads(str(row["embedding_json"] or "[]"))
                    except Exception:
                        vector = []
                    chunks.append((cosine_similarity(query_vector, vector), str(row["chunk_text"] or "").strip()))
            except Exception as exc:
                self.logger.warning("JD embedding lookup failed | job_id=%s error=%s", job_id, exc)
        if not chunks:
            for chunk in split_text_chunks(jd_text):
                chunks.append((cosine_similarity(query_vector, build_hashed_embedding(chunk)), chunk))
        selected = [chunk for _score, chunk in sorted(chunks, key=lambda item: item[0], reverse=True)[: max(1, limit)] if chunk]
        result = "\n\n".join(selected).strip() or str(jd_text or "").strip()
        self._store_ctx_cache(cache_key, result)
        if TUNING_ENABLE_PERSISTED_CONTEXT_CACHE or TUNING_ENABLE_PERSISTED_CACHE:
            self._cache_put(cache_key, result)
        return ContextSelectionTrace(
            text=result,
            total_ms=(time.perf_counter() - started) * 1000,
            rerank_ms=0.0,
            candidate_count=len(chunks),
            selected_count=len(selected),
            cache_hit=False,
            selection_mode="legacy_heuristic",
            fallback_reason="",
            retrieval_candidate_count=0,
            top_score=None,
            top_gap=None,
        )

    def _legacy_cv_context_trace(self, *, cv_master: str, query_text: str, limit: int = 8) -> ContextSelectionTrace:
        # Preserve the original CV chunk selection behavior for safe fallback.
        started = time.perf_counter()
        cache_key = f"cvctx::{self._hash_text(cv_master)}:{self._hash_text(query_text)}:{limit}"
        cached = self._ctx_cache.get(cache_key)
        if cached:
            return ContextSelectionTrace(
                text=cached,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=0.0,
                candidate_count=0,
                selected_count=max(1, min(limit, len([part for part in cached.split('\n\n') if part.strip()]))),
                cache_hit=True,
                selection_mode="legacy_heuristic_cache",
                fallback_reason="",
                retrieval_candidate_count=0,
                top_score=None,
                top_gap=None,
            )
        if TUNING_ENABLE_PERSISTED_CONTEXT_CACHE or TUNING_ENABLE_PERSISTED_CACHE:
            persisted = self._cache_get(cache_key)
            if persisted:
                self._store_ctx_cache(cache_key, persisted)
                return ContextSelectionTrace(
                    text=persisted,
                    total_ms=(time.perf_counter() - started) * 1000,
                    rerank_ms=0.0,
                    candidate_count=0,
                    selected_count=max(1, min(limit, len([part for part in persisted.split('\n\n') if part.strip()]))),
                    cache_hit=True,
                    selection_mode="legacy_heuristic_persisted_cache",
                    fallback_reason="",
                    retrieval_candidate_count=0,
                    top_score=None,
                    top_gap=None,
                )
        query_vector = build_hashed_embedding(query_text)
        chunks: list[tuple[float, str]] = []
        for chunk in split_text_chunks(cv_master, max_chars=850, overlap_chars=120):
            chunks.append((cosine_similarity(query_vector, build_hashed_embedding(chunk)), chunk))
        selected = [chunk for _score, chunk in sorted(chunks, key=lambda item: item[0], reverse=True)[: max(1, limit)] if chunk]
        result = "\n\n".join(selected).strip() or str(cv_master or "").strip()
        self._store_ctx_cache(cache_key, result)
        if TUNING_ENABLE_PERSISTED_CONTEXT_CACHE or TUNING_ENABLE_PERSISTED_CACHE:
            self._cache_put(cache_key, result)
        return ContextSelectionTrace(
            text=result,
            total_ms=(time.perf_counter() - started) * 1000,
            rerank_ms=0.0,
            candidate_count=len(chunks),
            selected_count=len(selected),
            cache_hit=False,
            selection_mode="legacy_heuristic",
            fallback_reason="",
            retrieval_candidate_count=0,
            top_score=None,
            top_gap=None,
        )

    def _select_relevant_jd_context_trace(
        self,
        *,
        job_id: int,
        jd_text: str,
        query_text: str,
        limit: int = 6,
    ) -> ContextSelectionTrace:
        if not TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE:
            return self._legacy_jd_context_trace(
                job_id=job_id,
                jd_text=jd_text,
                query_text=query_text,
                limit=limit,
            )
        started = time.perf_counter()
        cache_key = f"jdctx_retrieval::{job_id}:{self._hash_text(jd_text)}:{self._hash_text(query_text)}:{limit}"
        cached = self._ctx_cache.get(cache_key)
        if cached:
            return ContextSelectionTrace(
                text=cached,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=0.0,
                candidate_count=0,
                selected_count=max(1, min(limit, len([part for part in cached.split('\n\n') if part.strip()]))),
                cache_hit=True,
                selection_mode="retrieval_cache",
                fallback_reason="",
                retrieval_candidate_count=max(1, min(limit, TUNING_RETRIEVAL_TOP_K)),
                top_score=None,
                top_gap=None,
            )
        if TUNING_ENABLE_CONTEXT_PACK:
            pack = self._load_context_pack(job_id=job_id, jd_text=jd_text)
            if pack:
                return ContextSelectionTrace(
                    text=pack,
                    total_ms=(time.perf_counter() - started) * 1000,
                    rerank_ms=0.0,
                    candidate_count=0,
                    selected_count=max(1, len([part for part in pack.split('\n\n') if part.strip()])),
                    cache_hit=True,
                    selection_mode="context_pack_cache",
                    fallback_reason="",
                    retrieval_candidate_count=0,
                    top_score=None,
                    top_gap=None,
                )
        try:
            candidates: list[str] = []
            if job_id > 0:
                conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute(
                        """
                        SELECT chunk_text
                        FROM job_text_embeddings
                        WHERE job_post_id = ? AND content_type = 'jd'
                        ORDER BY chunk_index ASC
                        """,
                        (job_id,),
                    ).fetchall()
                finally:
                    conn.close()
                candidates = [str(row["chunk_text"] or "").strip() for row in rows if str(row["chunk_text"] or "").strip()]
            if not candidates:
                candidates = split_text_chunks(jd_text)
            selected, candidate_count, meta = self._rank_context_candidates(
                query_text=query_text,
                candidates=candidates,
                limit=max(1, min(limit, TUNING_RERANK_TOP_K)),
            )
            if not selected:
                raise ValueError("retrieval_empty")
            result = "\n\n".join(selected).strip() or str(jd_text or "").strip()
            self._store_ctx_cache(cache_key, result)
            return ContextSelectionTrace(
                text=result,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=float(meta.get("rerank_ms") or 0.0),
                candidate_count=candidate_count,
                selected_count=len(selected),
                cache_hit=False,
                selection_mode=str(meta.get("selection_mode") or "retrieval_rerank"),
                fallback_reason="",
                retrieval_candidate_count=candidate_count,
                top_score=meta.get("top_score"),
                top_gap=meta.get("top_gap"),
            )
        except Exception as exc:
            if not TUNING_FORCE_HEURISTIC_FALLBACK_ON_ERROR:
                raise
            legacy = self._legacy_jd_context_trace(
                job_id=job_id,
                jd_text=jd_text,
                query_text=query_text,
                limit=limit,
            )
            return ContextSelectionTrace(
                text=legacy.text,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=0.0,
                candidate_count=legacy.candidate_count,
                selected_count=legacy.selected_count,
                cache_hit=legacy.cache_hit,
                selection_mode="retrieval_fallback_legacy",
                fallback_reason=str(exc),
                retrieval_candidate_count=0,
                top_score=None,
                top_gap=None,
            )

    def _select_relevant_cv_context_trace(self, *, cv_master: str, query_text: str, limit: int = 8) -> ContextSelectionTrace:
        if not TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE:
            return self._legacy_cv_context_trace(
                cv_master=cv_master,
                query_text=query_text,
                limit=limit,
            )
        started = time.perf_counter()
        cache_key = f"cvctx_retrieval::{self._hash_text(cv_master)}:{self._hash_text(query_text)}:{limit}"
        cached = self._ctx_cache.get(cache_key)
        if cached:
            return ContextSelectionTrace(
                text=cached,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=0.0,
                candidate_count=0,
                selected_count=max(1, min(limit, len([part for part in cached.split('\n\n') if part.strip()]))),
                cache_hit=True,
                selection_mode="retrieval_cache",
                fallback_reason="",
                retrieval_candidate_count=max(1, min(limit, TUNING_RETRIEVAL_TOP_K)),
                top_score=None,
                top_gap=None,
            )
        try:
            candidates = split_text_chunks(cv_master, max_chars=850, overlap_chars=120)
            selected, candidate_count, meta = self._rank_context_candidates(
                query_text=query_text,
                candidates=candidates,
                limit=max(1, min(limit, TUNING_RERANK_TOP_K)),
            )
            if not selected:
                raise ValueError("retrieval_empty")
            result = "\n\n".join(selected).strip() or str(cv_master or "").strip()
            self._store_ctx_cache(cache_key, result)
            return ContextSelectionTrace(
                text=result,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=float(meta.get("rerank_ms") or 0.0),
                candidate_count=candidate_count,
                selected_count=len(selected),
                cache_hit=False,
                selection_mode=str(meta.get("selection_mode") or "retrieval_rerank"),
                fallback_reason="",
                retrieval_candidate_count=candidate_count,
                top_score=meta.get("top_score"),
                top_gap=meta.get("top_gap"),
            )
        except Exception as exc:
            if not TUNING_FORCE_HEURISTIC_FALLBACK_ON_ERROR:
                raise
            legacy = self._legacy_cv_context_trace(
                cv_master=cv_master,
                query_text=query_text,
                limit=limit,
            )
            return ContextSelectionTrace(
                text=legacy.text,
                total_ms=(time.perf_counter() - started) * 1000,
                rerank_ms=0.0,
                candidate_count=legacy.candidate_count,
                selected_count=legacy.selected_count,
                cache_hit=legacy.cache_hit,
                selection_mode="retrieval_fallback_legacy",
                fallback_reason=str(exc),
                retrieval_candidate_count=0,
                top_score=None,
                top_gap=None,
            )

    def _select_relevant_jd_context(self, *, job_id: int, jd_text: str, query_text: str, limit: int = 6) -> str:
        return self._select_relevant_jd_context_trace(
            job_id=job_id,
            jd_text=jd_text,
            query_text=query_text,
            limit=limit,
        ).text

    def _select_relevant_cv_context(self, *, cv_master: str, query_text: str, limit: int = 8) -> str:
        return self._select_relevant_cv_context_trace(
            cv_master=cv_master,
            query_text=query_text,
            limit=limit,
        ).text

    def _store_ctx_cache(self, key: str, value: str) -> None:
        if len(self._ctx_cache) >= self._ctx_cache_limit:
            self._ctx_cache.pop(next(iter(self._ctx_cache)))
        self._ctx_cache[key] = value
        if TUNING_ENABLE_PERSISTED_CONTEXT_CACHE or TUNING_ENABLE_PERSISTED_CACHE:
            self._cache_put(key, value)

    @staticmethod
    def _resolve_llm_backend(usage: dict[str, Any] | None) -> str:
        payload = usage if isinstance(usage, dict) else {}
        backend = str(payload.get("llm_backend") or "").strip()
        if backend:
            return backend
        if payload.get("fallback") is True:
            return "fallback_heuristic"
        if payload:
            return "gateway_chat_completions"
        return ""

    def _local_fallback_llm(
        self,
        *,
        job_context: dict[str, Any],
        cv_master: str,
        jd_text: str,
        reason: str = "fallback",
    ) -> dict[str, Any]:
        title = str((job_context or {}).get("title") or "").strip()
        company = str((job_context or {}).get("company") or "").strip()
        summary = self._compose_local_summary(title=title, jd_text=jd_text, cv_master=cv_master)
        cv_text = self._compose_local_cv(cv_master=cv_master, title=title)
        cover_letter = self._compose_local_cover_letter(title=title, company=company, summary=summary, jd_text=jd_text)
        return {
            "cv_text": cv_text,
            "cover_letter": cover_letter,
            "headline": title or self._build_local_headline(jd_text=jd_text),
            "summary": summary,
            "experience_summary": self._extract_experience_summary(cv_text=cv_text),
            "notes": [
                "Generated by embedded local fallback mode with JD-aware phrasing.",
                "Transferable skills were emphasized without claiming unsupported experience.",
            ],
            "_llm_backend": "fallback_heuristic",
            "_llm_model": "",
            "_usage": {"fallback": True, "fallback_reason": reason},
        }


    @staticmethod
    def _extract_keywords(text: str, *, limit: int = 3) -> list[str]:
        patterns = [
            r"\.net",
            r"c#",
            r"asp\.net",
            r"azure",
            r"java",
            r"python",
            r"spring boot",
            r"microservices?",
            r"apis?",
            r"react",
            r"typescript",
            r"aws",
            r"kubernetes",
            r"docker",
        ]
        found: list[str] = []
        lowered = str(text or "").lower()
        for pattern in patterns:
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(0)
            normalized = value.upper() if value.lower() in {"c#", ".net"} else value.title()
            if normalized not in found:
                found.append(normalized)
            if len(found) >= limit:
                break
        return found

    def _compose_local_summary(self, *, title: str, jd_text: str, cv_master: str) -> str:
        target_stack = self._extract_keywords(f"{title}\n{jd_text}", limit=2)
        candidate_stack = self._extract_keywords(cv_master, limit=4)
        candidate_text = ", ".join(candidate_stack) if candidate_stack else "backend API delivery, system integration, and production support"
        motivation = " The profile also signals strong interest in joining the target team and contributing durable engineering value over time."
        if any(token in {".NET", "C#"} for token in target_stack):
            return (
                f"Backend engineer with hands-on delivery experience across {candidate_text}. "
                f"While direct {', '.join(target_stack)} experience is not explicit in the source CV, the profile shows adjacent platform engineering depth, "
                "ownership of maintainable systems, and the ability to ramp quickly into a new production stack."
                f"{motivation}"
            )
        if target_stack:
            return (
                f"Engineer with delivery experience across {candidate_text}, aligned to roles needing {', '.join(target_stack)}. "
                "The profile emphasizes transferable backend fundamentals, production ownership, and fast adaptation to unfamiliar domain tooling."
                f"{motivation}"
            )
        return (
            f"Engineer with delivery experience across {candidate_text}, focused on maintainable backend systems, measurable execution, "
            "and fast ramp-up into new product and technology domains."
            f"{motivation}"
        )

    @staticmethod
    def _build_local_headline(*, jd_text: str) -> str:
        for line in str(jd_text or "").splitlines():
            text = line.strip(" -:\t")
            if 4 <= len(text) <= 120:
                return text
        return "Target Role"

    def _compose_local_cover_letter(self, *, title: str, company: str, summary: str, jd_text: str) -> str:
        target = title or "the role"
        at_company = f" at {company}" if company else ""
        target_stack = self._extract_keywords(f"{title}\n{jd_text}", limit=2)
        gap_line = ""
        if any(token in {".NET", "C#"} for token in target_stack):
            gap_line = (
                f" Although my background does not show direct {', '.join(target_stack)} delivery yet, "
                "it does show adjacent backend engineering experience and a track record of learning new stacks quickly enough to deliver in production."
            )
        contribution_line = (
            f" I want the opportunity to contribute to {company}'s engineering work in a meaningful, long-term way."
            if company
            else " I want the opportunity to contribute meaningfully to the team over the long term."
        )
        return (
            f"Dear Hiring Team{at_company},\n\n"
            f"I am excited to apply for {target}. {summary}{gap_line}{contribution_line}\n\n"
            "I focus on clear execution, measurable impact, maintainable engineering quality, and translating adjacent experience into fast, practical delivery while supporting the team's longer-term goals.\n\n"
            "Thank you for your time and consideration.\n"
        )

    @staticmethod
    def _compose_local_cv(*, cv_master: str, title: str) -> str:
        base = str(cv_master or "").strip()
        if not base:
            header = title or "CV Output"
            return (
                f"<bold><center>{header}</center></bold>\n"
                "<bold><green>Professional Summary</green></bold>\n"
                "- Generated by embedded local fallback mode.\n"
            )
        if not title:
            return base + "\n"
        lines = base.splitlines()
        rebuilt: list[str] = []
        replaced = False
        for line in lines:
            stripped = line.strip()
            if (
                not replaced
                and stripped.startswith("<center>")
                and stripped.endswith("</center>")
                and "|" not in stripped
            ):
                rebuilt.append(f"<center>{title}</center>")
                replaced = True
            else:
                rebuilt.append(line)
        return "\n".join(rebuilt).strip() + "\n"

    @staticmethod
    def _strip_cv_tags(value: str) -> str:
        return re.sub(r"</?(bold|italic|green|orange|center|size:\d+)>", "", str(value or ""), flags=re.IGNORECASE).strip()

    def _extract_headline(self, *, cv_text: str, job_context: dict[str, Any]) -> str:
        lines = [self._strip_cv_tags(line) for line in str(cv_text or "").splitlines()]
        lines = [line for line in lines if line]
        if len(lines) >= 2:
            first = lines[0]
            second = lines[1]
            if first.upper() == first and ("|" in second or len(second.split()) >= 4):
                return second[:250]
        for line in lines:
            if "@" in line or "dob:" in line.lower():
                continue
            return line[:250]
        return str((job_context or {}).get("title") or "").strip()[:250]

    def _extract_summary(self, *, cv_text: str) -> str:
        lines = [self._strip_cv_tags(line) for line in str(cv_text or "").splitlines()]
        lines = [line for line in lines if line]
        capture = False
        collected: list[str] = []
        for line in lines:
            lower = line.lower()
            if "professional summary" in lower:
                capture = True
                continue
            if capture and ("experience" in lower or "technical skills" in lower or "education" in lower):
                break
            if capture:
                collected.append(line)
        if collected:
            return " ".join(collected)[:2000]
        bullet_lines = [line.lstrip("- ").strip() for line in lines if line.strip().startswith("- ")]
        if bullet_lines:
            return " ".join(bullet_lines[:3])[:2000]
        return " ".join(lines[1:4] if len(lines) > 1 else lines[:4])[:2000]

    def _extract_experience_summary(self, *, cv_text: str) -> str:
        lines = [self._strip_cv_tags(line) for line in str(cv_text or "").splitlines()]
        lines = [line for line in lines if line]
        in_work = False
        current_role = ""
        current_company = ""
        bullets: list[str] = []
        sections: list[tuple[str, str, list[str]]] = []
        for line in lines:
            lower = line.lower()
            if "work experience" in lower:
                in_work = True
                continue
            if not in_work:
                continue
            if "technical skills" in lower or "education" in lower:
                break
            if line.startswith("- "):
                bullets.append(line.lstrip("- ").strip())
                continue
            if "|" in line and not line.lower().startswith("http"):
                if current_role or bullets:
                    sections.append((current_role, current_company, bullets[:]))
                parts = [part.strip() for part in line.split("|", 1)]
                current_role = parts[0]
                current_company = parts[1] if len(parts) > 1 else ""
                bullets = []
        if current_role or bullets:
            sections.append((current_role, current_company, bullets[:]))

        sentences: list[str] = []
        for role, company, role_bullets in sections:
            if not role_bullets:
                continue
            opening = f"At {company}, I worked as {role}" if company else f"I worked as {role}"
            chosen = role_bullets[:2]
            detail = "; ".join(bullet[:220].rstrip(".") for bullet in chosen)
            if detail:
                sentences.append(f"{opening}, where I {detail[0].lower() + detail[1:]}.")
        text = " ".join(sentences).strip()
        words = text.split()
        if len(words) > 300:
            text = " ".join(words[:300]).rstrip(" ,;:.") + "."
        return text[:6000]

    def _allow_no_key_for_base_url(self, base_url: str) -> bool:
        explicit = os.getenv("OPENAI_ALLOW_NO_KEY", "").strip().lower()
        if explicit in {"1", "true", "yes", "y"}:
            return True
        try:
            host = (urlparse(base_url).hostname or "").strip().lower()
        except Exception:
            host = ""
        return host in {"127.0.0.1", "localhost"}

    def _resolve_openai_api_key(self) -> str:
        direct = os.getenv("OPENAI_API_KEY", "").strip()
        if direct:
            return direct
        if self.env_file.exists():
            try:
                for line in self.env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    raw = line.strip()
                    if not raw or raw.startswith("#") or "=" not in raw:
                        continue
                    key, value = raw.split("=", 1)
                    if key.strip() == "OPENAI_API_KEY":
                        return value.strip().strip("'").strip('"')
            except Exception as exc:
                self.logger.warning("Failed reading .env for OPENAI_API_KEY: %s", exc)
        return ""

    def _next_run_folder(self, jd_slug: str) -> Path:
        self.raw_cv_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%y%m%d")
        pattern = re.compile(rf"^{re.escape(stamp)}_(\d{{2}})_.+$")
        next_id = 1
        for p in self.raw_cv_root.iterdir():
            if not p.is_dir():
                continue
            match = pattern.match(p.name)
            if match:
                next_id = max(next_id, int(match.group(1)) + 1)
        return self.raw_cv_root / f"{stamp}_{next_id:02d}_{jd_slug}"

    def _venv_python(self) -> Path:
        py = self.project_root / ".venv" / "Scripts" / "python.exe"
        return py if py.exists() else Path("python")

    def _run_subprocess(self, cmd: list[str]) -> None:
        self.logger.info("Subprocess start | cmd=%s", cmd)
        env = os.environ.copy()
        env["PYTHONHOME"] = ""
        env["PYTHONPATH"] = ""
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            cmd,
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=env,
        )
        if completed.returncode != 0:
            self.logger.error(
                "Subprocess failed | cmd=%s returncode=%s stdout=%s stderr=%s",
                cmd,
                completed.returncode,
                completed.stdout[-1200:],
                completed.stderr[-1200:],
            )
            raise ValueError(
                "Command failed: "
                + " ".join(cmd)
                + f"\nstdout:\n{completed.stdout[-1000:]}\nstderr:\n{completed.stderr[-1200:]}"
            )
        self.logger.info("Subprocess done | cmd=%s", cmd)

    @staticmethod
    def _slugify(value: str) -> str:
        text = CvRewriteService._strip_compensation_for_filename(str(value or "").strip())
        # Never expose local DB ids in output names (e.g. job_457).
        text = re.sub(r"(?i)(^|[^a-zA-Z0-9]+)job_\d+(?=[^a-zA-Z0-9]+|$)", r"\1", text)
        # File names must not contain dots in role/company segments and should
        # never end up with repeated special separators like "_-" or "__".
        text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
        text = re.sub(r"(?i)(?:^|_)\d+(?:_\d+)?h(?:rs?|ours?)?(?:_(?:week|wk|day|month|year|yr))?(?=_|$)", "_", text)
        text = re.sub(r"(?i)(?:^|_)\d+(?:_\d+)+(?:_per)?_(?:hr|hour|day|week|month|year|yr)(?=_|$)", "_", text)
        text = re.sub(r"(?i)(?:^|_)\d+(?:k|m)?(?:_per)?_(?:hr|hour|day|week|month|year|yr)(?=_|$)", "_", text)
        text = re.sub(r"(?i)(?:^|_)(?:salary|compensation|rate|pay)(?=_|$)", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        # Windows MAX_PATH safety: keep slug short so run folders + file names stay < 260 chars.
        return (text or "jd")[:96]

    @staticmethod
    def _strip_schedule_for_filename(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"[â€â€‘â€’â€“â€”âˆ’]+", "-", text)
        patterns = [
            r"(?i)\b\d+(?:[.,]\d+)?\s*-\s*\d+(?:[.,]\d+)?\s*h(?:rs?|ours?)?\s*(?:/|\bper\b\s*)?(?:week|wk|day|month|year|yr)\b",
            r"(?i)\b\d+(?:[.,]\d+)?\s+\d+(?:[.,]\d+)?\s*h(?:rs?|ours?)?\s*(?:/|\bper\b\s*)?(?:week|wk|day|month|year|yr)\b",
            r"(?i)\b\d+(?:[.,]\d+)?\s*h(?:rs?|ours?)?\s*(?:/|\bper\b\s*)?(?:week|wk|day|month|year|yr)\b",
            r"(?i)\b\d+(?:_\d+)?h(?:rs?|ours?)?(?:_(?:week|wk|day|month|year|yr))\b",
            r"(?i)\b\d+(?:[.,]\d+)?\s*h(?:rs?|ours?)?\b",
        ]
        for pattern in patterns:
            text = re.sub(pattern, " ", text)
        return re.sub(r"\s+", " ", text).strip(" -_â€“")

    @staticmethod
    def _strip_compensation_for_filename(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = CvRewriteService._strip_schedule_for_filename(text)
        text = re.sub(r"[‐‑‒–—−]+", "-", text)
        patterns = [
            r"(?i)\b(?:usd|eur|gbp|cad|aud|sgd|inr|vnd)\s*\d+(?:[.,]\d+)?(?:\s*[-–to]+\s*(?:usd|eur|gbp|cad|aud|sgd|inr|vnd)?\s*\d+(?:[.,]\d+)?)?\s*(?:/|\bper\b\s*)?(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)[₹$€£]\s*\d+(?:[.,]\d+)?(?:\s*[-–to]+\s*[₹$€£]?\s*\d+(?:[.,]\d+)?)?\s*(?:/|\bper\b\s*)?(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)(?:[₹$€£]\s*)?\d+(?:[.,]\d+)?(?:k|m)?\s*-\s*(?:[₹$€£]\s*)?\d+(?:[.,]\d+)?(?:k|m)?\s*(?:/|\bper\b\s*)?(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)\b\d+(?:[.,]\d+)?(?:k|m)?\s*[-–to]+\s*\d+(?:[.,]\d+)?(?:k|m)?\s*(?:/|\bper\b\s*)?(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)\bup\s+to\s+[₹$€£]?\s*\d+(?:[.,]\d+)?(?:k|m)?\s*(?:/|\bper\b\s*)?(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)\b[₹$€£]?\s*\d+(?:[.,]\d+)?(?:k|m)?\s*(?:/|\bper\b\s*)?(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)\b\d+(?:_\d+)+(?:_per)?_(?:hr|hour|day|week|month|year|yr)\b",
            r"(?i)\b[₹$€£]?\d+(?:k|m)?_(?:per_)?(?:hr|hour|day|week|month|year|yr)\b",
        ]
        for pattern in patterns:
            text = re.sub(pattern, " ", text)
        text = re.sub(r"(?i)\b(?:salary|compensation|rate|pay)\b", " ", text)
        text = re.sub(r"\(\s*\)", " ", text)
        text = re.sub(r"\[\s*\]", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" -_–")
        return text

    def _build_output_basename(self, *, cv_master: str, job_context: dict[str, Any], run_folder: Path) -> str:
        candidate = self._extract_candidate_name(cv_master)
        company = self._normalize_company_for_filename(str((job_context or {}).get("company") or ""))
        title = self._normalize_role_for_filename(str((job_context or {}).get("title") or ""))
        base = f"{candidate}_{company}_{title}"
        slug = self._slugify(base)
        if not slug.lower().startswith("cv_"):
            slug = f"CV_{slug}"
        return slug[:140]

    @staticmethod
    def _build_company_folder_name(company: str) -> str:
        text = str(company or "").strip()
        if not text:
            return "Company"
        slug = CvRewriteService._slugify(text)
        return slug[:80] or "Company"

    @staticmethod
    def _build_cover_letter_output_basename(cv_output_basename: str) -> str:
        base = str(cv_output_basename or "").strip()
        if base.lower().startswith("cv_"):
            return f"COVER_LETTER_{base[3:]}"
        return f"COVER_LETTER_{base}"

    def _next_artifact_version(self, company_documents_dir: Path) -> int:
        highest = 0
        for path in company_documents_dir.iterdir():
            if not path.is_dir():
                continue
            match = re.match(r"^CV(\d+)$", path.name, flags=re.IGNORECASE)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1

    def _reserve_output_path(self, preferred_path: Path) -> Path:
        preferred = Path(preferred_path)
        preferred.parent.mkdir(parents=True, exist_ok=True)
        if self._path_is_writable(preferred):
            return preferred

        stem = preferred.stem
        suffix = preferred.suffix
        for index in range(2, 1000):
            candidate = preferred.with_name(f"{stem}_{index}{suffix}")
            if self._path_is_writable(candidate):
                self.logger.warning(
                    "Output path locked or unavailable, using alternate path | preferred=%s selected=%s",
                    preferred,
                    candidate,
                )
                return candidate
        raise ValueError(f"No writable output path available for {preferred}")

    @staticmethod
    def _path_is_writable(path: Path) -> bool:
        target = Path(path)
        parent = target.parent
        if not parent.exists():
            return False
        if not target.exists():
            try:
                with tempfile.NamedTemporaryFile(dir=parent, delete=True):
                    pass
                return True
            except OSError:
                return False
        try:
            with open(target, "ab"):
                return True
        except OSError:
            return False

    @staticmethod
    def _documents_date_folder() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _extract_candidate_name(self, cv_master: str) -> str:
        text = str(cv_master or "")
        center_match = re.search(r"<center>\s*(.*?)\s*</center>", text, flags=re.IGNORECASE | re.DOTALL)
        if center_match:
            candidate = re.sub(r"\s+", " ", center_match.group(1)).strip()
            if candidate:
                return self._slugify(candidate.replace(" ", "_"))
        return "Dinh_Cong_Thanh"

    @staticmethod
    def _normalize_company_for_filename(company: str) -> str:
        text = CvRewriteService._strip_compensation_for_filename(str(company or "").strip())
        if not text:
            return "Company"
        text = re.sub(r"[^\w\s&.-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        words = [word.capitalize() if word.islower() else word for word in text.split()]
        return " ".join(words) or "Company"

    @classmethod
    def _normalize_role_for_filename(cls, title: str) -> str:
        text = cls._strip_compensation_for_filename(str(title or "").strip())
        if not text:
            return "Role"

        replacements = {
            ".net": "DotNet",
            "asp.net": "AspNet",
            "c#": "CSharp",
            "node.js": "NodeJS",
            "next.js": "NextJS",
            "vue.js": "Vue",
            "react.js": "React",
            "sr.": "Senior",
            "sr ": "Senior ",
            "jr.": "Junior",
            "jr ": "Junior ",
        }
        lowered = text.lower()
        for raw, repl in replacements.items():
            lowered = lowered.replace(raw, repl)
        text = lowered

        primary = re.split(r"\s[-|:]\s", text, maxsplit=1)[0].strip()
        paren_parts = re.findall(r"\((.*?)\)", primary)
        primary_no_paren = re.sub(r"\(.*?\)", "", primary).strip()

        tech_tokens: list[str] = []
        skip_words = {
            "remote", "fully remote", "hybrid", "europe", "usa", "uk", "germany",
            "france", "spain", "insurance", "fintech", "disruption", "part time", "full time",
        }
        for part in paren_parts:
            normalized = re.sub(r"[/,]+", " ", part)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if not normalized:
                continue
            if normalized.lower() in skip_words:
                continue
            for token in normalized.split():
                token_clean = token.strip()
                if not token_clean:
                    continue
                if token_clean.lower() in skip_words:
                    continue
                tech_tokens.append(token_clean)

        combined = " ".join([primary_no_paren, *tech_tokens]).strip()
        combined = cls._strip_compensation_for_filename(combined)
        combined = re.sub(r"\b100\s*remote\b", "", combined, flags=re.IGNORECASE)
        combined = re.sub(r"\bfully\s+remote\b", "", combined, flags=re.IGNORECASE)
        combined = re.sub(r"\bremote\b", "", combined, flags=re.IGNORECASE)
        combined = re.sub(r"\beurope\b", "", combined, flags=re.IGNORECASE)
        combined = re.sub(r"(?i)(?:^|[\s_-])\d+(?:[\s_-]\d+)?h(?:rs?|ours?)?(?:[\s_-](?:week|wk|day|month|year|yr))?", " ", combined)
        combined = re.sub(r"(?i)\b\d+(?:[.,]\d+)?h(?:rs?|ours?)?\b", "", combined)
        combined = re.sub(r"(?i)\b(?:hr|hour|day|week|month|year|yr)\b", "", combined)
        combined = re.sub(r"(?<![A-Za-z])\d+(?:[.,]\d+)?(?![A-Za-z])", "", combined)
        combined = re.sub(r"[^\w\s-]+", " ", combined)
        combined = re.sub(r"\s+", " ", combined).strip(" -_")
        words = [word for word in combined.split() if word]
        if len(words) > 8:
            words = words[:8]
        pretty_words = [word.capitalize() if word.islower() else word for word in words]
        return " ".join(pretty_words) or "Role"
