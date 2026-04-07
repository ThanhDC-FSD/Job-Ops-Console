from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any

from app.repositories.fit_repository import FitRepository
import logging


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "you",
    "your",
    "our",
    "are",
    "have",
    "has",
    "will",
    "into",
    "about",
    "they",
    "them",
    "their",
    "through",
    "using",
    "build",
    "help",
    "work",
    "role",
    "team",
    "strong",
    "experience",
    "product",
    "candidate",
    "candidates",
}

TECH_TERMS = {
    "react",
    "typescript",
    "javascript",
    "python",
    "fastapi",
    "django",
    "flask",
    "sql",
    "postgresql",
    "mysql",
    "oracle",
    "docker",
    "jenkins",
    "nginx",
    "llm",
    "llms",
    "langchain",
    "chroma",
    "mcp",
    "supabase",
    "chakra",
    "tanstackdb",
    "ux",
    "ui",
    "saas",
}

ACTION_VERBS = {
    "built",
    "developed",
    "designed",
    "implemented",
    "integrated",
    "automated",
    "delivered",
    "created",
    "contributed",
    "improved",
}

DOMAIN_TERMS = {
    "saas",
    "startup",
    "frontend",
    "full",
    "fullstack",
    "ux",
    "ai",
    "ownership",
    "scale",
    "product",
}

