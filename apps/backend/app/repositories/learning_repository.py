from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.repositories.database import Database


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_text(*parts: str) -> str:
    joined = "||".join(str(part or "").strip().lower() for part in parts)
    return sha256(joined.encode("utf-8")).hexdigest()


class LearningRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_source(
        self,
        *,
        source_key: str,
        source_type: str,
        label: str,
        uri: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_sources (source_key, source_type, label, uri, meta_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                  source_type = excluded.source_type,
                  label = excluded.label,
                  uri = excluded.uri,
                  meta_json = excluded.meta_json,
                  updated_at = excluded.updated_at
                """,
                (
                    source_key,
                    source_type,
                    label,
                    uri,
                    json.dumps(meta or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM learning_sources WHERE source_key = ?", (source_key,)).fetchone()
        item = dict(row)
        item["meta_json"] = json.loads(item.get("meta_json") or "{}")
        return item

    def upsert_topic(self, *, topic_key: str, name_en: str, name_vi: str = "", sort_order: int = 0) -> dict[str, Any]:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_topics (topic_key, name_en, name_vi, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_key) DO UPDATE SET
                  name_en = excluded.name_en,
                  name_vi = excluded.name_vi,
                  sort_order = excluded.sort_order,
                  updated_at = excluded.updated_at
                """,
                (topic_key, name_en, name_vi, sort_order, now, now),
            )
            row = conn.execute("SELECT * FROM learning_topics WHERE topic_key = ?", (topic_key,)).fetchone()
        return dict(row)

    def upsert_question(
        self,
        *,
        topic_id: int,
        source_id: int,
        source_question_key: str,
        question_en: str,
        question_vi: str,
        answer_en: str,
        answer_vi: str,
        explanation_en: str,
        explanation_vi: str,
        language: str,
        difficulty: str,
        embedding: list[float],
        chunk_count: int,
    ) -> dict[str, Any]:
        now = _now_iso()
        question_hash = _hash_text(str(topic_id), question_en or question_vi)
        content_hash = _hash_text(question_en, question_vi, answer_en, answer_vi, explanation_en, explanation_vi)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_questions (
                  topic_id, source_id, source_question_key, question_en, question_vi,
                  answer_en, answer_vi, explanation_en, explanation_vi, language,
                  difficulty, question_hash, content_hash, embedding_json, chunk_count,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(question_hash) DO UPDATE SET
                  topic_id = excluded.topic_id,
                  source_id = excluded.source_id,
                  source_question_key = excluded.source_question_key,
                  question_en = excluded.question_en,
                  question_vi = excluded.question_vi,
                  answer_en = excluded.answer_en,
                  answer_vi = excluded.answer_vi,
                  explanation_en = excluded.explanation_en,
                  explanation_vi = excluded.explanation_vi,
                  language = excluded.language,
                  difficulty = excluded.difficulty,
                  content_hash = excluded.content_hash,
                  embedding_json = excluded.embedding_json,
                  chunk_count = excluded.chunk_count,
                  updated_at = excluded.updated_at
                """,
                (
                    topic_id,
                    source_id,
                    source_question_key,
                    question_en,
                    question_vi,
                    answer_en,
                    answer_vi,
                    explanation_en,
                    explanation_vi,
                    language,
                    difficulty,
                    question_hash,
                    content_hash,
                    json.dumps(embedding or [], ensure_ascii=False),
                    int(chunk_count or 0),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM learning_questions WHERE question_hash = ?", (question_hash,)).fetchone()
        item = dict(row)
        item["embedding_json"] = json.loads(item.get("embedding_json") or "[]")
        return item

    def replace_answers(self, question_id: int, answers: list[dict[str, Any]]) -> None:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM learning_answers WHERE question_id = ?", (question_id,))
            for answer in answers:
                answer_en = str(answer.get("answer_en") or "").strip()
                answer_vi = str(answer.get("answer_vi") or "").strip()
                conn.execute(
                    """
                    INSERT INTO learning_answers (
                      question_id, answer_en, answer_vi, is_correct, answer_hash, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        answer_en,
                        answer_vi,
                        int(bool(answer.get("is_correct", False))),
                        _hash_text(answer_en, answer_vi, str(answer.get("is_correct", False))),
                        str(answer.get("source") or "seed_md"),
                        now,
                        now,
                    ),
                )

    def replace_chunks(self, question_id: int, chunks: list[dict[str, Any]]) -> None:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM learning_question_chunks WHERE question_id = ?", (question_id,))
            for index, chunk in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO learning_question_chunks (
                      question_id, chunk_index, chunk_text, embedding_json, token_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        index,
                        str(chunk.get("chunk_text") or ""),
                        json.dumps(chunk.get("embedding") or [], ensure_ascii=False),
                        int(chunk.get("token_count") or 0),
                        now,
                        now,
                    ),
                )

    def list_chunks_by_question(self, question_id: int, limit: int = 5) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_index, chunk_text
                FROM learning_question_chunks
                WHERE question_id = ?
                ORDER BY chunk_index
                LIMIT ?
                """,
                (int(question_id), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_topics(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  t.*,
                  COUNT(q.id) AS question_count
                FROM learning_topics t
                LEFT JOIN learning_questions q ON q.topic_id = t.id
                GROUP BY t.id
                ORDER BY t.sort_order, t.name_en
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_topic_by_key(self, topic_key: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM learning_topics WHERE topic_key = ?", (topic_key,)).fetchone()
        return dict(row) if row is not None else None

    def list_questions_by_topic(self, topic_id: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_questions WHERE topic_id = ? ORDER BY id",
                (topic_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["embedding_json"] = json.loads(item.get("embedding_json") or "[]")
            items.append(item)
        return items

    def get_questions_by_ids(self, question_ids: list[int]) -> list[dict[str, Any]]:
        ids = [int(x) for x in question_ids if int(x) > 0]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM learning_questions WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["embedding_json"] = json.loads(item.get("embedding_json") or "[]")
            items.append(item)
        return items

    def get_answers_for_question(self, question_id: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_answers WHERE question_id = ? ORDER BY is_correct DESC, id ASC",
                (question_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_questions_missing_explanation(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  id, topic_id, question_en, question_vi, answer_en, answer_vi,
                  explanation_en, explanation_vi,
                  explanation_en_draft, explanation_vi_draft,
                  explanation_quality, explanation_generated_by, explanation_prompt_version,
                  explanation_overlap_ratio, explanation_needs_review, explanation_input_hash,
                  explanation_information_gain_score, explanation_dimensions_present,
                  explanation_publishable, explanation_rejected_reason, explanation_generation_stage
                FROM learning_questions
                WHERE (COALESCE(explanation_en, '') = '' AND COALESCE(explanation_vi, '') = '')
                ORDER BY id
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_questions_for_explanation_enrichment(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  q.id,
                  q.topic_id,
                  q.difficulty,
                  t.topic_key,
                  q.question_en,
                  q.question_vi,
                  q.answer_en,
                  q.answer_vi,
                  q.explanation_en,
                  q.explanation_vi,
                  q.explanation_en_draft,
                  q.explanation_vi_draft,
                  COALESCE(q.explanation_quality, '') AS explanation_quality,
                  COALESCE(q.explanation_generated_by, '') AS explanation_generated_by,
                  COALESCE(q.explanation_prompt_version, '') AS explanation_prompt_version,
                  COALESCE(q.explanation_overlap_ratio, 0) AS explanation_overlap_ratio,
                  COALESCE(q.explanation_needs_review, 0) AS explanation_needs_review,
                  COALESCE(q.explanation_input_hash, '') AS explanation_input_hash,
                  COALESCE(q.explanation_information_gain_score, 0) AS explanation_information_gain_score,
                  COALESCE(q.explanation_dimensions_present, '') AS explanation_dimensions_present,
                  COALESCE(q.explanation_publishable, 0) AS explanation_publishable,
                  COALESCE(q.explanation_rejected_reason, '') AS explanation_rejected_reason,
                  COALESCE(q.explanation_generation_stage, '') AS explanation_generation_stage,
                  COALESCE(q.content_hash, '') AS content_hash
                FROM learning_questions q
                LEFT JOIN learning_topics t ON t.id = q.topic_id
                ORDER BY q.id
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_question_needs_enrichment(self, question_id: int) -> None:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE learning_questions
                SET explanation_quality = ?, explanation_needs_review = 1, updated_at = ?
                WHERE id = ?
                """,
                ("needs_enrichment", now, int(question_id)),
            )

    def update_question_explanation(
        self,
        question_id: int,
        *,
        explanation_en: str,
        explanation_vi: str,
        explanation_en_draft: str,
        explanation_vi_draft: str,
        explanation_quality: str | None = None,
        explanation_generated_by: str | None = None,
        explanation_prompt_version: str | None = None,
        explanation_overlap_ratio: float | None = None,
        explanation_needs_review: bool | None = None,
        explanation_input_hash: str | None = None,
        explanation_information_gain_score: float | None = None,
        explanation_dimensions_present: str | None = None,
        explanation_publishable: bool | None = None,
        explanation_rejected_reason: str | None = None,
        explanation_generation_stage: str | None = None,
    ) -> None:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE learning_questions
                SET explanation_en = CASE WHEN ? THEN ? ELSE explanation_en END,
                    explanation_vi = CASE WHEN ? THEN ? ELSE explanation_vi END,
                    explanation_en_draft = COALESCE(?, explanation_en_draft),
                    explanation_vi_draft = COALESCE(?, explanation_vi_draft),
                    explanation_quality = COALESCE(?, explanation_quality),
                    explanation_generated_by = COALESCE(?, explanation_generated_by),
                    explanation_prompt_version = COALESCE(?, explanation_prompt_version),
                    explanation_overlap_ratio = COALESCE(?, explanation_overlap_ratio),
                    explanation_needs_review = COALESCE(?, explanation_needs_review),
                    explanation_input_hash = COALESCE(?, explanation_input_hash),
                    explanation_information_gain_score = COALESCE(?, explanation_information_gain_score),
                    explanation_dimensions_present = COALESCE(?, explanation_dimensions_present),
                    explanation_publishable = COALESCE(?, explanation_publishable),
                    explanation_rejected_reason = COALESCE(?, explanation_rejected_reason),
                    explanation_generation_stage = COALESCE(?, explanation_generation_stage),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    bool(explanation_publishable),
                    explanation_en,
                    bool(explanation_publishable),
                    explanation_vi,
                    explanation_en_draft,
                    explanation_vi_draft,
                    explanation_quality,
                    explanation_generated_by,
                    explanation_prompt_version,
                    explanation_overlap_ratio,
                    int(bool(explanation_needs_review)) if explanation_needs_review is not None else None,
                    explanation_input_hash,
                    explanation_information_gain_score,
                    explanation_dimensions_present,
                    int(bool(explanation_publishable)) if explanation_publishable is not None else None,
                    explanation_rejected_reason,
                    explanation_generation_stage,
                    now,
                    int(question_id),
                ),
            )

    def count_questions(self) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT COUNT(1) AS c FROM learning_questions").fetchone()
        return int(row["c"] or 0)

    def list_correct_answers_for_topic(self, topic_id: int, *, exclude_question_id: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [topic_id]
        where = "q.topic_id = ? AND a.is_correct = 1"
        if exclude_question_id is not None:
            where += " AND q.id <> ?"
            params.append(int(exclude_question_id))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT a.*, q.id AS question_id
                FROM learning_answers a
                JOIN learning_questions q ON q.id = a.question_id
                WHERE {where}
                ORDER BY a.id
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_distractors(self, question_id: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM distractors WHERE question_id = ? ORDER BY id",
                (question_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_distractors(self, question_id: int, distractors: list[dict[str, Any]]) -> None:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM distractors WHERE question_id = ?", (question_id,))
            for item in distractors:
                text_en = str(item.get("distractor_en") or "").strip()
                text_vi = str(item.get("distractor_vi") or "").strip()
                conn.execute(
                    """
                    INSERT INTO distractors (
                      question_id, distractor_en, distractor_vi, distractor_hash, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        question_id,
                        text_en,
                        text_vi,
                        _hash_text(text_en, text_vi),
                        str(item.get("source") or "rule_based"),
                        now,
                        now,
                    ),
                )

    def create_quiz_attempt(self, *, topic_id: int | None, lang: str, score: int, total: int) -> int:
        now = _now_iso()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO quiz_attempts (topic_id, lang, score, total, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic_id, lang, score, total, now),
            )
            return int(cur.lastrowid)

    def insert_quiz_attempt_item(
        self,
        *,
        attempt_id: int,
        question_id: int,
        selected_answer_id: int | None,
        selected_answer_text: str,
        is_correct: bool,
        choices: list[dict[str, Any]],
        explanation_en: str,
        explanation_vi: str,
    ) -> None:
        now = _now_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_attempt_items (
                  attempt_id, question_id, selected_answer_id, selected_answer_text, is_correct,
                  choices_json, explanation_en, explanation_vi, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    question_id,
                    selected_answer_id,
                    selected_answer_text,
                    int(bool(is_correct)),
                    json.dumps(choices, ensure_ascii=False),
                    explanation_en,
                    explanation_vi,
                    now,
                ),
            )

    def list_quiz_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  qa.*,
                  COALESCE(t.topic_key, '') AS topic_key,
                  COALESCE(t.name_en, '') AS topic_name_en,
                  COALESCE(t.name_vi, '') AS topic_name_vi
                FROM quiz_attempts qa
                LEFT JOIN learning_topics t ON t.id = qa.topic_id
                ORDER BY qa.id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]
