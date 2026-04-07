from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from app.config import (
    PROJECT_ROOT,
    TUNING_CACHE_VERSION,
    TUNING_CHUNK_CACHE_ENABLED,
    TUNING_ENRICH_CHUNK_LIMIT,
    TUNING_ENRICH_MAX_BATCH,
    TUNING_ENRICH_MAX_RUNTIME_SEC,
)
from app.repositories.learning_repository import LearningRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.explanation_enrichment_service import ExplanationEnrichmentService
from app.services.text_vector_utils import build_hashed_embedding, split_text_chunks, tokenize_vector_text


class LearningService:
    TOPIC_SOURCES: dict[str, list[str]] = {
        "python_concurrency": [
            "https://docs.python.org/3/library/asyncio-task.html",
            "https://docs.python.org/3/library/concurrent.futures.html",
        ],
        "fastapi": [
            "https://fastapi.tiangolo.com/tutorial/dependencies/",
            "https://fastapi.tiangolo.com/tutorial/sql-databases/",
        ],
        "react": [
            "https://react.dev/learn",
            "https://react.dev/reference/react/useEffect",
        ],
        "sql_optimization": [
            "https://www.postgresql.org/docs/current/indexes-intro.html",
            "https://use-the-index-luke.com/",
        ],
    }

    def __init__(self, repo: LearningRepository, schedule_repo: ScheduleRepository | None = None) -> None:
        self.repo = repo
        self.schedule_repo = schedule_repo
        self.logger = logging.getLogger("job_ops.learning")
        self._chunk_cache: dict[str, dict[str, Any]] = {}
        self._chunk_cache_limit = 512

    @staticmethod
    def _slugify(value: str) -> str:
        text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
        return text.strip("_")

    @staticmethod
    def _stable_hash(*parts: str) -> str:
        return sha256("||".join(str(part or "").strip().lower() for part in parts).encode("utf-8")).hexdigest()

    def _chunk_and_embed_cached(self, text: str, *, max_chars: int, overlap_chars: int) -> tuple[list[str], list[float]]:
        """
        Lightweight per-process cache to avoid recomputing chunks/embeddings for identical text.
        Safe because inputs are deterministic and cached only in memory.
        """
        normalized = str(text or "")
        key = self._stable_hash(TUNING_CACHE_VERSION, normalized, str(max_chars), str(overlap_chars))
        if TUNING_CHUNK_CACHE_ENABLED:
            cached = self._chunk_cache.get(key)
            if cached:
                return cached["chunks"], cached["embedding"]
        chunks = split_text_chunks(normalized, max_chars=max_chars, overlap_chars=overlap_chars)
        embedding = build_hashed_embedding(normalized)
        if TUNING_CHUNK_CACHE_ENABLED:
            if len(self._chunk_cache) >= self._chunk_cache_limit:
                # Drop oldest by popping first inserted key
                self._chunk_cache.pop(next(iter(self._chunk_cache)))
            self._chunk_cache[key] = {"chunks": chunks, "embedding": embedding}
        return chunks, embedding

    def ensure_seed_data(self, *, seed_path: str | Path = "learning_plan.md") -> dict[str, Any]:
        return self.import_learning_markdown(seed_path=seed_path, source_key="seed_md")

    def ensure_seed_if_empty(self, *, seed_path: str | Path = "learning_plan.md") -> dict[str, Any] | None:
        if self.repo.count_questions() > 0:
            return None
        return self.ensure_seed_data(seed_path=seed_path)

    def ensure_default_job(self, *, enqueue_if_empty: bool = False) -> dict[str, Any]:
        """
        Backward-compatible startup hook.

        The old learning queue processor was removed, but app startup still calls this
        method. Keep a no-op shim so the API can boot safely without recreating the
        retired background job flow.
        """
        result = {
            "ok": True,
            "status": "noop",
            "enqueue_if_empty": bool(enqueue_if_empty),
            "reason": "legacy_learning_default_job_removed",
        }
        self.logger.info("Learning default job shim | %s", json.dumps(result, ensure_ascii=False))
        return result

    def import_learning_markdown(self, *, seed_path: str | Path, source_key: str = "seed_md") -> dict[str, Any]:
        file_path = Path(seed_path)
        if not file_path.is_absolute():
            file_path = (PROJECT_ROOT / file_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Learning seed file not found: {file_path}")

        text = file_path.read_text(encoding="utf-8", errors="ignore")
        parsed = self._parse_learning_plan(text)
        source = self.repo.upsert_source(
            source_key=source_key,
            source_type="seed_md",
            label="learning_plan.md",
            uri=str(file_path),
            meta={"content_hash": self._stable_hash(text), "topic_count": len(parsed)},
        )

        imported_questions = 0
        topic_count = 0
        for topic_index, topic in enumerate(parsed, start=1):
            topic_row = self.repo.upsert_topic(
                topic_key=topic["topic_key"],
                name_en=topic["topic_name_en"],
                name_vi=topic["topic_name_vi"],
                sort_order=topic_index,
            )
            topic_count += 1
            for item in topic["items"]:
                question_texts = "\n\n".join(
                    part
                    for part in [
                        item.get("question_en", ""),
                        item.get("answer_en", ""),
                        item.get("explanation_en", ""),
                        item.get("question_vi", ""),
                        item.get("answer_vi", ""),
                    ]
                    if str(part or "").strip()
                )
                chunks, embedding = self._chunk_and_embed_cached(question_texts, max_chars=700, overlap_chars=120)
                question_row = self.repo.upsert_question(
                    topic_id=int(topic_row["id"]),
                    source_id=int(source["id"]),
                    source_question_key=f'{topic["topic_key"]}:{item["index"]}',
                    question_en=item.get("question_en", ""),
                    question_vi=item.get("question_vi", ""),
                    answer_en=item.get("answer_en", ""),
                    answer_vi=item.get("answer_vi", ""),
                    explanation_en=item.get("explanation_en", ""),
                    explanation_vi=item.get("explanation_vi", ""),
                    language="bilingual" if item.get("question_vi") or item.get("answer_vi") else "en",
                    difficulty=item.get("difficulty", ""),
                    embedding=embedding,
                    chunk_count=len(chunks),
                )
                self.repo.replace_answers(
                    int(question_row["id"]),
                    [
                        {
                            "answer_en": item.get("answer_en", ""),
                            "answer_vi": item.get("answer_vi", ""),
                            "is_correct": True,
                            "source": source_key,
                        }
                    ],
                )
                self.repo.replace_chunks(
                    int(question_row["id"]),
                    [
                        {
                            "chunk_text": chunk,
                            "embedding": build_hashed_embedding(chunk),
                            "token_count": len(tokenize_vector_text(chunk)),
                        }
                        for chunk in chunks
                    ],
                )
                self._ensure_distractors_cached(question_row)
                imported_questions += 1

        summary = {
            "ok": True,
            "source": source_key,
            "seed_path": str(file_path),
            "topics": topic_count,
            "questions": imported_questions,
        }
        self.logger.info("Learning seed import complete | %s", json.dumps(summary, ensure_ascii=False))
        return summary

    def list_topics(self) -> list[dict[str, Any]]:
        return self.repo.list_topics()

    def get_quiz(self, *, topic_key: str, limit: int = 5, lang: str = "en") -> dict[str, Any]:
        topic = self.repo.get_topic_by_key(topic_key)
        if topic is None:
            raise ValueError(f"Unknown topic: {topic_key}")
        questions = self.repo.list_questions_by_topic(int(topic["id"]))
        if not questions:
            return {"topic": topic, "items": []}
        seed = int(self._stable_hash(topic_key, str(limit))[:8], 16)
        rng = random.Random(seed)
        picked = list(questions)
        rng.shuffle(picked)
        picked = picked[: max(1, min(limit, len(picked)))]

        items = []
        for question in picked:
            answers = self.repo.get_answers_for_question(int(question["id"]))
            correct = next((item for item in answers if int(item.get("is_correct") or 0) == 1), None)
            if correct is None:
                continue
            distractors = self._ensure_distractors_cached(question)
            choices = [
                {
                    "id": int(correct["id"]),
                    "text_en": correct.get("answer_en", ""),
                    "text_vi": correct.get("answer_vi", ""),
                    "is_correct": True,
                }
            ]
            for distractor in distractors[:3]:
                choices.append(
                    {
                        "id": -int(distractor["id"]),
                        "text_en": distractor.get("distractor_en", ""),
                        "text_vi": distractor.get("distractor_vi", ""),
                        "is_correct": False,
                    }
                )
            rng.shuffle(choices)
            items.append(
                {
                    "question_id": int(question["id"]),
                    "topic_key": topic["topic_key"],
                    "question": question.get("question_vi") if lang == "vi" and question.get("question_vi") else question.get("question_en", ""),
                    "question_en": question.get("question_en", ""),
                    "question_vi": question.get("question_vi", ""),
                    "explanation_en": question.get("explanation_en", ""),
                    "explanation_vi": question.get("explanation_vi", ""),
                    "choices": [
                        {
                            "answer_id": int(choice["id"]),
                            "text": choice.get("text_vi") if lang == "vi" and choice.get("text_vi") else choice.get("text_en", ""),
                            "text_en": choice.get("text_en", ""),
                            "text_vi": choice.get("text_vi", ""),
                        }
                        for choice in choices
                    ],
                }
            )
        return {
            "topic": {
                "topic_key": topic["topic_key"],
                "name": topic.get("name_vi") if lang == "vi" and topic.get("name_vi") else topic.get("name_en", ""),
                "name_en": topic.get("name_en", ""),
                "name_vi": topic.get("name_vi", ""),
            },
            "lang": lang,
            "items": items,
        }

    def get_topic_knowledge(self, *, topic_key: str, limit: int = 20, lang: str = "en") -> dict[str, Any]:
        topic = self.repo.get_topic_by_key(topic_key)
        if topic is None:
            raise ValueError(f"Unknown topic: {topic_key}")
        questions = self.repo.list_questions_by_topic(int(topic["id"]))
        topic_payload = {
            "topic_key": topic["topic_key"],
            "name": topic.get("name_vi") if lang == "vi" and topic.get("name_vi") else topic.get("name_en", ""),
            "name_en": topic.get("name_en", ""),
            "name_vi": topic.get("name_vi", ""),
        }
        if not questions:
            return {"topic": topic_payload, "lang": lang, "items": []}

        items: list[dict[str, Any]] = []
        ordered_questions = sorted(questions, key=lambda q: int(q.get("id") or 0))
        max_items = max(1, min(int(limit), len(ordered_questions)))
        fallback_service = ExplanationEnrichmentService()
        for question in ordered_questions[:max_items]:
            answers = self.repo.get_answers_for_question(int(question["id"]))
            correct = next((row for row in answers if int(row.get("is_correct") or 0) == 1), None)
            answer_en = (correct or {}).get("answer_en") or question.get("answer_en", "")
            answer_vi = (correct or {}).get("answer_vi") or question.get("answer_vi", "")
            explanation_en = question.get("explanation_en", "") or ""
            explanation_vi = question.get("explanation_vi", "") or ""
            explanation_en_draft = question.get("explanation_en_draft", "") or ""
            explanation_vi_draft = question.get("explanation_vi_draft", "") or ""
            final_explanation_en = explanation_en or explanation_en_draft
            final_explanation_vi = explanation_vi or explanation_vi_draft
            explanation_source = "published" if (explanation_en or explanation_vi) else ("draft" if (explanation_en_draft or explanation_vi_draft) else "empty")
            if not final_explanation_en and not final_explanation_vi:
                fallback_en, fallback_vi = fallback_service.build_domain_fallback(
                    topic_key=topic.get("topic_key"),
                    question_style=str(question.get("difficulty") or "general"),
                )
                if not fallback_en and not fallback_vi:
                    fallback_en = (
                        "Why this is correct: the answer summarizes the key mechanism and trade-offs. "
                        "When to use: prefer the approach that matches the workload constraints. "
                        "Practical check: measure latency/throughput and verify behavior in logs."
                    )
                    fallback_vi = (
                        "Vi sao dung: cau tra loi tong hop co che va danh doi chinh. "
                        "Khi dung: chon cach phu hop voi rang buoc tai. "
                        "Kiem tra: do latency/throughput va doi chieu log."
                    )
                final_explanation_en = fallback_en
                final_explanation_vi = fallback_vi
                explanation_source = "fallback"
                try:
                    self.logger.info("Knowledge fallback applied | question_id=%s topic=%s", question.get("id"), topic.get("topic_key"))
                except Exception:
                    pass
            items.append(
                {
                    "question_id": int(question["id"]),
                    "topic_key": topic["topic_key"],
                    "question": question.get("question_vi") if lang == "vi" and question.get("question_vi") else question.get("question_en", ""),
                    "question_en": question.get("question_en", ""),
                    "question_vi": question.get("question_vi", ""),
                    "answer": answer_vi if lang == "vi" and answer_vi else answer_en,
                    "answer_en": answer_en,
                    "answer_vi": answer_vi,
                    "explanation": final_explanation_vi if lang == "vi" and final_explanation_vi else final_explanation_en,
                    "explanation_en": final_explanation_en,
                    "explanation_vi": final_explanation_vi,
                    "explanation_source": explanation_source,
                    "difficulty": question.get("difficulty", ""),
                    "source_question_key": question.get("source_question_key", ""),
                }
            )

        return {"topic": topic_payload, "lang": lang, "items": items}

    def submit_quiz(self, *, topic_key: str, lang: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        topic = self.repo.get_topic_by_key(topic_key)
        if topic is None:
            raise ValueError(f"Unknown topic: {topic_key}")
        question_ids = [int(item.get("question_id") or 0) for item in items if int(item.get("question_id") or 0) > 0]
        questions = {int(row["id"]): row for row in self.repo.get_questions_by_ids(question_ids)}
        score = 0
        results = []
        prepared_attempt_items = []
        for item in items:
            question_id = int(item.get("question_id") or 0)
            question = questions.get(question_id)
            if question is None:
                continue
            answers = self.repo.get_answers_for_question(question_id)
            correct = next((row for row in answers if int(row.get("is_correct") or 0) == 1), None)
            if correct is None:
                continue
            selected_answer_id = item.get("selected_answer_id")
            selected_text = str(item.get("selected_text") or "").strip()
            is_correct = False
            if selected_answer_id is not None and int(selected_answer_id) == int(correct["id"]):
                is_correct = True
            elif selected_text:
                selected_norm = selected_text.strip().lower()
                is_correct = selected_norm in {
                    str(correct.get("answer_en") or "").strip().lower(),
                    str(correct.get("answer_vi") or "").strip().lower(),
                }
            if is_correct:
                score += 1
            distractors = self._ensure_distractors_cached(question)
            choice_snapshot = [
                {
                    "text_en": correct.get("answer_en", ""),
                    "text_vi": correct.get("answer_vi", ""),
                    "is_correct": True,
                }
            ]
            for distractor in distractors[:3]:
                choice_snapshot.append(
                    {
                        "text_en": distractor.get("distractor_en", ""),
                        "text_vi": distractor.get("distractor_vi", ""),
                        "is_correct": False,
                    }
                )
            results.append(
                {
                    "question_id": question_id,
                    "question": question.get("question_vi") if lang == "vi" and question.get("question_vi") else question.get("question_en", ""),
                    "selected_text": selected_text,
                    "correct_answer": correct.get("answer_vi") if lang == "vi" and correct.get("answer_vi") else correct.get("answer_en", ""),
                    "correct_answer_en": correct.get("answer_en", ""),
                    "correct_answer_vi": correct.get("answer_vi", ""),
                    "explanation": question.get("explanation_vi") if lang == "vi" and question.get("explanation_vi") else question.get("explanation_en", ""),
                    "explanation_en": question.get("explanation_en", ""),
                    "explanation_vi": question.get("explanation_vi", ""),
                    "is_correct": is_correct,
                }
            )
            prepared_attempt_items.append(
                {
                    "question_id": question_id,
                    "selected_answer_id": int(selected_answer_id) if selected_answer_id else None,
                    "selected_answer_text": selected_text,
                    "is_correct": is_correct,
                    "choices": choice_snapshot,
                    "explanation_en": question.get("explanation_en", ""),
                    "explanation_vi": question.get("explanation_vi", ""),
                }
            )

        attempt_id = self.repo.create_quiz_attempt(
            topic_id=int(topic["id"]),
            lang=lang,
            score=score,
            total=len(prepared_attempt_items),
        )
        for prepared in prepared_attempt_items:
            self.repo.insert_quiz_attempt_item(attempt_id=attempt_id, **prepared)

        return {
            "attempt_id": attempt_id,
            "topic_key": topic_key,
            "lang": lang,
            "score": score,
            "total": len(prepared_attempt_items),
            "results": results,
        }

    def get_quiz_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.list_quiz_history(limit)

    def run_learning_etl(self, payload: dict[str, Any]) -> dict[str, Any]:
        seed_result = self.import_learning_markdown(
            seed_path=payload.get("seed_path", "learning_plan.md"),
            source_key="seed_md",
        )
        theory_backfill = self._backfill_theory_from_answers(limit=payload.get("backfill_limit", 500))
        crawl_candidates = self._collect_daily_crawl_candidates(payload)
        explanation_enrichment = self._enrich_explanations(payload)
        return {
            "ok": True,
            "mode": "learning_etl",
            "seed_import": seed_result,
            "theory_backfill": theory_backfill,
            "crawl_candidates_added": len(crawl_candidates),
            "explanation_enrichment": explanation_enrichment,
            "daily_target_per_topic": int(payload.get("daily_target_per_topic", 20)),
        }

    def _backfill_theory_from_answers(self, limit: int = 500) -> dict[str, Any]:
        missing = self.repo.list_questions_missing_explanation(limit=limit)
        marked = 0
        skipped_no_answer = 0
        for row in missing:
            answer_en = str(row.get("answer_en") or "").strip()
            answer_vi = str(row.get("answer_vi") or "").strip()
            if not answer_en and not answer_vi:
                skipped_no_answer += 1
                continue
            # Mark for mandatory enrichment instead of copying answer into explanation.
            self.repo.mark_question_needs_enrichment(int(row["id"]))
            marked += 1
        return {"missing_before": len(missing), "marked_needs_enrichment": marked, "skipped_no_answer": skipped_no_answer}

    def _enrich_explanations(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Keep enrichment lightweight for local CPU environments.
        service = ExplanationEnrichmentService()
        limit = max(1, min(int(payload.get("explanation_batch_limit", TUNING_ENRICH_MAX_BATCH)), 200))
        chunk_limit = max(1, min(int(payload.get("explanation_chunk_limit", TUNING_ENRICH_CHUNK_LIMIT)), 5))
        rows = self.repo.list_questions_for_explanation_enrichment(limit=limit)

        reviewed = 0
        skipped_cached = 0
        enriched = 0
        fallback_used = 0
        failed = 0
        review_needed = 0
        started_at = datetime.now(timezone.utc)
        max_runtime = max(30, int(payload.get("explanation_max_runtime_sec", TUNING_ENRICH_MAX_RUNTIME_SEC)))

        for idx, row in enumerate(rows, start=1):
            question_id = int(row["id"])
            question = str(row.get("question_en") or row.get("question_vi") or "").strip()
            answer = str(row.get("answer_en") or row.get("answer_vi") or "").strip()
            if not question or not answer:
                continue

            chunks = self.repo.list_chunks_by_question(question_id, limit=chunk_limit)
            context_text = "\n\n".join(str(chunk.get("chunk_text") or "").strip() for chunk in chunks if str(chunk.get("chunk_text") or "").strip())
            input_hash = service.build_input_hash(question=question, answer=answer, context_text=context_text)

            existing_explanation_en = str(row.get("explanation_en") or "").strip()
            existing_explanation_vi = str(row.get("explanation_vi") or "").strip()
            existing_assessment = service.assess_existing(
                answer=answer,
                explanation_en=existing_explanation_en,
                explanation_vi=existing_explanation_vi,
            )

            if (
                existing_assessment["is_valid"]
                and bool(int(row.get("explanation_publishable") or 0))
                and str(row.get("explanation_input_hash") or "") == input_hash
                and int(row.get("explanation_needs_review") or 0) == 0
            ):
                skipped_cached += 1
                continue

            requires_enrichment = (
                not existing_explanation_en
                or not existing_assessment["is_valid"]
                or int(row.get("explanation_needs_review") or 0) == 1
                or float(row.get("explanation_overlap_ratio") or 0) > service.max_overlap
                or str(row.get("explanation_quality") or "").strip().lower() in {"", "low", "needs_enrichment"}
            )
            if not requires_enrichment:
                reviewed += 1
                continue

            try:
                result = service.generate(
                    question=question,
                    answer=answer,
                    context_text=context_text,
                    topic_key=str(row.get("topic_key") or ""),
                    question_style=str(row.get("difficulty") or "general"),
                )
                self.repo.update_question_explanation(
                    question_id,
                    explanation_en=result.explanation_en,
                    explanation_vi=result.explanation_vi,
                    explanation_en_draft=result.explanation_en,
                    explanation_vi_draft=result.explanation_vi,
                    explanation_quality=result.quality,
                    explanation_generated_by=result.generated_by,
                    explanation_prompt_version=result.prompt_version,
                    explanation_overlap_ratio=result.overlap_ratio,
                    explanation_needs_review=result.needs_review,
                    explanation_input_hash=result.input_hash,
                    explanation_information_gain_score=result.information_gain_score,
                    explanation_dimensions_present=",".join(result.dimensions_present),
                    explanation_publishable=result.publishable,
                    explanation_rejected_reason=result.rejected_reason,
                    explanation_generation_stage=result.generation_stage,
                )
                enriched += 1
                if result.used_fallback:
                    fallback_used += 1
                if not result.publishable:
                    review_needed += 1
            except Exception:
                failed += 1
                self.logger.exception("Explanation enrichment failed | question_id=%s", question_id)
            reviewed += 1
            elapsed_sec = (datetime.now(timezone.utc) - started_at).total_seconds()
            if elapsed_sec >= max_runtime:
                self.logger.warning(
                    "Enrichment batch stopped due to max runtime | processed=%s elapsed=%.1fs limit=%ss",
                    idx,
                    elapsed_sec,
                    max_runtime,
                )
                break

        return {
            "reviewed": reviewed,
            "skipped_cached": skipped_cached,
            "enriched": enriched,
            "fallback_used": fallback_used,
            "failed": failed,
            "needs_review": review_needed,
            "batch_limit": limit,
            "chunk_limit": chunk_limit,
            "elapsed_seconds": round((datetime.now(timezone.utc) - started_at).total_seconds(), 3),
        }

    def _collect_daily_crawl_candidates(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not bool(payload.get("crawl_enabled", True)):
            return []

        topic_keys = payload.get("topic_keys") or list(self.TOPIC_SOURCES.keys())
        per_topic_limit = int(payload.get("crawl_per_topic_limit") or payload.get("daily_target_per_topic") or 10)
        per_topic_limit = max(1, min(per_topic_limit, 50))
        crawl_sources_override: dict[str, list[str]] = {}
        if payload.get("crawl_sources"):
            # optional override: same list for all topics
            crawl_sources_override = {key: list(payload["crawl_sources"]) for key in topic_keys}

        added: list[dict[str, Any]] = []
        for topic_key in topic_keys:
            urls = crawl_sources_override.get(topic_key) or self.TOPIC_SOURCES.get(topic_key, [])
            if not urls:
                continue
            fetched_items: list[dict[str, str]] = []
            for url in urls:
                try:
                    html = self._fetch_url_text(url)
                    if not str(html or "").strip():
                        continue
                    fetched_items.extend(self._extract_qa_from_text(html, topic_key, url))
                except Exception:
                    self.logger.exception("Crawl failed | topic=%s url=%s", topic_key, url)
            if not fetched_items:
                continue
            # keep stable ordering, cap per_topic_limit
            for item in fetched_items[:per_topic_limit]:
                added.append(self._upsert_crawled_item(topic_key, item))
        return [x for x in added if x]

    def _fetch_url_text(self, url: str) -> str:
        # Migrate known retired docs URLs to active pages to reduce crawl noise.
        url_aliases = {
            "https://fastapi.tiangolo.com/advanced/async-sql-databases/": "https://fastapi.tiangolo.com/tutorial/sql-databases/",
        }
        target_url = url_aliases.get(url, url)

        with httpx.Client(timeout=httpx.Timeout(8.0, read=8.0, connect=4.0)) as client:
            resp = client.get(target_url, follow_redirects=True)
            if resp.status_code == 404:
                self.logger.warning("Crawl skipped (404) | url=%s resolved_url=%s", url, target_url)
                return ""
            resp.raise_for_status()
            text = resp.text
            # Trim very long pages to reduce parsing overhead
            return text[:300_000]

    def _extract_qa_from_text(self, html: str, topic_key: str, url: str) -> list[dict[str, str]]:
        # Build a wider evidence window so explanation drafts have learning value.
        text = re.sub(r"<(script|style)[\\s\\S]*?>[\\s\\S]*?</\\1>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        lines = [re.sub(r"\\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        qa: list[dict[str, str]] = []
        question_prefixes = ("what", "how", "why", "when", "where", "can", "should", "is", "are", "does", "do")
        for idx, line in enumerate(lines):
            low = line.lower()
            if not any(low.startswith(p) for p in question_prefixes):
                continue
            answer = ""
            for nxt in lines[idx + 1 : idx + 8]:
                if len(nxt) > 30:
                    answer = nxt
                    break
            if not answer:
                continue
            evidence_window = [nxt for nxt in lines[idx + 1 : idx + 10] if len(nxt) > 20][:4]
            explanation_draft = self._build_crawl_explanation_draft(question=line, answer=answer, evidence_lines=evidence_window)
            qa.append(
                {
                    "question_en": line,
                    "answer_en": answer,
                    "explanation_en": explanation_draft,
                    "source_url": url,
                    "evidence_window": " ".join(evidence_window),
                    "parser_version": "crawl.v2.evidence-window",
                    "question_vi": "",
                    "answer_vi": "",
                    "explanation_vi": "",
                }
            )
        return qa

    @staticmethod
    def _build_crawl_explanation_draft(question: str, answer: str, evidence_lines: list[str]) -> str:
        # Keep crawl output structured so later enrichment can refine instead of replacing from scratch.
        evidence = " ".join(str(line or "").strip() for line in evidence_lines if str(line or "").strip())
        why = "Why this is likely correct: the nearby documentation context supports this answer for the question scope."
        when = (
            "When to use / not use: apply this guidance when your runtime behavior matches the documented scenario, "
            "and avoid blindly applying it to CPU-heavy or blocking execution paths."
        )
        profile = (
            "Practical check: run a focused benchmark after warm-up, compare latency and throughput, and verify "
            "the behavior under representative load."
        )
        if evidence:
            why = f"{why} Evidence: {evidence[:260]}"
        return "\n\n".join([why, when, profile])

    def _upsert_crawled_item(self, topic_key: str, item: dict[str, str]) -> dict[str, Any] | None:
        topic = self.repo.get_topic_by_key(topic_key)
        if topic is None:
            return None
        source_key = f"crawl::{self._stable_hash(item.get('source_url', ''), datetime.now(timezone.utc).date())}"
        source = self.repo.upsert_source(
            source_key=source_key,
            source_type="official_docs",
            label=item.get("source_url") or "crawl",
            uri=item.get("source_url") or "",
            meta={
                "topic_key": topic_key,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "parser_version": item.get("parser_version", "crawl.v2.evidence-window"),
                "evidence_window": item.get("evidence_window", ""),
            },
        )
        question_texts = "\n\n".join(
            part
            for part in [
                item.get("question_en", ""),
                item.get("answer_en", ""),
                item.get("explanation_en", ""),
                item.get("question_vi", ""),
                item.get("answer_vi", ""),
            ]
            if str(part or "").strip()
        )
        chunks, embedding = self._chunk_and_embed_cached(question_texts, max_chars=700, overlap_chars=120)
        question_row = self.repo.upsert_question(
            topic_id=int(topic["id"]),
            source_id=int(source["id"]),
            source_question_key=f"{topic_key}:{self._stable_hash(item.get('question_en', ''), item.get('source_url', ''))[:12]}",
            question_en=item.get("question_en", ""),
            question_vi=item.get("question_vi", ""),
            answer_en=item.get("answer_en", ""),
            answer_vi=item.get("answer_vi", ""),
            explanation_en=item.get("explanation_en", ""),
            explanation_vi=item.get("explanation_vi", ""),
            language="bilingual" if item.get("question_vi") or item.get("answer_vi") else "en",
            difficulty=item.get("difficulty", "intermediate"),
            embedding=embedding,
            chunk_count=len(chunks),
        )
        self.repo.replace_answers(
            int(question_row["id"]),
            [
                {
                    "answer_en": item.get("answer_en", ""),
                    "answer_vi": item.get("answer_vi", ""),
                    "is_correct": True,
                    "source": "crawl",
                }
            ],
        )
        self.repo.replace_chunks(
            int(question_row["id"]),
            [
                {
                    "chunk_text": chunk,
                    "embedding": build_hashed_embedding(chunk),
                    "token_count": len(tokenize_vector_text(chunk)),
                }
                for chunk in chunks
            ],
        )
        self.repo.mark_question_needs_enrichment(int(question_row["id"]))
        self._ensure_distractors_cached(question_row)
        return question_row

    def _ensure_distractors_cached(self, question: dict[str, Any]) -> list[dict[str, Any]]:
        existing = self.repo.get_distractors(int(question["id"]))
        if existing:
            return existing
        candidates = self.repo.list_correct_answers_for_topic(int(question["topic_id"]), exclude_question_id=int(question["id"]))
        distractors: list[dict[str, Any]] = []
        seen = set()
        for candidate in candidates:
            text_en = str(candidate.get("answer_en") or "").strip()
            text_vi = str(candidate.get("answer_vi") or "").strip()
            key = self._stable_hash(text_en, text_vi)
            if not text_en or key in seen:
                continue
            distractors.append(
                {
                    "distractor_en": text_en,
                    "distractor_vi": text_vi,
                    "source": "topic_pool",
                }
            )
            seen.add(key)
            if len(distractors) >= 3:
                break
        while len(distractors) < 3:
            base_en = str(question.get("answer_en") or "Use the same approach for every scenario.").strip()
            base_vi = str(question.get("answer_vi") or "DÃ¹ng cÃ¹ng má»™t cÃ¡ch cho má»i trÆ°á»ng há»£p.").strip()
            variant_index = len(distractors) + 1
            distractors.append(
                {
                    "distractor_en": self._rule_based_distractor(base_en, variant_index, "en"),
                    "distractor_vi": self._rule_based_distractor(base_vi or base_en, variant_index, "vi"),
                    "source": "rule_based",
                }
            )
        self.repo.replace_distractors(int(question["id"]), distractors[:3])
        return self.repo.get_distractors(int(question["id"]))

    @staticmethod
    def _rule_based_distractor(value: str, variant_index: int, lang: str) -> str:
        base = str(value or "").strip().rstrip(".")
        if lang == "vi":
            variants = [
                f"LuÃ´n Ã¡p dá»¥ng má»™t cÃ¡ch cá»‘ Ä‘á»‹nh: {base}.",
                f"Chá»‰ táº­p trung vÃ o máº·c Ä‘á»‹nh thay vÃ¬ ngá»¯ cáº£nh thá»±c táº¿: {base}.",
                f"Bá» qua Ä‘Ã¡nh giÃ¡ trade-off vÃ  chá»n ngay phÆ°Æ¡ng Ã¡n nÃ y: {base}.",
            ]
        else:
            variants = [
                f"Always apply a single default rule: {base}.",
                f"Ignore context and rely only on this default approach: {base}.",
                f"Skip trade-off analysis and choose this path every time: {base}.",
            ]
        return variants[(variant_index - 1) % len(variants)]


    def _parse_learning_plan(self, content: str) -> list[dict[str, Any]]:
        """
        Parse markdown following the structure already present in learning_plan.md.

        We accept both English and Vietnamese sections and are tolerant to line-ending
        differences (\n / \r\n) plus dash variants in headers.
        """

        topic_pattern = re.compile(r'^##\s+(?P<name>.+?)\s+[\-\u2013\u2014]\s+Top Questions\s*$', re.MULTILINE)
        topic_matches = list(topic_pattern.finditer(content))

        parsed_topics: list[dict[str, Any]] = []

        for index, match in enumerate(topic_matches):
            start = match.end()
            end = topic_matches[index + 1].start() if index + 1 < len(topic_matches) else len(content)
            section = content[start:end]
            topic_name = match.group('name').strip()
            topic_key = self._slugify(topic_name)

            vi_marker = 'Phi\u00ean b\u1ea3n ti\u1ebfng Vi\u1ec7t'
            vi_start = section.find(vi_marker)
            english_section = section if vi_start == -1 else section[:vi_start]
            vi_section = '' if vi_start == -1 else section[vi_start:]

            english_items: list[dict[str, Any]] = []
            blocks = re.split(r'^### Question\s+', english_section, flags=re.MULTILINE)
            for block in blocks[1:]:
                first_line_end = block.find("\n")
                if first_line_end == -1:
                    continue
                header = block[:first_line_end].strip()
                if ':' not in header:
                    continue
                idx_str, question = header.split(':', 1)
                try:
                    idx = int(idx_str.strip())
                except ValueError:
                    continue
                answer_match = re.search(r'^\*\*Answer:\*\*\s*(.+)', block, flags=re.MULTILINE)
                explanation_match = re.search(r'^\*\*Explanation:\*\*\s*\n([\s\S]+?)(?:\n\*\*Example:\*\*\s*\n([\s\S]+))?$', block.strip(), flags=re.MULTILINE)
                answer = answer_match.group(1).strip() if answer_match else ''
                explanation = explanation_match.group(1).strip() if explanation_match else ''
                example = (explanation_match.group(2) or '').strip() if explanation_match else ''
                if example:
                    explanation = f"{explanation}\n\nExample:\n{example}"
                english_items.append(
                    {
                        'index': idx,
                        'question_en': question.strip(),
                        'answer_en': answer,
                        'explanation_en': explanation,
                    }
                )

            vi_items_map: dict[int, dict[str, str]] = {}
            if vi_section:
                for line_match in re.finditer(
                    r'(?m)^\s*(?P<idx>\d+)\.\s+\*\*C\u00e2u h\u1ecfi:\*\*\s+(?P<question>.+?)\s*$\s*^\s*-\s+\*\*Tr\u1ea3 l\u1eddi:\*\*\s+(?P<answer>.+?)\s*$',
                    vi_section,
                ):
                    vi_items_map[int(line_match.group('idx'))] = {
                        'question_vi': line_match.group('question').strip(),
                        'answer_vi': line_match.group('answer').strip(),
                    }

            topic_name_vi = topic_name if not topic_name.startswith('SQL /') else 'SQL / T\u1ed1i \u01b0u'

            items = []
            for item in english_items:
                vi_item = vi_items_map.get(item['index'], {})
                items.append(
                    {
                        **item,
                        'question_vi': vi_item.get('question_vi', ''),
                        'answer_vi': vi_item.get('answer_vi', ''),
                        'explanation_vi': '',
                    }
                )

            parsed_topics.append(
                {
                    'topic_key': topic_key,
                    'topic_name_en': topic_name,
                    'topic_name_vi': topic_name_vi,
                    'items': items,
                }
            )

        return parsed_topics