COUNTRY_ALIASES = {
    "usa": "United States",
    "gbr": "United Kingdom",
    "can": "Canada",
    "aut": "Austria",
    "bel": "Belgium",
    "fra": "France",
    "deu": "Germany",
    "lie": "Liechtenstein",
    "lux": "Luxembourg",
    "mco": "Monaco",
    "nld": "Netherlands",
    "che": "Switzerland",
    "bgr": "Bulgaria",
    "cze": "Czechia",
    "hun": "Hungary",
    "mda": "Moldova",
    "pol": "Poland",
    "rou": "Romania",
    "svk": "Slovakia",
    "vnm": "Vietnam",
    "viet nam": "Vietnam",
    "vietnam": "Vietnam",
    "puerto rico": "Puerto Rico",
    "argentina": "Argentina",
    "peru": "Peru",
    "colombia": "Colombia",
    "dominica": "Dominica",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "belize": "Belize",
    "costa rica": "Costa Rica",
    "dominican republic": "Dominican Republic",
    "el salvador": "El Salvador",
    "nicaragua": "Nicaragua",
    "panama": "Panama",
    "trinidad and tobago": "Trinidad and Tobago",
    "bolivia": "Bolivia",
    "chile": "Chile",
    "ecuador": "Ecuador",
    "paraguay": "Paraguay",
    "venezuela": "Venezuela",
    "uruguay": "Uruguay",
    "honduras": "Honduras",
    "guatemala": "Guatemala",
    "united states": "United States",
    "canada": "Canada",
}
COUNTRY_PATTERNS = [
    (canonical, re.compile(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", re.IGNORECASE))
    for alias, canonical in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
]
LOCATION_LIST_MARKERS = (
    "location requirements",
    "locations:",
    "location:",
    "countries:",
    "country:",
    "eligible locations",
    "we hire in",
    "hiring in",
    "must be located in",
    "can be located in",
    "residing in",
    "reside in",
)
ISO3_TOKEN_PATTERN = re.compile(r"\b[A-Z]{3}\b")


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", (text or "").lower())


def keyword_pool(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for token in tokens:
        if len(token) < 3:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        out.append(token)
    return out


def top_keywords(jd_text: str, limit: int = 40) -> list[str]:
    counts = Counter(keyword_pool(tokenize(jd_text)))
    return [w for w, _ in counts.most_common(limit)]


def keyword_coverage_score(jd_keywords: list[str], cv_tokens_set: set[str]) -> tuple[float, list[str], list[str]]:
    if not jd_keywords:
        return 100.0, [], []
    matched = [k for k in jd_keywords if k in cv_tokens_set]
    missing = [k for k in jd_keywords if k not in cv_tokens_set]
    return (len(matched) / len(jd_keywords)) * 100.0, matched, missing


def technical_fit_score(jd_tokens_set: set[str], cv_tokens_set: set[str]) -> float:
    jd_tech = sorted(jd_tokens_set.intersection(TECH_TERMS))
    if not jd_tech:
        return 70.0
    hit = [t for t in jd_tech if t in cv_tokens_set]
    return (len(hit) / len(jd_tech)) * 100.0


def domain_fit_score(jd_tokens_set: set[str], cv_tokens_set: set[str]) -> float:
    jd_domain = sorted(jd_tokens_set.intersection(DOMAIN_TERMS))
    if not jd_domain:
        return 70.0
    hit = [t for t in jd_domain if t in cv_tokens_set]
    return (len(hit) / len(jd_domain)) * 100.0


def evidence_quality_score(cv_text: str) -> float:
    bullets = [line.strip().lower() for line in (cv_text or "").splitlines() if line.strip().startswith("- ")]
    if not bullets:
        return 0.0
    rich = 0
    for bullet in bullets:
        has_verb = any(bullet.startswith(f"- {v}") for v in ACTION_VERBS)
        has_tech = any(term in bullet for term in TECH_TERMS)
        if has_verb and has_tech:
            rich += 1
    return (rich / len(bullets)) * 100.0


def _candidate_country() -> str:
    sample = str(os.getenv("LINKEDIN_LOCATION", "Hanoi, Vietnam") or "Hanoi, Vietnam").strip().lower()
    for canonical, pattern in COUNTRY_PATTERNS:
        if pattern.search(sample):
            return canonical
    return "Vietnam"


def _extract_explicit_location_countries(jd_text: str) -> list[str]:
    text = str(jd_text or "")
    if not text.strip():
        return []
    segments: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        lower_line = line.lower()
        if any(marker in lower_line for marker in LOCATION_LIST_MARKERS):
            segments.append(line.strip())
            for next_line in lines[index + 1 : index + 4]:
                cleaned = str(next_line or "").strip()
                if not cleaned:
                    break
                segments.append(cleaned)
    for match in re.finditer(
        r"(?is)(locations?|countries?|eligible locations|we hire in|hiring in|must be located in|can be located in)\s*[:\-]\s*([^\n\r]{0,500})",
        text,
    ):
        segments.append(match.group(2).strip())
    found: set[str] = set()
    for segment in segments:
        for canonical, pattern in COUNTRY_PATTERNS:
            if pattern.search(segment):
                found.add(canonical)
        iso_tokens = ISO3_TOKEN_PATTERN.findall(segment.upper())
        if len(iso_tokens) >= 2:
            for token in iso_tokens:
                canonical = COUNTRY_ALIASES.get(token.lower())
                if canonical:
                    found.add(canonical)
    return sorted(found)


def _location_constraint_check(jd_text: str) -> tuple[bool, str]:
    allowed_countries = _extract_explicit_location_countries(jd_text)
    if len(allowed_countries) >= 2:
        candidate_country = _candidate_country()
        if candidate_country not in allowed_countries:
            return (
                False,
                f"Location constraint failed: explicit hiring countries are {', '.join(allowed_countries[:24])}; candidate country {candidate_country} is not included.",
            )
        return True, f"Location constraint passed: candidate country {_candidate_country()} is included in explicit hiring countries."
    jd_lower = (jd_text or "").lower()
    candidate_country = _candidate_country().lower()
    if "only candidates residing in sweden" in jd_lower:
        return ("sweden" == candidate_country), (
            "Location constraint passed: JD requires Sweden residency and candidate country is Sweden."
            if "sweden" == candidate_country
            else "Location constraint failed: JD requires Sweden residency."
        )
    return True, "No strict location constraint detected by rule-based check."


def constraint_score(jd_text: str, cv_text: str) -> float:
    ok, _ = _location_constraint_check(jd_text)
    return 100.0 if ok else 0.0


def hard_constraint_check(jd_text: str, mode: str = "medium") -> tuple[bool, str]:
    jd_lower = (jd_text or "").lower()
    location_ok, location_note = _location_constraint_check(jd_text)
    if not location_ok:
        return False, location_note
    part_time_signals = [
        "part-time",
        "part time",
        "freelance",
        "contract",
        "hours/week",
        "hours per week",
        "hourly",
    ]
    remote_signals = [
        "remote",
        "work from home",
        "distributed",
        "asynchronous",
        "work independently and asynchronously",
    ]
    flexible_signals = [
        "hybrid",
        "flexible",
        "flexibility",
        "flexible schedule",
    ]
    hard_negative_signals = ["on-site", "onsite", "in-office", "office-based"]

    part_time_ok = any(s in jd_lower for s in part_time_signals)
    remote_ok = any(s in jd_lower for s in remote_signals)
    flexible_ok = remote_ok or any(s in jd_lower for s in flexible_signals)
    has_hard_negative = any(s in jd_lower for s in hard_negative_signals)
    mode_norm = (mode or "medium").strip().lower()
    if mode_norm not in {"hard", "medium", "soft"}:
        mode_norm = "medium"

    if mode_norm == "soft":
        if has_hard_negative and not flexible_ok:
            return False, "Soft constraint failed: JD indicates on-site/in-office requirement."
        return True, "Soft constraint passed."

    if mode_norm == "hard":
        if has_hard_negative and not remote_ok:
            return False, "Hard constraint failed: JD indicates on-site/in-office requirement."
        if part_time_ok and remote_ok:
            return True, "Hard constraint passed: JD indicates both part-time and remote."
        if not part_time_ok and not remote_ok:
            return False, "Hard constraint failed: JD lacks part-time and remote signals."
        if not part_time_ok:
            return False, "Hard constraint failed: JD lacks part-time/flexible signal."
        return False, "Hard constraint failed: JD lacks remote signal."

    if has_hard_negative and not flexible_ok:
        return False, "Medium constraint failed: JD indicates on-site/in-office requirement."
    if part_time_ok or flexible_ok:
        return True, "Medium constraint passed: JD indicates flexible or remote-friendly setup."
    return False, "Medium constraint failed: JD lacks flexible/remote signals."


def weighted_total(domain: float, technical: float, evidence: float, compliance: float) -> float:
    return (0.35 * domain) + (0.30 * technical) + (0.20 * evidence) + (0.15 * compliance)


def _primary_issue(*, mode_ok: bool, constraint_note: str, domain_score: float, tech_score: float, evidence_score: float, compliance_score: float) -> tuple[str, float, str]:
    if not mode_ok:
        return ("constraint", round(compliance_score, 2), constraint_note or "Constraint failed.")
    metrics = [
        ("domain", round(domain_score, 2), f"Lowest score is domain fit ({domain_score:.2f})."),
        ("tech", round(tech_score, 2), f"Lowest score is technical fit ({tech_score:.2f})."),
        ("evidence", round(evidence_score, 2), f"Lowest score is evidence quality ({evidence_score:.2f})."),
        ("compliance", round(compliance_score, 2), f"Lowest score is compliance ({compliance_score:.2f})."),
    ]
    metric, score, text = min(metrics, key=lambda item: item[1])
    return metric, score, text


def _build_detailed_fit_reason(
    *,
    mode: str,
    mode_ok: bool,
    total_score: float,
    domain_score: float,
    tech_score: float,
    evidence_score: float,
    constraint_score_value: float,
    matched_keywords: list[str],
    missing_keywords: list[str],
    constraint_note: str,
) -> str:
    strengths = ", ".join(matched_keywords[:8]) if matched_keywords else "none"
    gaps = ", ".join(missing_keywords[:8]) if missing_keywords else "none"
    verdict = "PASS" if mode_ok else "FAIL"
    return (
        f"Mode={mode.upper()} | Constraint={verdict}. "
        f"Total={total_score:.2f}. "
        f"Scores(domain={domain_score:.2f}, tech={tech_score:.2f}, evidence={evidence_score:.2f}, compliance={constraint_score_value:.2f}). "
        f"Strengths: {strengths}. "
        f"Gaps: {gaps}. "
        f"Constraint note: {constraint_note}"
    )


def _build_fit_jd_text(job: dict[str, Any], payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            str(job.get("jd_text", "") or "").strip(),
            str(payload.get("jd", "")).strip(),
            str(payload.get("about_job", "")).strip(),
            str(payload.get("description", "")).strip(),
            str(payload.get("jobDescription", "")).strip(),
            str(payload.get("job_description", "")).strip(),
            str(payload.get("details", "")).strip(),
            str(payload.get("requirements", "")).strip(),
            str(payload.get("skills", "")).strip(),
            str(payload.get("technologies", "")).strip(),
            str(payload.get("full_page_text", "")).strip(),
            str(job.get("title", "") or ""),
            str(job.get("company", "") or ""),
            str(job.get("location", "") or ""),
        ]
    ).strip()


class FitService:
    def __init__(self, repo: FitRepository) -> None:
        self.repo = repo
        self.logger = logging.getLogger("job_ops.fit")

    def evaluate_jobs(
        self,
        *,
        cv_path: Path,
        stage: str,
        limit: int = 0,
        constraint_mode: str = "medium",
        posted_within_days: int = 0,
        sort_by: str = "posted_date_desc",
        job_post_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        t_start = time.perf_counter()
        cv_text = cv_path.read_text(encoding="utf-8", errors="ignore")
        cv_clean = strip_tags(cv_text)
        cv_tokens_set = set(tokenize(cv_clean))
        jobs = self.repo.list_jobs_for_fit(
            stage=stage,
            limit=limit,
            posted_within_days=posted_within_days,
            sort_by=sort_by,
            job_post_ids=job_post_ids,
        )

        evaluated = 0
        timings: list[float] = []
        for job in jobs:
            payload = {}
            try:
                payload = json.loads(job.get("latest_payload_json") or "{}")
            except Exception:
                payload = {}

            jd_text = _build_fit_jd_text(job, payload)
            jd_clean = strip_tags(jd_text)
            jd_tokens_set = set(tokenize(jd_clean))
            if not jd_tokens_set:
                self.repo.upsert_fit_score(
                    {
                        "job_post_id": int(job["id"]),
                        "cv_profile": "full_doc_stlye",
                        "cv_source_path": str(cv_path.resolve()),
                        "total_score": 0.0,
                        "fit_hard": 0.0,
                        "fit_medium": 0.0,
                        "fit_soft": 0.0,
                        "domain_score": 0.0,
                        "tech_score": 0.0,
                        "evidence_score": 0.0,
                        "constraint_score": 0.0,
                        "status": "not_evaluated",
                        "fit_reason": "JD content missing or too short to evaluate.",
                        "fit_reason_hard": "Mode=HARD | Constraint=FAIL. JD content missing or too short to evaluate.",
                        "fit_reason_medium": "Mode=MEDIUM | Constraint=FAIL. JD content missing or too short to evaluate.",
                        "fit_reason_soft": "Mode=SOFT | Constraint=FAIL. JD content missing or too short to evaluate.",
                        "primary_issue_metric": "constraint",
                        "primary_issue_score": 0.0,
                        "primary_issue_text": "JD content missing or too short to evaluate.",
                        "main_issue": "Constraint — JD content missing or too short to evaluate.",
                        "matched_keywords_json": "[]",
                        "missing_keywords_json": "[]",
                        "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "evaluator_version": "fit-v2-evaluate_cv_fit",
                    }
                )
                evaluated += 1
                continue

            jd_keywords = top_keywords(jd_clean, limit=40)
            keyword_score, matched_keywords, missing_keywords = keyword_coverage_score(jd_keywords, cv_tokens_set)
            technical_score = technical_fit_score(jd_tokens_set, cv_tokens_set)
            domain_score = domain_fit_score(jd_tokens_set, cv_tokens_set)
            evidence_score = evidence_quality_score(cv_clean)
            compliance_score = constraint_score(jd_clean, cv_clean)
            domain_blended = (0.6 * domain_score) + (0.4 * keyword_score)
            base_total = round(weighted_total(domain_blended, technical_score, evidence_score, compliance_score), 2)

            mode_totals: dict[str, float] = {}
            mode_notes: dict[str, str] = {}
            mode_ok: dict[str, bool] = {}
            for mode_name in ("hard", "medium", "soft"):
                ok, note = hard_constraint_check(jd_clean, mode=mode_name)
                mode_ok[mode_name] = bool(ok)
                mode_notes[mode_name] = note or ""
                mode_totals[mode_name] = base_total if ok else 0.0

            selected_mode = (constraint_mode or "medium").strip().lower()
            if selected_mode not in {"hard", "medium", "soft"}:
                selected_mode = "medium"
            total_score = round(mode_totals[selected_mode], 2)
            status = (
                "ready_to_apply"
                if (mode_ok[selected_mode] and total_score >= 85)
                else "needs_improvement"
                if (mode_ok[selected_mode] and total_score >= 70)
                else "not_compatible"
            )
            if not mode_ok[selected_mode]:
                fit_reason = mode_notes[selected_mode]
            elif total_score >= 85:
                fit_reason = "Strong fit across domain, technical, and evidence dimensions."
            elif total_score >= 70:
                fit_reason = "Partial fit: some gaps remain in domain/keywords."
            else:
                fit_reason = "Low fit score against required domain/technical keywords."
            primary_issue_metric, primary_issue_score, primary_issue_text = _primary_issue(
                mode_ok=mode_ok[selected_mode],
                constraint_note=mode_notes[selected_mode],
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                compliance_score=round(compliance_score, 2),
            )
            primary_issue_label = {
                "constraint": "Constraint",
                "domain": "Domain",
                "tech": "Technical",
                "evidence": "Evidence",
                "compliance": "Compliance",
            }.get(primary_issue_metric, "Issue")
            main_issue = f"{primary_issue_label} — {primary_issue_text}"

            fit_reason_hard = _build_detailed_fit_reason(
                mode="hard",
                mode_ok=mode_ok["hard"],
                total_score=round(mode_totals["hard"], 2),
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                constraint_score_value=round(compliance_score, 2),
                matched_keywords=matched_keywords,
                missing_keywords=missing_keywords,
                constraint_note=mode_notes["hard"],
            )
            fit_reason_medium = _build_detailed_fit_reason(
                mode="medium",
                mode_ok=mode_ok["medium"],
                total_score=round(mode_totals["medium"], 2),
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                constraint_score_value=round(compliance_score, 2),
                matched_keywords=matched_keywords,
                missing_keywords=missing_keywords,
                constraint_note=mode_notes["medium"],
            )
            fit_reason_soft = _build_detailed_fit_reason(
                mode="soft",
                mode_ok=mode_ok["soft"],
                total_score=round(mode_totals["soft"], 2),
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                constraint_score_value=round(compliance_score, 2),
                matched_keywords=matched_keywords,
                missing_keywords=missing_keywords,
                constraint_note=mode_notes["soft"],
            )

            t_job_start = time.perf_counter()
            self.repo.upsert_fit_score(
                {
                    "job_post_id": int(job["id"]),
                    "cv_profile": "full_doc_stlye",
                    "cv_source_path": str(cv_path.resolve()),
                    "total_score": total_score,
                    "fit_hard": round(mode_totals["hard"], 2),
                    "fit_medium": round(mode_totals["medium"], 2),
                    "fit_soft": round(mode_totals["soft"], 2),
                    "domain_score": round(domain_blended, 2),
                    "tech_score": round(technical_score, 2),
                    "evidence_score": round(evidence_score, 2),
                    "constraint_score": round(compliance_score, 2),
                    "status": status,
                    "fit_reason": fit_reason,
                    "fit_reason_hard": fit_reason_hard,
                    "fit_reason_medium": fit_reason_medium,
                    "fit_reason_soft": fit_reason_soft,
                    "primary_issue_metric": primary_issue_metric,
                    "primary_issue_score": primary_issue_score,
                    "primary_issue_text": primary_issue_text,
                    "main_issue": main_issue,
                    "matched_keywords_json": json.dumps(matched_keywords[:120], ensure_ascii=False),
                    "missing_keywords_json": json.dumps(missing_keywords[:120], ensure_ascii=False),
                    "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "evaluator_version": "fit-v2-evaluate_cv_fit",
                }
            )
            evaluated += 1
            timings.append(time.perf_counter() - t_job_start)

        total_elapsed = time.perf_counter() - t_start
        avg = sum(timings) / len(timings) if timings else 0.0
        p95 = sorted(timings)[int(len(timings) * 0.95)] if timings else 0.0
        self.logger.info(
            "Fit evaluate_jobs done | stage=%s evaluated=%s total=%.3fs avg=%.3fs p95=%.3fs",
            stage,
            evaluated,
            total_elapsed,
            avg,
            p95,
        )
        return {
            "evaluated": evaluated,
            "stage": stage,
            "cv_path": str(cv_path.resolve()),
            "total_seconds": round(total_elapsed, 3),
            "avg_seconds": round(avg, 3),
            "p95_seconds": round(p95, 3),
        }
