from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import httpx

from app.config import BACKEND_HOST, BACKEND_PORT, ENV_FILE

logger = logging.getLogger("job_ops.explanation")

EDUCATIONAL_SIGNALS = {
    "why",
    "because",
    "when",
    "however",
    "trade-off",
    "tradeoff",
    "profiling",
    "benchmark",
    "latency",
    "throughput",
    "pitfall",
    "gotcha",
}

EDUCATIONAL_DIMENSIONS = {
    "mechanism": {"mechanism", "why", "because", "internal", "loop", "state", "scheduling", "behavior"},
    "tradeoff": {"tradeoff", "trade-off", "cost", "limit", "avoid", "however", "but", "versus"},
    "profiling": {"profiling", "profile", "benchmark", "latency", "throughput", "measure", "verify"},
    "pitfall": {"pitfall", "danger", "risk", "gotcha", "warning", "limitation", "issue"},
}

DOMAIN_FALLBACKS = {
    "python_concurrency": {
        "en_why": "Why this is correct: asyncio leverages a single event loop, so spinning up more threads does not unlock I/O parallelism.",
        "en_when": "When to use / not use: choose asyncio for I/O-bound workloads, avoid it for CPU-heavy or blocking C extensions.",
        "en_tip": "Practical check: compare p95 latency after warm-up and verify context switch counts via tracing hooks.",
        "vi_why": "Vì sao đúng: asyncio dùng event loop đơn nên không mở rộng song song I/O bằng thread.",
        "vi_when": "Khi nào dùng/không dùng: dùng cho I/O-bound, tránh khi công việc nặng CPU hoặc dùng C blocking.",
        "vi_tip": "Kiểm tra: benchmark sau warm-up, quan sát latency p95 và đếm lần chuyển context.",
    },
    "sql_optimization": {
        "en_why": "Why this is correct: indexed scans avoid full-table work when predicates are selective.",
        "en_when": "When to use / not use: rely on indexes when selectivity is high; prefer sequential scans when predicates touch most rows.",
        "en_tip": "Practical check: run EXPLAIN ANALYZE and compare scan costs + actual rows.",
        "vi_why": "Vì sao đúng: chỉ số giúp tránh duyệt toàn bộ bảng khi điều kiện lọc chọn lọc.",
        "vi_when": "Khi nào dùng/không dùng: dùng khi selectivity cao, dùng sequential scan khi gần như mọi row thỏa mãn.",
        "vi_tip": "Kiểm tra: chạy EXPLAIN ANALYZE, so sánh chi phí scan và số hàng thực tế.",
    },
    "react": {
        "en_why": "Why this is correct: rendering cost depends on component tree and memoization.",
        "en_when": "When to use / not use: memoize pure components to avoid re-renders, but avoid over-memoization when props vary constantly.",
        "en_tip": "Practical check: profile with DevTools and inspect render durations + commit counts.",
        "vi_why": "Vì sao đúng: chi phí render phụ thuộc cây component và việc memo.",
        "vi_when": "Khi nào dùng/không dùng: memo cho component thuần, nhưng tránh khi props thay đổi liên tục.",
        "vi_tip": "Kiểm tra: dùng DevTools đo thời gian render và số lần commit.",
    },
}


@dataclass
class ExplanationResult:
    explanation_en: str
    explanation_vi: str
    quality: str
    overlap_ratio: float
    needs_review: bool
    generated_by: str
    prompt_version: str
    input_hash: str
    retry_count: int
    used_fallback: bool
    information_gain_score: float
    dimensions_present: list[str]
    missing_angles: list[str]
    publishable: bool
    rejected_reason: str
    generation_stage: str


