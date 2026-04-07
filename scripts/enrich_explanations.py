from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.database import Database
from app.repositories.learning_repository import LearningRepository
from app.repositories.meta_repository import MetaRepository
from app.services.explanation_enrichment_service import ExplanationEnrichmentService

LOG_PATH = Path("apps/backend/app/logs/explanation_enrichment.log")


def ensure_log_path() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def configure_logger() -> logging.Logger:
    ensure_log_path()
    logger = logging.getLogger("enrich_explanations")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console_handler)
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich low-quality learning explanations.")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--chunk-limit", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def run_enrichment(args: argparse.Namespace, logger: logging.Logger) -> None:
    db = Database()
    meta_repo = MetaRepository(db)
    meta_repo.ensure_app_tables(run_maintenance=False)
    repo = LearningRepository(db)
    service = ExplanationEnrichmentService()

    limit = max(1, min(int(args.limit), 200))
    chunk_limit = max(1, min(int(args.chunk_limit), 5))
    rows = repo.list_questions_for_explanation_enrichment(limit=limit)
    if not rows:
        logger.info("No candidate rows found.")
        return

    reviewed = 0
    skipped_cached = 0
    updated = 0
    fallback_used = 0
    failed = 0
    review_needed = 0

    for row in rows:
        question_id = int(row["id"])
        question = str(row.get("question_en") or row.get("question_vi") or "").strip()
        answer = str(row.get("answer_en") or row.get("answer_vi") or "").strip()
        if not question or not answer:
            continue

        chunks = repo.list_chunks_by_question(question_id, limit=chunk_limit)
        context_text = "\n\n".join(str(chunk.get("chunk_text") or "").strip() for chunk in chunks if str(chunk.get("chunk_text") or "").strip())
        input_hash = service.build_input_hash(question=question, answer=answer, context_text=context_text)

        existing_assessment = service.assess_existing(
            answer=answer,
            explanation_en=str(row.get("explanation_en") or ""),
            explanation_vi=str(row.get("explanation_vi") or ""),
        )
        if (
            existing_assessment["is_valid"]
            and bool(int(row.get("explanation_publishable") or 0))
            and str(row.get("explanation_input_hash") or "") == input_hash
            and int(row.get("explanation_needs_review") or 0) == 0
        ):
            skipped_cached += 1
            continue

        reviewed += 1
        try:
            result = service.generate(
                question=question,
                answer=answer,
                context_text=context_text,
                topic_key=str(row.get("topic_key") or ""),
                question_style=str(row.get("difficulty") or "general"),
            )
            if args.dry_run:
                logger.info(
                    "Dry-run question=%s quality=%s overlap=%.3f fallback=%s",
                    question_id,
                    result.quality,
                    result.overlap_ratio,
                    result.used_fallback,
                )
                continue
            repo.update_question_explanation(
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
            updated += 1
            if result.used_fallback:
                fallback_used += 1
            if not result.publishable:
                review_needed += 1
        except Exception as exc:
            failed += 1
            logger.error("Failed to enrich question %s: %s", question_id, exc)

    logger.info(
        "Done reviewed=%s skipped_cached=%s updated=%s fallback_used=%s failed=%s review_needed=%s",
        reviewed,
        skipped_cached,
        updated,
        fallback_used,
        failed,
        review_needed,
    )


def main() -> None:
    args = parse_args()
    logger = configure_logger()
    run_enrichment(args, logger)


if __name__ == "__main__":
    main()
