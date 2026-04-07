from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.repositories.database import Database
from app.services.location_normalizer import COUNTRY_TO_REGION, REGION_MEMBERSHIP_MAP, infer_region, normalize_country
from app.services.programming_language_extractor import INVALID_LANGUAGE_VALUES, extract_programming_languages
from app.services.text_vector_utils import build_hashed_embedding, split_text_chunks


class MetaRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_app_tables(self, *, run_maintenance: bool = False) -> None:
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_fit_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL,
                    cv_profile TEXT NOT NULL,
                    cv_source_path TEXT,
                    total_score REAL NOT NULL,
                    fit_hard REAL,
                    fit_medium REAL,
                    fit_soft REAL,
                    domain_score REAL NOT NULL,
                    tech_score REAL NOT NULL,
                    evidence_score REAL NOT NULL,
                    constraint_score REAL NOT NULL,
                    status TEXT NOT NULL,
                    fit_reason TEXT,
                    fit_reason_hard TEXT,
                    fit_reason_medium TEXT,
                    fit_reason_soft TEXT,
                    primary_issue_metric TEXT,
                    primary_issue_score REAL,
                    primary_issue_text TEXT,
                    main_issue TEXT,
                    matched_keywords_json TEXT,
                    missing_keywords_json TEXT,
                    evaluated_at TEXT NOT NULL,
                    evaluator_version TEXT,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
                    UNIQUE(job_post_id, cv_profile)
                );

                CREATE TABLE IF NOT EXISTS automation_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    cron_expr TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
                    pipeline_type TEXT NOT NULL,
                    crawl_config_json TEXT,
                    auto_eval_fit INTEGER NOT NULL DEFAULT 1,
                    fit_cv_profile TEXT NOT NULL DEFAULT 'full_doc_stlye',
                    auto_generate_cv INTEGER NOT NULL DEFAULT 0,
                    fit_threshold REAL NOT NULL DEFAULT 75,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id INTEGER,
                    triggered_by TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (schedule_id) REFERENCES automation_schedules(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS automation_schedule_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id INTEGER NOT NULL,
                    target_occurrence_at TEXT NOT NULL,
                    override_run_at TEXT NOT NULL,
                    override_payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (schedule_id) REFERENCES automation_schedules(id) ON DELETE CASCADE,
                    UNIQUE(schedule_id, target_occurrence_at)
                );

                CREATE INDEX IF NOT EXISTS ix_fit_job_post_id ON job_fit_scores(job_post_id);
                CREATE INDEX IF NOT EXISTS ix_automation_runs_schedule ON automation_runs(schedule_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS ix_automation_schedule_overrides_schedule
                    ON automation_schedule_overrides(schedule_id, status, override_run_at);

                CREATE TABLE IF NOT EXISTS learning_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL DEFAULT 'seed_md',
                    label TEXT NOT NULL DEFAULT '',
                    uri TEXT NOT NULL DEFAULT '',
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_key TEXT NOT NULL UNIQUE,
                    name_en TEXT NOT NULL,
                    name_vi TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL,
                    source_id INTEGER NOT NULL,
                    source_question_key TEXT NOT NULL DEFAULT '',
                    question_en TEXT NOT NULL DEFAULT '',
                    question_vi TEXT NOT NULL DEFAULT '',
                    answer_en TEXT NOT NULL DEFAULT '',
                    answer_vi TEXT NOT NULL DEFAULT '',
                    explanation_en TEXT NOT NULL DEFAULT '',
                    explanation_vi TEXT NOT NULL DEFAULT '',
                    explanation_en_draft TEXT NOT NULL DEFAULT '',
                    explanation_vi_draft TEXT NOT NULL DEFAULT '',
                    explanation_information_gain_score REAL NOT NULL DEFAULT 0,
                    explanation_dimensions_present TEXT NOT NULL DEFAULT '',
                    explanation_publishable INTEGER NOT NULL DEFAULT 0,
                    explanation_rejected_reason TEXT NOT NULL DEFAULT '',
                    explanation_generation_stage TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT 'bilingual',
                    difficulty TEXT NOT NULL DEFAULT '',
                    question_hash TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL DEFAULT '',
                    explanation_quality TEXT NOT NULL DEFAULT '',
                    explanation_generated_by TEXT NOT NULL DEFAULT '',
                    explanation_prompt_version TEXT NOT NULL DEFAULT '',
                    explanation_overlap_ratio REAL NOT NULL DEFAULT 0,
                    explanation_needs_review INTEGER NOT NULL DEFAULT 0,
                    explanation_input_hash TEXT NOT NULL DEFAULT '',
                    embedding_json TEXT NOT NULL DEFAULT '',
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (topic_id) REFERENCES learning_topics(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_id) REFERENCES learning_sources(id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS ix_learning_questions_topic
                    ON learning_questions(topic_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS learning_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    answer_en TEXT NOT NULL DEFAULT '',
                    answer_vi TEXT NOT NULL DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    answer_hash TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'seed_md',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (question_id) REFERENCES learning_questions(id) ON DELETE CASCADE,
                    UNIQUE(question_id, answer_hash)
                );

                CREATE INDEX IF NOT EXISTS ix_learning_answers_question
                    ON learning_answers(question_id, is_correct DESC);

                CREATE TABLE IF NOT EXISTS distractors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    distractor_en TEXT NOT NULL DEFAULT '',
                    distractor_vi TEXT NOT NULL DEFAULT '',
                    distractor_hash TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'rule_based',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (question_id) REFERENCES learning_questions(id) ON DELETE CASCADE,
                    UNIQUE(question_id, distractor_hash)
                );

                CREATE INDEX IF NOT EXISTS ix_distractors_question
                    ON distractors(question_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS learning_question_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL DEFAULT '',
                    embedding_json TEXT NOT NULL DEFAULT '',
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (question_id) REFERENCES learning_questions(id) ON DELETE CASCADE,
                    UNIQUE(question_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS ix_learning_question_chunks_question
                    ON learning_question_chunks(question_id, chunk_index);

                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER,
                    lang TEXT NOT NULL DEFAULT 'en',
                    score INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (topic_id) REFERENCES learning_topics(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS quiz_attempt_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    selected_answer_id INTEGER,
                    selected_answer_text TEXT NOT NULL DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    choices_json TEXT NOT NULL DEFAULT '[]',
                    explanation_en TEXT NOT NULL DEFAULT '',
                    explanation_vi TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (attempt_id) REFERENCES quiz_attempts(id) ON DELETE CASCADE,
                    FOREIGN KEY (question_id) REFERENCES learning_questions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS ix_quiz_attempt_items_attempt
                    ON quiz_attempt_items(attempt_id, question_id);

                CREATE TABLE IF NOT EXISTS schedule_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    cron_expr TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    last_enqueued_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_schedule_jobs_type
                    ON schedule_jobs(job_type, enabled);

                CREATE TABLE IF NOT EXISTS schedule_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    job_type TEXT NOT NULL,
                    queue_key TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    run_after TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    error_text TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES schedule_jobs(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS ix_schedule_queue_status
                    ON schedule_queue(status, job_type, created_at);
                CREATE INDEX IF NOT EXISTS ix_schedule_queue_job
                    ON schedule_queue(job_id, status, created_at);

                CREATE TABLE IF NOT EXISTS job_apply_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL,
                    apply_date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
                    UNIQUE(job_post_id, apply_date, source)
                );

                CREATE INDEX IF NOT EXISTS ix_job_apply_events_date
                    ON job_apply_events(apply_date, source);

                CREATE TABLE IF NOT EXISTS job_jd_contents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id INTEGER NOT NULL UNIQUE,
                    job_post_id INTEGER NOT NULL,
                    jd_text TEXT NOT NULL,
                    jd_source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (observation_id) REFERENCES job_observations(id) ON DELETE CASCADE,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS ix_job_jd_contents_job_post
                    ON job_jd_contents(job_post_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS job_text_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    source_key TEXT NOT NULL DEFAULT '',
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
                    UNIQUE(job_post_id, content_type, source_key, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS ix_job_text_embeddings_job_post
                    ON job_text_embeddings(job_post_id, content_type, source_key, chunk_index);

                CREATE TABLE IF NOT EXISTS job_generated_artifact_sets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL,
                    documents_date_folder TEXT NOT NULL DEFAULT '',
                    company_folder_name TEXT NOT NULL DEFAULT '',
                    version_number INTEGER NOT NULL DEFAULT 1,
                    run_folder_name TEXT NOT NULL DEFAULT '',
                    output_slug TEXT NOT NULL DEFAULT '',
                    output_basename TEXT NOT NULL DEFAULT '',
                    cv_text TEXT NOT NULL DEFAULT '',
                    portfolio_text TEXT NOT NULL DEFAULT '',
                    cover_letter_text TEXT NOT NULL DEFAULT '',
                    fit_report_text TEXT NOT NULL DEFAULT '',
                    headline TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    experience_summary TEXT NOT NULL DEFAULT '',
                    llm_model TEXT NOT NULL DEFAULT '',
                    llm_backend TEXT NOT NULL DEFAULT '',
                    llm_usage_json TEXT NOT NULL DEFAULT '',
                    source_kind TEXT NOT NULL DEFAULT 'rewrite',
                    materialized_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
                    UNIQUE(job_post_id, documents_date_folder, company_folder_name, version_number)
                );

                CREATE INDEX IF NOT EXISTS ix_job_generated_artifact_sets_job_post
                    ON job_generated_artifact_sets(job_post_id, updated_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS job_programming_languages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL,
                    language TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'jd_text',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
                    UNIQUE(job_post_id, language)
                );

                CREATE INDEX IF NOT EXISTS ix_job_programming_languages_job_post
                    ON job_programming_languages(job_post_id);
                CREATE INDEX IF NOT EXISTS ix_job_programming_languages_language
                    ON job_programming_languages(language);

                CREATE TABLE IF NOT EXISTS job_detail_validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL UNIQUE,
                    source_hash TEXT NOT NULL DEFAULT '',
                    posted_time TEXT NOT NULL DEFAULT '',
                    linkedin_posted_date TEXT NOT NULL DEFAULT '',
                    applicant_insight TEXT NOT NULL DEFAULT '',
                    compensation_text TEXT NOT NULL DEFAULT '',
                    work_model TEXT NOT NULL DEFAULT '',
                    employment_type TEXT NOT NULL DEFAULT '',
                    easy_apply INTEGER NOT NULL DEFAULT 0,
                    application_status TEXT NOT NULL DEFAULT '',
                    response_note TEXT NOT NULL DEFAULT '',
                    programming_language TEXT NOT NULL DEFAULT '',
                    validation_model TEXT NOT NULL DEFAULT '',
                    validation_backend TEXT NOT NULL DEFAULT '',
                    validation_usage_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS ix_job_detail_validations_job_post
                    ON job_detail_validations(job_post_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS job_location_enrichment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_post_id INTEGER NOT NULL UNIQUE,
                    raw_location TEXT,
                    normalized_country TEXT NOT NULL,
                    normalized_region TEXT,
                    region_hint TEXT,
                    confidence REAL NOT NULL DEFAULT 0.6,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS ix_job_location_enrichment_country
                    ON job_location_enrichment(normalized_country);

                CREATE TABLE IF NOT EXISTS geo_region_country_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_region TEXT NOT NULL,
                    normalized_country TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'seed',
                    updated_at TEXT NOT NULL,
                    UNIQUE(normalized_region, normalized_country)
                );

                CREATE INDEX IF NOT EXISTS ix_geo_region_country_map_region
                    ON geo_region_country_map(normalized_region);
                CREATE INDEX IF NOT EXISTS ix_geo_region_country_map_country
                    ON geo_region_country_map(normalized_country);

                CREATE TABLE IF NOT EXISTS company_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL UNIQUE,
                    priority_flag TEXT NOT NULL DEFAULT '',
                    priority_note TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_company_preferences_company_name
                    ON company_preferences(company_name);
                """
            )
            self._ensure_job_post_columns(conn)
            self._ensure_fit_columns(conn)
            self._ensure_location_columns(conn)
            self._ensure_job_application_tracking_columns(conn)
            self._ensure_learning_question_columns(conn)
            self._ensure_location_indexes(conn)
            self._seed_region_country_map(conn)
            if run_maintenance:
                self._backfill_jd_contents(conn)
                self.backfill_job_jd_embeddings()
                self._backfill_job_post_normalizations(conn)
                self._backfill_programming_languages(conn)
                self._backfill_location_enrichment(conn)
                self._sync_region_country_map_from_jobs(conn)

    @staticmethod
    def _ensure_job_post_columns(conn) -> None:
        cols = conn.execute("PRAGMA table_info(job_posts)").fetchall()
        names = {str(c["name"]) for c in cols}
        if "normalized_work_model" not in names:
            conn.execute("ALTER TABLE job_posts ADD COLUMN normalized_work_model TEXT")
        if "normalized_employment_type" not in names:
            conn.execute("ALTER TABLE job_posts ADD COLUMN normalized_employment_type TEXT")
        if "normalized_easy_apply" not in names:
            conn.execute("ALTER TABLE job_posts ADD COLUMN normalized_easy_apply INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_fit_columns(conn) -> None:
        cols = conn.execute("PRAGMA table_info(job_fit_scores)").fetchall()
        names = {str(c["name"]) for c in cols}
        if "fit_reason" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason TEXT")
        if "fit_reason_hard" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason_hard TEXT")
        if "fit_reason_medium" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason_medium TEXT")
        if "fit_reason_soft" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason_soft TEXT")
        if "primary_issue_metric" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN primary_issue_metric TEXT")
        if "primary_issue_score" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN primary_issue_score REAL")
        if "primary_issue_text" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN primary_issue_text TEXT")
        if "main_issue" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN main_issue TEXT")
        if "fit_hard" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_hard REAL")
        if "fit_medium" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_medium REAL")
        if "fit_soft" not in names:
            conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_soft REAL")

    @staticmethod
    def _ensure_location_columns(conn) -> None:
        cols = conn.execute("PRAGMA table_info(job_location_enrichment)").fetchall()
        names = {str(c["name"]) for c in cols}
        if "normalized_region" not in names:
            conn.execute("ALTER TABLE job_location_enrichment ADD COLUMN normalized_region TEXT")

    @staticmethod
    def _ensure_job_application_tracking_columns(conn) -> None:
        cols = conn.execute("PRAGMA table_info(job_application_tracking)").fetchall()
        names = {str(c["name"]) for c in cols}
        if "manual_review_required" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN manual_review_required INTEGER NOT NULL DEFAULT 0")
        if "manual_review_note" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN manual_review_note TEXT")
        if "manual_review_updated_at" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN manual_review_updated_at TEXT")
        if "priority_flag" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN priority_flag TEXT NOT NULL DEFAULT ''")
        if "priority_note" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN priority_note TEXT")
        if "priority_updated_at" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN priority_updated_at TEXT")
        if "cover_letter_path" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN cover_letter_path TEXT")
        if "applied_first_seen_at" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN applied_first_seen_at TEXT")
        if "cover_letter_docx_path" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN cover_letter_docx_path TEXT")
        if "cover_letter_pdf_path" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN cover_letter_pdf_path TEXT")
        if "generated_headline" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN generated_headline TEXT")
        if "generated_summary" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN generated_summary TEXT")
        if "generated_experience_summary" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN generated_experience_summary TEXT")
        if "generated_llm_model" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN generated_llm_model TEXT")
        if "generated_llm_backend" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN generated_llm_backend TEXT")
        if "generated_llm_usage_json" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN generated_llm_usage_json TEXT")
        if "portfolio_path" not in names:
            conn.execute("ALTER TABLE job_application_tracking ADD COLUMN portfolio_path TEXT")
        conn.execute(
            """
            UPDATE job_application_tracking
            SET applied_first_seen_at = COALESCE(
              (
                SELECT MIN(apply_date)
                FROM job_apply_events e
                WHERE e.job_post_id = job_application_tracking.job_post_id
                  AND TRIM(COALESCE(e.apply_date, '')) <> ''
              ),
              CASE
                WHEN TRIM(COALESCE(created_at, '')) <> '' THEN created_at
                WHEN TRIM(COALESCE(applied_last_seen_date, '')) <> '' THEN applied_last_seen_date
                ELSE applied_first_seen_at
              END
            )
            WHERE COALESCE(is_applied, 0) = 1
              AND TRIM(COALESCE(applied_first_seen_at, '')) = ''
            """
        )

    @staticmethod
    def _ensure_learning_question_columns(conn) -> None:
        cols = conn.execute("PRAGMA table_info(learning_questions)").fetchall()
        names = {str(c["name"]) for c in cols}
        if "explanation_quality" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_quality TEXT NOT NULL DEFAULT ''")
        if "explanation_generated_by" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_generated_by TEXT NOT NULL DEFAULT ''")
        if "explanation_prompt_version" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_prompt_version TEXT NOT NULL DEFAULT ''")
        if "explanation_overlap_ratio" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_overlap_ratio REAL NOT NULL DEFAULT 0")
        if "explanation_needs_review" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_needs_review INTEGER NOT NULL DEFAULT 0")
        if "explanation_input_hash" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_input_hash TEXT NOT NULL DEFAULT ''")
        if "explanation_en_draft" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_en_draft TEXT NOT NULL DEFAULT ''")
        if "explanation_vi_draft" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_vi_draft TEXT NOT NULL DEFAULT ''")
        if "explanation_information_gain_score" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_information_gain_score REAL NOT NULL DEFAULT 0")
        if "explanation_dimensions_present" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_dimensions_present TEXT NOT NULL DEFAULT ''")
        if "explanation_publishable" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_publishable INTEGER NOT NULL DEFAULT 0")
        if "explanation_rejected_reason" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_rejected_reason TEXT NOT NULL DEFAULT ''")
        if "explanation_generation_stage" not in names:
            conn.execute("ALTER TABLE learning_questions ADD COLUMN explanation_generation_stage TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _ensure_location_indexes(conn) -> None:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_job_location_enrichment_region
                ON job_location_enrichment(normalized_region)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_job_location_enrichment_region_country
                ON job_location_enrichment(normalized_region, normalized_country)
            """
        )

    @staticmethod
    def _backfill_jd_contents(conn) -> None:
        def _looks_like_fallback_jd(text: str) -> bool:
            sample = str(text or "").strip().lower()
            if not sample:
                return True
            return sample.startswith("job context (fallback jd):") or sample.startswith("fallback jd:")

        def _source_uses_full_page_text(source: str) -> bool:
            return "full_page_text" in str(source or "").strip().lower()

        def _clean_payload_text(value: Any) -> str:
            return re.sub(r"\s+", " ", str(value or "").replace("\r", " ").replace("\n", " ")).strip()

        def _stringify_payload_candidate(raw: Any) -> str:
            if raw in (None, ""):
                return ""
            if isinstance(raw, str):
                return raw.strip()
            if isinstance(raw, list):
                parts = [_stringify_payload_candidate(item) for item in raw]
                return "\n".join(part for part in parts if part).strip()
            if isinstance(raw, dict):
                parts: list[str] = []
                for nested_key, nested_value in raw.items():
                    rendered = _stringify_payload_candidate(nested_value)
                    if not rendered:
                        continue
                    label = str(nested_key or "").strip()
                    if label and rendered.lower() != label.lower():
                        separator = ":\n" if "\n" in rendered else ": "
                        parts.append(f"{label}{separator}{rendered}")
                    else:
                        parts.append(rendered)
                return "\n\n".join(part for part in parts if part).strip()
            return str(raw).strip()

        def _ordered_payload_jd(payload: dict[str, Any]) -> tuple[str, str]:
            keys = [
                ("jd", 0),
                ("about_job", 1),
                ("about_job_sections", 2),
                ("description", 3),
                ("jobDescription", 4),
                ("job_description", 5),
                ("descriptionText", 6),
                ("requirements", 7),
                ("details", 8),
                ("content", 9),
                ("summary", 10),
                ("skills", 11),
                ("technologies", 12),
                ("meta_description", 13),
                ("og_description", 14),
                ("twitter_description", 15),
                ("full_page_text", 99),
            ]
            candidates: list[tuple[int, int, str, str]] = []
            for key, priority in keys:
                value = _stringify_payload_candidate(payload.get(key, ""))
                if not value:
                    continue
                if key == "full_page_text":
                    lowered = value.lower()
                    stop_markers = [
                        "people also viewed",
                        "jobs you may be interested in",
                        "similar jobs",
                        "recommended for you",
                    ]
                    cut_positions = [lowered.find(marker) for marker in stop_markers if lowered.find(marker) >= 0]
                    if cut_positions:
                        value = value[: min(cut_positions)].strip()
                value = _clean_payload_text(value)
                if not value or _looks_like_fallback_jd(value):
                    continue
                candidates.append((priority, -len(value), str(key), value))
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                _, _, key, value = candidates[0]
                return value, key
            return "", ""

        def _title_tokens(title: str) -> set[str]:
            stop_tokens = {
                "senior",
                "junior",
                "lead",
                "principal",
                "software",
                "engineer",
                "developer",
                "remote",
                "fully",
                "part",
                "time",
            }
            normalized = re.sub(r"\([^)]*\)", " ", title or "")
            tokens = set(re.findall(r"[a-z0-9+#.-]{2,}", normalized.lower()))
            return {t for t in tokens if t not in stop_tokens}

        def _title_overlap(a: str, b: str) -> int:
            ta = _title_tokens(a)
            tb = _title_tokens(b)
            if not ta or not tb:
                return 0
            return len(ta.intersection(tb))

        def _find_peer_jd(job_post_id: int, title: str, company: str) -> tuple[str, str]:
            peers = conn.execute(
                """
                SELECT
                  jp.id,
                  COALESCE(jp.title, '') AS title,
                  COALESCE(jjc.jd_text, '') AS jd_text,
                  COALESCE(jjc.jd_source, '') AS jd_source
                FROM job_posts jp
                JOIN job_observations jo ON jo.job_post_id = jp.id
                JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
                WHERE jp.id <> ?
                  AND COALESCE(LOWER(TRIM(jp.company)), '') = COALESCE(LOWER(TRIM(?)), '')
                  AND COALESCE(TRIM(jjc.jd_text), '') <> ''
                  AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
                  AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
                  AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
                ORDER BY jo.crawl_date DESC, jo.id DESC
                LIMIT 200
                """,
                (job_post_id, company),
            ).fetchall()
            best_peer = None
            best_score = 0
            for peer in peers:
                score = _title_overlap(title, str(peer["title"] or ""))
                if score > best_score:
                    best_score = score
                    best_peer = peer
            if best_peer is not None and best_score > 0:
                return str(best_peer["jd_text"]), f"peer_company_overlap:{best_peer['jd_source']}"
            return "", ""

        rows = conn.execute(
            """
            SELECT
              jo.id AS observation_id,
              jo.job_post_id AS job_post_id,
              COALESCE(jp.title, '') AS title,
              COALESCE(jp.company, '') AS company,
              jo.row_json AS row_json,
              jp.latest_payload_json AS latest_payload_json,
              jo.observed_at AS observed_at,
              jjc.id AS jd_content_id,
              COALESCE(jjc.jd_text, '') AS current_jd_text,
              COALESCE(jjc.jd_source, '') AS current_jd_source
            FROM job_observations jo
            JOIN job_posts jp ON jp.id = jo.job_post_id
            LEFT JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
            WHERE jjc.id IS NULL
               OR LOWER(TRIM(COALESCE(jjc.jd_text, ''))) LIKE 'job context (fallback jd):%'
               OR LOWER(TRIM(COALESCE(jjc.jd_text, ''))) LIKE 'fallback jd:%'
               OR LOWER(COALESCE(jjc.jd_source, '')) LIKE '%full_page_text%'
            ORDER BY jo.id
            """
        ).fetchall()
        if not rows:
            return

        for row in rows:
            jd_text = ""
            jd_source = ""

            try:
                payload = json.loads(row["row_json"] or "{}")
                jd_text, jd_key = _ordered_payload_jd(payload if isinstance(payload, dict) else {})
                jd_source = str(payload.get("jd_source", "") or "").strip() if isinstance(payload, dict) else ""
                if jd_text and not jd_source:
                    jd_source = f"payload_fallback:{jd_key}"
            except Exception:
                pass

            if not jd_text:
                try:
                    payload_latest = json.loads(row["latest_payload_json"] or "{}")
                    jd_text, jd_key = _ordered_payload_jd(payload_latest if isinstance(payload_latest, dict) else {})
                    if not jd_source and isinstance(payload_latest, dict):
                        jd_source = str(payload_latest.get("jd_source", "") or "").strip()
                    if jd_text and not jd_source:
                        jd_source = f"payload_fallback:{jd_key}"
                except Exception:
                    pass

            if not jd_text:
                jd_text, jd_source = _find_peer_jd(
                    int(row["job_post_id"]),
                    str(row["title"] or ""),
                    str(row["company"] or ""),
                )

            if not jd_text:
                continue

            observed_at = str(row["observed_at"] or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
            current_jd_text = str(row["current_jd_text"] or "").strip()
            current_jd_source = str(row["current_jd_source"] or "").strip()
            if row["jd_content_id"] is not None and (
                _looks_like_fallback_jd(current_jd_text) or _source_uses_full_page_text(current_jd_source)
            ):
                conn.execute(
                    """
                    UPDATE job_jd_contents
                    SET jd_text = ?, jd_source = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (jd_text, jd_source, observed_at, int(row["jd_content_id"])),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO job_jd_contents (
                      observation_id, job_post_id, jd_text, jd_source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(row["observation_id"]),
                        int(row["job_post_id"]),
                        jd_text,
                        jd_source,
                        observed_at,
                        observed_at,
                    ),
                )

    @staticmethod
    def _backfill_job_post_normalizations(conn) -> None:
        work_model_keywords = {
            "remote": "remote",
            "hybrid": "hybrid",
            "on-site": "on_site",
            "onsite": "on_site",
            "in-office": "on_site",
            "office-based": "on_site",
        }
        employment_type_keywords = {
            "full-time": "full_time",
            "full time": "full_time",
            "part-time": "part_time",
            "part time": "part_time",
            "freelance": "contract",
            "freelancer": "contract",
            "contract": "contract",
            "internship": "internship",
            "temporary": "temporary",
            "volunteer": "volunteer",
        }

        def _collect_texts(raw: Any) -> list[str]:
            if raw in (None, ""):
                return []
            if isinstance(raw, str):
                return [raw]
            if isinstance(raw, list):
                out: list[str] = []
                for item in raw:
                    out.extend(_collect_texts(item))
                return out
            if isinstance(raw, dict):
                out: list[str] = []
                for nested_key, nested_value in raw.items():
                    out.append(str(nested_key or ""))
                    out.extend(_collect_texts(nested_value))
                return out
            return [str(raw)]

        def _normalize_flags(payload: dict[str, Any], current_jd_text: str, title: str) -> tuple[str, str, int]:
            values: list[str] = []
            raw_tags = payload.get("job_type_tags")
            if isinstance(raw_tags, list):
                values.extend(str(x or "").strip().lower() for x in raw_tags)
            for key in (
                "employment_type",
                "workplace_type",
                "work_type",
                "description",
                "about_job",
                "about_job_sections",
                "jd",
                "meta_description",
                "og_description",
                "twitter_description",
                "full_page_text",
            ):
                values.extend(text.strip().lower() for text in _collect_texts(payload.get(key)) if str(text).strip())
            if current_jd_text:
                values.append(current_jd_text.strip().lower())
            if title:
                values.append(title.strip().lower())
            sample = "\n".join(v for v in values if v)

            work_model = ""
            employment_type = ""
            for token, normalized in work_model_keywords.items():
                if token in sample:
                    work_model = normalized
                    break
            for token, normalized in employment_type_keywords.items():
                if token in sample:
                    employment_type = normalized
                    break

            easy_apply = 1 if "easy apply" in sample else 0
            apply_url = str(payload.get("apply_url", "") or "").strip().lower()
            if not easy_apply and ("linkedin.com" in apply_url or "onsiteapply" in apply_url or "easyapply" in apply_url):
                easy_apply = 1
            return work_model, employment_type, easy_apply

        rows = conn.execute(
            """
            SELECT
              jp.id,
              COALESCE(jp.title, '') AS title,
              COALESCE(jp.latest_payload_json, '') AS latest_payload_json,
              COALESCE(jp.normalized_work_model, '') AS normalized_work_model,
              COALESCE(jp.normalized_employment_type, '') AS normalized_employment_type,
              COALESCE(jp.normalized_easy_apply, 0) AS normalized_easy_apply,
              COALESCE((
                SELECT jjc.jd_text
                FROM job_jd_contents jjc
                JOIN job_observations jo ON jo.id = jjc.observation_id
                WHERE jo.job_post_id = jp.id
                ORDER BY jo.crawl_date DESC, jo.id DESC
                LIMIT 1
              ), '') AS current_jd_text
            FROM job_posts jp
            WHERE COALESCE(TRIM(jp.normalized_work_model), '') = ''
               OR COALESCE(TRIM(jp.normalized_employment_type), '') = ''
               OR COALESCE(jp.normalized_easy_apply, 0) = 0
            """
        ).fetchall()
        if not rows:
            return

        for row in rows:
            try:
                payload = json.loads(row["latest_payload_json"] or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            work_model, employment_type, easy_apply = _normalize_flags(
                payload,
                str(row["current_jd_text"] or ""),
                str(row["title"] or ""),
            )
            next_work_model = str(row["normalized_work_model"] or "").strip() or work_model
            next_employment_type = str(row["normalized_employment_type"] or "").strip() or employment_type
            next_easy_apply = int(row["normalized_easy_apply"] or 0) or easy_apply
            if (
                next_work_model != str(row["normalized_work_model"] or "").strip()
                or next_employment_type != str(row["normalized_employment_type"] or "").strip()
                or next_easy_apply != int(row["normalized_easy_apply"] or 0)
            ):
                conn.execute(
                    """
                    UPDATE job_posts
                    SET normalized_work_model = ?,
                        normalized_employment_type = ?,
                        normalized_easy_apply = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_work_model,
                        next_employment_type,
                        next_easy_apply,
                        datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        int(row["id"]),
                    ),
                )

    @staticmethod
    def _backfill_programming_languages(conn) -> None:
        def _looks_like_fallback_jd(text: str) -> bool:
            sample = str(text or "").strip().lower()
            if not sample:
                return True
            return sample.startswith("job context (fallback jd):") or sample.startswith("fallback jd:")

        conn.execute(
            """
            DELETE FROM job_programming_languages
            WHERE LOWER(TRIM(COALESCE(language, ''))) IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            """
        )
        rows = conn.execute(
            """
            SELECT
              jp.id AS job_post_id,
              COALESCE(jp.title, '') AS title,
              COALESCE(jjc.jd_text, '') AS jd_text,
              COALESCE(jp.latest_payload_json, '') AS latest_payload_json,
              COALESCE(jp.updated_at, jp.created_at, '') AS fallback_ts
            FROM job_posts jp
            LEFT JOIN (
              SELECT t.job_post_id, t.jd_text
              FROM job_jd_contents t
              JOIN (
                SELECT job_post_id, MAX(updated_at) AS max_updated_at
                FROM job_jd_contents
                GROUP BY job_post_id
              ) latest
                ON latest.job_post_id = t.job_post_id
               AND latest.max_updated_at = t.updated_at
            ) jjc ON jjc.job_post_id = jp.id
            WHERE NOT EXISTS (
              SELECT 1
              FROM job_programming_languages jpl
              WHERE jpl.job_post_id = jp.id
                AND LOWER(TRIM(COALESCE(jpl.language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            )
            ORDER BY jp.id
            """
        ).fetchall()
        if not rows:
            return

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for row in rows:
            job_post_id = int(row["job_post_id"])
            jd_text = str(row["jd_text"] or "").strip()
            title_text = str(row["title"] or "")
            payload_text = ""
            try:
                payload = json.loads(row["latest_payload_json"] or "{}")
                payload_jd = "\n".join(
                    [
                        str(payload.get("jd", "") or "").strip(),
                        str(payload.get("about_job", "") or "").strip(),
                        str(payload.get("description", "") or "").strip(),
                        str(payload.get("jobDescription", "") or "").strip(),
                        str(payload.get("job_description", "") or "").strip(),
                    ]
                ).strip()
                payload_text = "\n".join(
                    [
                        str(payload.get("descriptionText", "") or "").strip(),
                        str(payload.get("summary", "") or "").strip(),
                        str(payload.get("details", "") or "").strip(),
                        str(payload.get("content", "") or "").strip(),
                        str(payload.get("requirements", "") or "").strip(),
                        str(payload.get("skills", "") or "").strip(),
                        str(payload.get("technologies", "") or "").strip(),
                        str(payload.get("about_company", "") or "").strip(),
                    ]
                ).strip()
                if not payload_jd and not payload_text:
                    payload_text = str(payload.get("full_page_text", "") or "").strip()
            except Exception:
                payload_jd = ""
                payload_text = ""

            primary_jd = jd_text
            if _looks_like_fallback_jd(primary_jd) and payload_jd:
                primary_jd = payload_jd
            combined_text = primary_jd if len(primary_jd) >= 120 else "\n".join([primary_jd, payload_text]).strip()
            if not combined_text:
                combined_text = "\n".join([title_text, primary_jd, payload_text]).strip()
            extracted = extract_programming_languages(combined_text, allow_unknown=False)
            existing_rows = conn.execute(
                """
                SELECT language
                FROM job_programming_languages
                WHERE job_post_id = ?
                  AND LOWER(TRIM(COALESCE(language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
                """,
                (job_post_id,),
            ).fetchall()
            existing = sorted({str(x["language"]).strip() for x in existing_rows if str(x["language"]).strip()})
            languages = extracted or existing
            created_at = str(row["fallback_ts"] or now)
            languages = [x for x in languages if str(x).strip().lower() not in INVALID_LANGUAGE_VALUES]
            conn.execute("DELETE FROM job_programming_languages WHERE job_post_id = ?", (job_post_id,))
            for language in languages:
                conn.execute(
                    """
                    INSERT INTO job_programming_languages (
                      job_post_id, language, source, created_at, updated_at
                    ) VALUES (?, ?, 'jd_text', ?, ?)
                    ON CONFLICT(job_post_id, language)
                    DO UPDATE SET
                      updated_at = excluded.updated_at
                    """,
                    (job_post_id, language, created_at, now),
                )

    @staticmethod
    def _backfill_location_enrichment(conn) -> None:
        rows = conn.execute(
            """
            SELECT
              jp.id AS job_post_id,
              COALESCE(jp.location, '') AS raw_location
            FROM job_posts jp
            LEFT JOIN job_location_enrichment jle ON jle.job_post_id = jp.id
            WHERE jle.job_post_id IS NULL
            ORDER BY jp.id
            """
        ).fetchall()
        if not rows:
            return
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for row in rows:
            job_post_id = int(row["job_post_id"])
            raw_location = str(row["raw_location"] or "")
            normalized_country, region_hint, confidence = normalize_country(raw_location)
            if not normalized_country:
                continue
            normalized_region = infer_region(normalized_country)
            conn.execute(
                """
                INSERT INTO job_location_enrichment (
                  job_post_id, raw_location, normalized_country, normalized_region, region_hint, confidence, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_post_id)
                DO UPDATE SET
                  raw_location = excluded.raw_location,
                  normalized_country = excluded.normalized_country,
                  normalized_region = excluded.normalized_region,
                  region_hint = excluded.region_hint,
                  confidence = excluded.confidence,
                  updated_at = excluded.updated_at
                """,
                (job_post_id, raw_location, normalized_country, normalized_region, region_hint, confidence, now),
            )

    @staticmethod
    def _seed_region_country_map(conn) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for country, region in COUNTRY_TO_REGION.items():
            conn.execute(
                """
                INSERT INTO geo_region_country_map (
                  normalized_region, normalized_country, source, updated_at
                ) VALUES (?, ?, 'seed', ?)
                ON CONFLICT(normalized_region, normalized_country)
                DO UPDATE SET
                  updated_at = excluded.updated_at
                """,
                (region, country, now),
            )
        for region, countries in REGION_MEMBERSHIP_MAP.items():
            for country in countries:
                conn.execute(
                    """
                    INSERT INTO geo_region_country_map (
                      normalized_region, normalized_country, source, updated_at
                    ) VALUES (?, ?, 'seed_membership', ?)
                    ON CONFLICT(normalized_region, normalized_country)
                    DO UPDATE SET
                      updated_at = excluded.updated_at
                    """,
                    (region, country, now),
                )

    @staticmethod
    def _sync_region_country_map_from_jobs(conn) -> None:
        rows = conn.execute(
            """
            SELECT DISTINCT
              TRIM(COALESCE(normalized_region, '')) AS normalized_region,
              TRIM(COALESCE(normalized_country, '')) AS normalized_country
            FROM job_location_enrichment
            WHERE TRIM(COALESCE(normalized_region, '')) <> ''
              AND TRIM(COALESCE(normalized_country, '')) <> ''
            """
        ).fetchall()
        if not rows:
            return
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for row in rows:
            region = str(row["normalized_region"])
            country = str(row["normalized_country"])
            conn.execute(
                """
                INSERT INTO geo_region_country_map (
                  normalized_region, normalized_country, source, updated_at
                ) VALUES (?, ?, 'observed', ?)
                ON CONFLICT(normalized_region, normalized_country)
                DO UPDATE SET
                  updated_at = excluded.updated_at
                """,
                (region, country, now),
            )

    @staticmethod
    def upsert_job_text_embeddings(
        conn,
        *,
        job_post_id: int,
        content_type: str,
        source_key: str,
        content_text: str,
        updated_at: str,
    ) -> None:
        text = str(content_text or "").strip()
        conn.execute(
            "DELETE FROM job_text_embeddings WHERE job_post_id = ? AND content_type = ? AND source_key = ?",
            (job_post_id, content_type, source_key),
        )
        if not text:
            return
        chunks = split_text_chunks(text)
        for idx, chunk in enumerate(chunks):
            vector = build_hashed_embedding(chunk)
            token_count = len(re.findall(r"[a-z0-9+#./_-]{2,}", chunk.lower()))
            conn.execute(
                """
                INSERT INTO job_text_embeddings (
                    job_post_id, content_type, source_key, chunk_index, chunk_text, embedding_json,
                    token_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(job_post_id),
                    str(content_type or "").strip(),
                    str(source_key or "").strip(),
                    idx,
                    chunk,
                    json.dumps(vector, ensure_ascii=False),
                    token_count,
                    updated_at,
                    updated_at,
                ),
            )

    def backfill_job_jd_embeddings(self, *, limit: int | None = None) -> int:
        with self.db.connect() as conn:
            sql = """
                SELECT job_post_id, jd_text, COALESCE(jd_source, '') AS jd_source, COALESCE(updated_at, created_at, '') AS updated_at
                FROM job_jd_contents
                WHERE COALESCE(TRIM(jd_text), '') <> ''
                ORDER BY updated_at DESC, id DESC
            """
            params: tuple[Any, ...] = ()
            if isinstance(limit, int) and limit > 0:
                sql += " LIMIT ?"
                params = (limit,)
            rows = conn.execute(sql, params).fetchall()
            count = 0
            for row in rows:
                updated_at = str(row["updated_at"] or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
                self.upsert_job_text_embeddings(
                    conn,
                    job_post_id=int(row["job_post_id"]),
                    content_type="jd",
                    source_key=str(row["jd_source"] or "jd_text"),
                    content_text=str(row["jd_text"] or ""),
                    updated_at=updated_at,
                )
                count += 1
            return count

    def seed_default_schedule_if_empty(self) -> None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM automation_schedules").fetchone()
            if int(row["cnt"]) > 0:
                return
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            default_config = {
                "url": "https://www.linkedin.com/jobs/search/?keywords=Full%20Stack%20Engineer",
                "window_days": 30,
                "max_jobs": 200,
            }
            conn.execute(
                """
                INSERT INTO automation_schedules (
                    name, enabled, cron_expr, timezone, pipeline_type, crawl_config_json,
                    auto_eval_fit, fit_cv_profile, auto_generate_cv, fit_threshold, created_at, updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, 1, ?, 0, ?, ?, ?)
                """,
                (
                    "Default Filtered Jobs",
                    "0 */6 * * *",
                    "Asia/Ho_Chi_Minh",
                    "filtered_jobs",
                    json.dumps(default_config, ensure_ascii=False),
                    "full_doc_stlye",
                    75.0,
                    now,
                    now,
                ),
            )
