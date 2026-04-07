from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

import requests

WORK_MODEL_VALUES = {"remote", "hybrid", "on_site", "unknown"}
EMPLOYMENT_TYPE_VALUES = {"full_time", "part_time", "contract", "internship", "temporary", "volunteer", "unknown"}
APPLICATION_STATUS_VALUES = {"open", "closed", "unknown"}
EXPLICIT_LANGUAGES = (
    "Python",
    "JavaScript",
    "TypeScript",
    "Go",
    "Java",
    "C#",
    "C++",
    "PHP",
    "Ruby",
    "Rust",
    "Kotlin",
    "Swift",
    "Scala",
    "Dart",
)


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _compact_text(value: str, max_chars: int = 2200) -> str:
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].strip()


def _candidate_texts(payload: dict[str, Any], jd_text: str) -> str:
    job_type_tags = payload.get("job_type_tags")
    job_type_text = ""
    if isinstance(job_type_tags, list):
        job_type_text = ", ".join(_clean_text(x) for x in job_type_tags if _clean_text(x))
    elif job_type_tags not in (None, ""):
        job_type_text = _clean_text(job_type_tags)

    parts = [
        payload.get("title"),
        payload.get("company"),
        payload.get("location"),
        job_type_text,
        payload.get("work_model"),
        payload.get("workplace_type"),
        payload.get("work_type"),
        payload.get("employment_type"),
        payload.get("posted_time"),
        payload.get("applicant_insight"),
        payload.get("response_note"),
        payload.get("meta_description"),
        payload.get("og_description"),
        payload.get("twitter_description"),
        payload.get("about_job"),
        payload.get("description"),
        payload.get("jd"),
        jd_text,
        payload.get("full_page_text"),
    ]
    about_sections = payload.get("about_job_sections")
    if isinstance(about_sections, dict):
        for key, value in about_sections.items():
            parts.append(key)
            if isinstance(value, list):
                parts.extend(value)
            else:
                parts.append(value)
    raw = "\n".join(_clean_text(x) for x in parts if _clean_text(x))
    return _compact_text(raw, max_chars=1800)


def _detect_posted_time(text: str) -> str:
    sample = _clean_text(text)
    if not sample:
        return ""
    match = re.search(r"\b\d+\+?\s+(?:minute|hour|day|week|month|year)s?\s+ago\b", sample, flags=re.IGNORECASE)
    if match:
        return match.group(0).strip()
    updated_match = re.search(
        r"\bUpdated:\s*((?:\d{1,2}\s+[A-Za-z]+\s+\d{4})|(?:[A-Za-z]+\s+\d{1,2},\s*\d{4}))",
        sample,
        flags=re.IGNORECASE,
    )
    if updated_match:
        return f"Updated: {updated_match.group(1).strip()}"
    return ""


