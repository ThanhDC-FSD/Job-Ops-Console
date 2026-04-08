from __future__ import annotations

import json
from typing import Any


VALID_CONFIDENCE = {"high", "medium", "low"}


def parse_json_message(response_json: dict[str, Any]) -> dict[str, Any]:
    """Parse JSON content from local LLM responses with a safe empty fallback."""
    content = str((response_json.get("message") or {}).get("content") or "").strip()
    if not content:
        content = str((((response_json.get("choices") or [{}])[0].get("message") or {}).get("content")) or "").strip()
    try:
        parsed = json.loads(content or "{}")
    except Exception:
        parsed = {"qa": []}
    return parsed if isinstance(parsed, dict) else {"qa": []}


def _normalize_confidence(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in VALID_CONFIDENCE else "medium"


def validate_prediction_payload(payload: dict[str, Any], *, valid_evidence_ids: set[str]) -> dict[str, Any]:
    """Normalize and filter raw LLM output before persistence."""
    qa_items = payload.get("qa")
    if not isinstance(qa_items, list):
        return {"qa": []}
    normalized: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in qa_items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            continue
        dedup_key = question.casefold()
        if dedup_key in seen_questions:
            continue
        seen_questions.add(dedup_key)
        evidence_ids = item.get("evidence_ids")
        kept_ids: list[str] = []
        if isinstance(evidence_ids, list):
            for raw_id in evidence_ids:
                chunk_id = str(raw_id or "").strip()
                if chunk_id and chunk_id in valid_evidence_ids and chunk_id not in kept_ids:
                    kept_ids.append(chunk_id)
        normalized.append(
            {
                "question": question,
                "answer": answer,
                "evidence_ids": kept_ids,
                "confidence": _normalize_confidence(item.get("confidence")),
            }
        )
    return {"qa": normalized}