class ExplanationEnrichmentService:
    PROMPT_VERSION = "v3.answer-aware"

    def __init__(self) -> None:
        self.base_url = self._resolve_base_url()
        self.api_key = self._resolve_env_value("OPENAI_API_KEY")
        self.model = self._resolve_env_value("EXPLANATION_OPENAI_MODEL") or "qwen2.5:1.5b-instruct"
        self.internal_llm_token = self._resolve_env_value("INTERNAL_LLM_SHARED_TOKEN")
        self.timeout_seconds = float(self._resolve_env_value("EXPLANATION_TIMEOUT_SECONDS") or "20")
        self.min_len_en = int(self._resolve_env_value("EXPLANATION_MIN_LEN_EN") or "180")
        self.min_len_vi = int(self._resolve_env_value("EXPLANATION_MIN_LEN_VI") or "120")
        self.max_overlap = float(self._resolve_env_value("EXPLANATION_MAX_OVERLAP") or "0.78")
        self.max_retries = 1
        self.min_information_gain = float(self._resolve_env_value("EXPLANATION_MIN_INFO_GAIN") or "0.7")

    @staticmethod
    def _read_env_file_value(name: str) -> str:
        if not ENV_FILE.exists():
            return ""
        try:
            for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip("'").strip('"')
        except Exception as exc:
            logger.warning("Failed reading .env for %s: %s", name, exc)
        return ""

    @classmethod
    def _resolve_env_value(cls, name: str) -> str:
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
        return cls._read_env_file_value(name)

    @staticmethod
    def _is_local_url(url: str) -> bool:
        lowered = (url or "").lower()
        return "127.0.0.1" in lowered or "localhost" in lowered or "0.0.0.0" in lowered

    def _resolve_base_url(self) -> str:
        # Force local_llm_controller by default to avoid external calls.
        preferred = self._resolve_env_value("LOCAL_LLM_BASE_URL")
        if preferred and self._is_local_url(preferred):
            return preferred.rstrip("/")
        # Default to backend local_llm_controller.
        return f"http://{BACKEND_HOST}:{BACKEND_PORT}/v1"

    @staticmethod
    def _normalize_tokens(text: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9_+\-]+", str(text or "").lower()) if len(t) > 1}

    def overlap_ratio(self, answer: str, explanation: str) -> float:
        answer_tokens = self._normalize_tokens(answer)
        if not answer_tokens:
            return 0.0
        explanation_tokens = self._normalize_tokens(explanation)
        if not explanation_tokens:
            return 1.0
        overlap = answer_tokens.intersection(explanation_tokens)
        return len(overlap) / max(1, len(answer_tokens))

    def plan_answer(self, answer: str) -> dict[str, Any]:
        tokens = self._normalize_tokens(answer)
        answer_concepts = sorted(list(tokens))[:12]
        missing_angles = []
        for dimension, keywords in EDUCATIONAL_DIMENSIONS.items():
            if not any(keyword in answer.lower() for keyword in keywords):
                missing_angles.append(dimension)
        return {"answer_concepts": answer_concepts, "missing_angles": missing_angles}

    def _dimensions_present(self, text: str) -> list[str]:
        lowered = str(text or "").lower()
        present: list[str] = []
        for dimension, keywords in EDUCATIONAL_DIMENSIONS.items():
            if any(keyword in lowered for keyword in keywords):
                present.append(dimension)
        return present

    def information_gain_score(self, *, answer: str, explanation: str, dimensions_present: list[str]) -> float:
        answer_tokens = self._normalize_tokens(answer)
        explanation_tokens = self._normalize_tokens(explanation)
        new_tokens = explanation_tokens - answer_tokens
        base_score = len(new_tokens) / max(1, len(answer_tokens))
        dimension_bonus = min(1.0, len(dimensions_present) / max(1, len(EDUCATIONAL_DIMENSIONS)))
        return min(5.0, base_score + dimension_bonus)

    @staticmethod
    def _join_non_empty(parts: list[str]) -> str:
        return "\n\n".join(part.strip() for part in parts if str(part or "").strip())

    def build_prompt(
        self,
        *,
        question: str,
        answer: str,
        context_text: str,
        plan: dict[str, Any],
        strict: bool,
    ) -> list[dict[str, str]]:
        answer_summary = ", ".join(plan.get("answer_concepts", [])[:6]) or "core facts"
        missing_angles = plan.get("missing_angles") or []
        missing_hint = (
            f"Missing angles: {', '.join(missing_angles)}. Include at least two of these."
            if missing_angles
            else "Answer already touches all angles; still add deeper mechanism/trade-off detail."
        )
        strict_block = ""
        if strict:
            strict_block = (
                "\n\nSTRICT MODE:\n"
                "- Avoid repeating answer phrasing.\n"
                "- Focus on the missing angles and new supporting ideas.\n"
                "- Clarify why or why not; mention profiling or debugging verification."
            )
        return [
            {
                "role": "system",
                "content": (
                    "You are a senior technical instructor. The answer already covers some facts; add learning value."
                    " Do NOT rephrase the answer or add redundant sentences.\n"
                    "Output EXACTLY six lines with these keys:\n"
                    "EN_WHY:\nEN_WHEN:\nEN_PROFILE:\nVI_WHY:\nVI_WHEN:\nVI_PROFILE:"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Answer: {answer}\n"
                    f"Answer covers: {answer_summary}\n"
                    f"{missing_hint}\n"
                    f"Context: {context_text or 'No additional context.'}\n\n"
                    "Required value:\n"
                    "- WHY this answer works (mechanism)\n"
                    "- WHEN to use and when to avoid (trade-offs)\n"
                    "- PRACTICAL verification or profiling steps\n"
                    f"{strict_block}"
                ),
            },
        ]

    @staticmethod
    def parse_sections(raw_text: str) -> dict[str, str]:
        values = {
            "EN_WHY": "",
            "EN_WHEN": "",
            "EN_PROFILE": "",
            "VI_WHY": "",
            "VI_WHEN": "",
            "VI_PROFILE": "",
        }
        current_key = ""
        for line in str(raw_text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if ":" in stripped:
                prefix = stripped.split(":", 1)[0].strip().upper()
                if prefix in values:
                    current_key = prefix
                    values[prefix] = stripped.split(":", 1)[1].strip()
                    continue
            if current_key:
                values[current_key] = (values[current_key] + " " + stripped).strip()
        return values

    def _call_openai_compatible(self, messages: list[dict[str, str]]) -> str:
        endpoint = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.internal_llm_token:
            headers["Authorization"] = f"Bearer {self.internal_llm_token}"
            headers["X-Internal-LLM-Token"] = self.internal_llm_token
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 420,
        }
        with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds, read=self.timeout_seconds)) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"] or "").strip()

    def build_domain_fallback(self, *, topic_key: str | None, question_style: str | None) -> tuple[str, str]:
        key = (topic_key or "").strip()
        template = DOMAIN_FALLBACKS.get(key, DOMAIN_FALLBACKS.get("python_concurrency"))
        en_parts = [template["en_why"], template["en_when"], template["en_tip"]]
        vi_parts = [template["vi_why"], template["vi_when"], template["vi_tip"]]
        return self._join_non_empty(en_parts), self._join_non_empty(vi_parts)

    def _rule_based_validation(
        self,
        *,
        answer: str,
        explanation_en: str,
        explanation_vi: str,
        dimensions_present: list[str],
        missing_angles: list[str],
        info_gain_score: float,
    ) -> tuple[bool, float, str]:
        overlap = self.overlap_ratio(answer, explanation_en)
        non_empty = bool(explanation_en.strip())
        not_identical = explanation_en.strip().lower() != str(answer or "").strip().lower()
        long_enough = len(explanation_en.strip()) >= self.min_len_en
        vi_ok = (not explanation_vi.strip()) or len(explanation_vi.strip()) >= self.min_len_vi
        dims_count = len(dimensions_present)
        has_new_angle = bool(set(dimensions_present).intersection(set(missing_angles)))
        publishable = (
            non_empty
            and not_identical
            and overlap <= self.max_overlap
            and long_enough
            and vi_ok
            and info_gain_score >= self.min_information_gain
            and dims_count >= 2
            and (has_new_angle or not missing_angles)
        )
        reason = ""
        if not non_empty:
            reason = "empty explanation"
        elif not not_identical:
            reason = "mirrors answer"
        elif overlap > self.max_overlap:
            reason = "too much overlap"
        elif info_gain_score < self.min_information_gain:
            reason = "low information gain"
        elif dims_count < 2:
            reason = "not enough dimensions"
        elif missing_angles and not has_new_angle:
            reason = "no novel dimension"
        elif not long_enough:
            reason = "too short"
        elif not vi_ok:
            reason = "vi translation too short"
        return publishable, overlap, reason

    def assess_existing(
        self,
        *,
        answer: str,
        explanation_en: str,
        explanation_vi: str,
    ) -> dict[str, Any]:
        plan = self.plan_answer(answer)
        dimensions_present = self._dimensions_present(explanation_en)
        info_gain_score = self.information_gain_score(
            answer=answer,
            explanation=explanation_en,
            dimensions_present=dimensions_present,
        )
        publishable, overlap, reason = self._rule_based_validation(
            answer=answer,
            explanation_en=explanation_en,
            explanation_vi=explanation_vi,
            dimensions_present=dimensions_present,
            missing_angles=plan.get("missing_angles") or [],
            info_gain_score=info_gain_score,
        )
        quality = "high" if publishable else "low"
        return {
            "is_valid": publishable,
            "quality": quality,
            "overlap_ratio": overlap,
            "needs_review": not publishable,
            "information_gain_score": info_gain_score,
        }

    def build_input_hash(self, *, question: str, answer: str, context_text: str) -> str:
        raw = "||".join([question.strip().lower(), answer.strip().lower(), context_text.strip().lower(), self.PROMPT_VERSION])
        return sha256(raw.encode("utf-8")).hexdigest()

    def generate(
        self,
        *,
        question: str,
        answer: str,
        context_text: str,
        topic_key: str | None = None,
        question_style: str | None = None,
    ) -> ExplanationResult:
        input_hash = self.build_input_hash(question=question, answer=answer, context_text=context_text)
        plan = self.plan_answer(answer)
        dimensions_present: list[str] = []
        missing_angles = plan.get("missing_angles") or []
        info_gain_score = 0.0
        explanation_en = ""
        explanation_vi = ""
        stage = "slm"
        retry_count = 0
        used_fallback = False

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            stage = "retry" if attempt > 0 else "slm"
            try:
                messages = self.build_prompt(
                    question=question,
                    answer=answer,
                    context_text=context_text,
                    plan=plan,
                    strict=attempt > 0,
                )
                raw = self._call_openai_compatible(messages)
                parts = self.parse_sections(raw)
                explanation_en = self._join_non_empty([parts["EN_WHY"], parts["EN_WHEN"], parts["EN_PROFILE"]])
                explanation_vi = self._join_non_empty([parts["VI_WHY"], parts["VI_WHEN"], parts["VI_PROFILE"]])
            except Exception:
                explanation_en = ""
                explanation_vi = ""
            dimensions_present = self._dimensions_present(explanation_en)
            info_gain_score = self.information_gain_score(
                answer=answer, explanation=explanation_en, dimensions_present=dimensions_present
            )
            publishable, overlap, reason = self._rule_based_validation(
                answer=answer,
                explanation_en=explanation_en,
                explanation_vi=explanation_vi,
                dimensions_present=dimensions_present,
                missing_angles=missing_angles,
                info_gain_score=info_gain_score,
            )
            if publishable:
                return ExplanationResult(
                    explanation_en=explanation_en,
                    explanation_vi=explanation_vi,
                    quality="high",
                    overlap_ratio=overlap,
                    needs_review=False,
                    generated_by=f"llm:{self.model}",
                    prompt_version=self.PROMPT_VERSION,
                    input_hash=input_hash,
                    retry_count=retry_count,
                    used_fallback=False,
                    information_gain_score=info_gain_score,
                    dimensions_present=dimensions_present,
                    missing_angles=missing_angles,
                    publishable=True,
                    rejected_reason="",
                    generation_stage=stage,
                )

        used_fallback = True
        stage = "fallback"
        fallback_en, fallback_vi = self.build_domain_fallback(topic_key=topic_key, question_style=question_style)
        dimensions_present = self._dimensions_present(fallback_en)
        info_gain_score = self.information_gain_score(
            answer=answer, explanation=fallback_en, dimensions_present=dimensions_present
        )
        publishable, overlap, reason = self._rule_based_validation(
            answer=answer,
            explanation_en=fallback_en,
            explanation_vi=fallback_vi,
            dimensions_present=dimensions_present,
            missing_angles=missing_angles,
            info_gain_score=info_gain_score,
        )
        quality = "medium" if overlap <= self.max_overlap else "low"
        return ExplanationResult(
            explanation_en=fallback_en,
            explanation_vi=fallback_vi,
            quality=quality,
            overlap_ratio=overlap,
            needs_review=not publishable,
            generated_by="deterministic_fallback",
            prompt_version=self.PROMPT_VERSION,
            input_hash=input_hash,
            retry_count=retry_count,
            used_fallback=used_fallback,
            information_gain_score=info_gain_score,
            dimensions_present=dimensions_present,
            missing_angles=missing_angles,
            publishable=publishable,
            rejected_reason=reason,
            generation_stage=stage,
        )