def _detect_applicant_insight(text: str) -> str:
    sample = _clean_text(text)
    if not sample:
        return ""
    patterns = [
        r"\bOver\s+\d+\s+people\s+clicked\s+apply\b",
        r"\bOver\s+\d+\s+applicants\b",
        r"\b\d+\s+applicants\b",
        r"\bBe among the first\s+\d+\s+applicants\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, sample, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _detect_response_note(text: str) -> str:
    sample = _clean_text(text)
    if not sample:
        return ""
    patterns = [
        r"\bResponses managed off LinkedIn\b",
        r"\bNo response insights available yet\b",
        r"\bPromoted by hirer\b",
        r"\bSee who .*? has hired for this role\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, sample, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _detect_work_model(text: str) -> str:
    sample = str(text or "").lower()
    explicit = re.search(
        r"(?:workplace|workplace type|work model|work mode)\s*[:\n ]+\s*(on[- ]?site|hybrid|remote)",
        sample,
        flags=re.IGNORECASE,
    )
    if explicit:
        token = explicit.group(1).strip().lower()
        if token in {"on-site", "on site", "onsite"}:
            return "on_site"
        if token == "hybrid":
            return "hybrid"
        if token == "remote":
            return "remote"
    if any(token in sample for token in ("on-site", "onsite", "in-office", "office-based", "on site")):
        return "on_site"
    if "this position is based in" in sample and not any(
        token in sample for token in ("remote", "hybrid", "work from home", "wfh", "telecommute")
    ):
        return "on_site"
    if "hybrid" in sample:
        return "hybrid"
    if "remote" in sample:
        return "remote"
    return "unknown"


def _detect_employment_type(text: str) -> str:
    sample = str(text or "").lower()
    mapping = (
        ("full-time", "full_time"),
        ("full time", "full_time"),
        ("part-time", "part_time"),
        ("part time", "part_time"),
        ("freelance", "contract"),
        ("freelancer", "contract"),
        ("contract", "contract"),
        ("internship", "internship"),
        ("temporary", "temporary"),
        ("volunteer", "volunteer"),
    )
    for token, normalized in mapping:
        if token in sample:
            return normalized
    return "unknown"


def _detect_application_status(text: str) -> str:
    sample = str(text or "").lower()
    if any(token in sample for token in ("no longer accepting applications", "not accepting applications", "position filled", "applications closed")):
        return "closed"
    if "apply" in sample:
        return "open"
    return "unknown"


def _detect_compensation(text: str) -> str:
    sample = _clean_text(text)
    patterns = [
        r"(?:[$€£]\s?\d[\d,]*(?:\s?(?:-|–|to)\s?[$€£]?\s?\d[\d,]*)?(?:\s?/\s?(?:hr|hour|day|week|month|year))?)",
        r"(?:\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|gbp|ars)\s?(?:/\s?(?:hr|hour|day|week|month|year))?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, sample, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _normalize_programming_language(value: Any, source_text: str) -> str:
    text = _clean_text(value)
    if text:
        return text
    found: list[str] = []
    for language in EXPLICIT_LANGUAGES:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(language) + r"(?![A-Za-z0-9])"
        if re.search(pattern, source_text, flags=re.IGNORECASE):
            found.append(language)
    return ", ".join(found)


def _needs_llm_validation(source_text: str, current: dict[str, Any]) -> bool:
    sample = str(source_text or "").lower()
    if len(sample) < 120:
        return False
    if any(
        [
            current.get("compensation_text"),
            not current.get("posted_time"),
            (not current.get("applicant_insight") and "applicant" in sample),
            (not current.get("response_note") and ("response" in sample or "hired for this role" in sample)),
            "responses managed off linkedin" in sample,
            "no response insights" in sample,
            "no longer accepting applications" in sample,
            "not accepting applications" in sample,
        ]
    ):
        return True
    return False


def build_validation_source_hash(*, payload: dict[str, Any], jd_text: str) -> str:
    logic_version = os.getenv("DETAIL_VALIDATION_LOGIC_VERSION", "v2")
    source = logic_version + "\n" + json.dumps(payload or {}, ensure_ascii=False, sort_keys=True) + "\n" + str(jd_text or "")
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()


def _resolve_ollama_base_url() -> str:
    return (os.getenv("LLM_UPSTREAM_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


def _call_ollama_detail_validator(*, payload: dict[str, Any], jd_text: str, current: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_text = _candidate_texts(payload, jd_text)
    system_prompt = (
        "Validate extracted LinkedIn job details.\n"
        "Use only the provided text.\n"
        "Do not invent missing facts.\n"
        "If a field is not supported by the text, return an empty string or unknown.\n"
        "Normalize work_model to remote|hybrid|on_site|unknown.\n"
        "Normalize employment_type to full_time|part_time|contract|internship|temporary|volunteer|unknown.\n"
        "Normalize application_status to open|closed|unknown.\n"
        "Return JSON only."
    )
    user_prompt = (
        "CURRENT_EXTRACTED:\n"
        f"{json.dumps(current, ensure_ascii=False)}\n\n"
        "SOURCE_TEXT:\n"
        f"{source_text}"
    )
    schema = {
        "type": "object",
        "properties": {
            "posted_time": {"type": "string"},
            "applicant_insight": {"type": "string"},
            "compensation_text": {"type": "string"},
            "work_model": {"type": "string"},
            "employment_type": {"type": "string"},
            "easy_apply": {"type": "integer"},
            "application_status": {"type": "string"},
            "response_note": {"type": "string"},
            "programming_language": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["work_model", "employment_type", "application_status"],
    }
    model_name = os.getenv("DETAIL_VALIDATION_MODEL", "qwen2.5:0.5b-instruct")
    resp = requests.post(
        f"{_resolve_ollama_base_url()}/api/chat",
        headers={"Content-Type": "application/json"},
        json={
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": schema,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_ctx": 1024,
                "num_predict": 180,
                "top_k": 20,
                "top_p": 0.9,
                "repeat_penalty": 1.05,
                "num_thread": max(2, min(4, int(os.cpu_count() or 2))),
            },
            "keep_alive": "30m",
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    content = _clean_text(((data.get("message") or {}).get("content")) or "")
    if not content:
        raise ValueError("empty_detail_validation_output")
    parsed = json.loads(content)
    usage = {
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "total_duration": data.get("total_duration"),
        "eval_duration": data.get("eval_duration"),
        "llm_backend": "ollama_detail_validation",
        "llm_model": model_name,
    }
    return parsed, usage


def validate_job_details(*, payload: dict[str, Any], jd_text: str) -> dict[str, Any]:
    source_text = _candidate_texts(payload, jd_text)
    current = {
        "posted_time": _clean_text(payload.get("posted_time")) or _detect_posted_time(source_text),
        "applicant_insight": _clean_text(payload.get("applicant_insight")) or _detect_applicant_insight(source_text),
        "compensation_text": _detect_compensation(source_text),
        "work_model": _detect_work_model(source_text),
        "employment_type": _detect_employment_type(source_text),
        "easy_apply": 1 if "easy apply" in source_text.lower() else int("linkedin.com" in str(payload.get("apply_url") or "").lower()),
        "application_status": _detect_application_status(source_text),
        "response_note": _clean_text(payload.get("response_note")) or _detect_response_note(source_text),
        "programming_language": _normalize_programming_language(payload.get("programming_language"), source_text),
    }
    backend = "heuristic_detail_validation"
    usage: dict[str, Any] = {"fallback": True, "fallback_reason": ""}
    result = dict(current)
    llm_disabled = str(os.getenv("DETAIL_VALIDATION_DISABLE_LLM", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    if llm_disabled:
        usage["fallback_reason"] = "llm_disabled_by_env"
    elif _needs_llm_validation(source_text, current):
        try:
            llm_result, llm_usage = _call_ollama_detail_validator(payload=payload, jd_text=jd_text, current=current)
            usage = llm_usage
            backend = "ollama_detail_validation"
            result.update(
                {
                    key: value
                    for key, value in llm_result.items()
                    if key
                    in {
                        "posted_time",
                        "applicant_insight",
                        "compensation_text",
                        "work_model",
                        "employment_type",
                        "easy_apply",
                        "application_status",
                        "response_note",
                        "programming_language",
                    }
                }
            )
        except Exception as exc:
            usage["fallback_reason"] = str(exc)
    else:
        usage["fallback_reason"] = "heuristic_confident"
    result["work_model"] = result["work_model"] if result.get("work_model") in WORK_MODEL_VALUES else current["work_model"]
    result["employment_type"] = result["employment_type"] if result.get("employment_type") in EMPLOYMENT_TYPE_VALUES else current["employment_type"]
    result["application_status"] = (
        result["application_status"] if result.get("application_status") in APPLICATION_STATUS_VALUES else current["application_status"]
    )
    result["easy_apply"] = int(result.get("easy_apply") or 0)
    result["posted_time"] = _clean_text(result.get("posted_time")) or current["posted_time"]
    result["applicant_insight"] = _clean_text(result.get("applicant_insight")) or current["applicant_insight"]
    result["compensation_text"] = _clean_text(result.get("compensation_text")) or current["compensation_text"]
    result["response_note"] = _clean_text(result.get("response_note")) or current["response_note"]
    result["programming_language"] = _normalize_programming_language(result.get("programming_language"), source_text)
    result["validation_backend"] = backend
    result["validation_model"] = (
        os.getenv("DETAIL_VALIDATION_MODEL", "qwen2.5:0.5b-instruct") if backend == "ollama_detail_validation" else ""
    )
    result["validation_usage_json"] = json.dumps(usage, ensure_ascii=False)
    result["source_hash"] = build_validation_source_hash(payload=payload, jd_text=jd_text)
    return result
