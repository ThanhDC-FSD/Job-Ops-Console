from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.api_models import (
    LearningQuizRequestPayload,
    LearningQuizSubmitPayload,
)
from app.services.learning_service import LearningService


def build_learning_router(learning: LearningService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["learning"])

    @router.get("/learning/topics")
    def learning_topics() -> dict:
        learning.ensure_seed_if_empty()
        return {"items": learning.list_topics()}

    @router.get("/learning/quiz")
    def learning_quiz(
        topic_key: str = Query(..., min_length=1),
        limit: int = Query(5, ge=1, le=20),
        lang: str = Query("en"),
    ) -> dict:
        try:
            return learning.get_quiz(topic_key=topic_key, limit=limit, lang=lang)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/learning/quiz")
    def learning_quiz_post(payload: LearningQuizRequestPayload) -> dict:
        try:
            return learning.get_quiz(topic_key=payload.topic_key, limit=payload.limit, lang=payload.lang)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/learning/quiz/submit")
    def learning_quiz_submit(payload: LearningQuizSubmitPayload) -> dict:
        try:
            return learning.submit_quiz(
                topic_key=payload.topic_key,
                lang=payload.lang,
                items=[item.model_dump() for item in payload.items],
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/learning/quiz/history")
    def learning_quiz_history(limit: int = Query(20, ge=1, le=100)) -> dict:
        return {"items": learning.get_quiz_history(limit)}

    @router.get("/learning/knowledge")
    def learning_knowledge(
        topic_key: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=200),
        lang: str = Query("en"),
    ) -> dict:
        try:
            result = learning.get_topic_knowledge(topic_key=topic_key, limit=limit, lang=lang)
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
            for item in result.get("items", []):
                if item.get("explanation_en") or item.get("explanation_vi"):
                    continue
                item["explanation_en"] = fallback_en
                item["explanation_vi"] = fallback_vi
                item["explanation"] = fallback_vi if lang == "vi" else fallback_en
                item["explanation_source"] = item.get("explanation_source") or "fallback"
            return result
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/learning/seed")
    def learning_seed() -> dict:
        result = learning.ensure_seed_data()
        return result

    return router
