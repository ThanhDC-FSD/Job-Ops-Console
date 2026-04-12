from __future__ import annotations

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import requests
from bs4 import BeautifulSoup

from app.config import TUNING_ANALYTICS_AI_CACHE_TTL_SECONDS, TUNING_ANALYTICS_AI_MODEL, TUNING_ANALYTICS_AI_TIMEOUT_SECONDS
from app.repositories.analytics_repository import AnalyticsRepository

MARKET_CONTEXT_TTL_SECONDS = 60 * 60 * 6
REQUEST_TIMEOUT_SECONDS = 8
USER_AGENT = "JobOpsAnalytics/1.0 (+https://127.0.0.1)"
TREND_AI_DIMENSIONS = [
    "economic",
    "labor_market",
    "social_cultural",
    "policy_regulatory",
    "geopolitical_conflict",
    "industry_cycle",
    "technology_stack",
    "regional_distribution",
]


class AnalyticsService:
    _market_context_cache: dict[str, Any] = {"expires_at": 0.0, "sources": []}
    _market_context_lock = threading.Lock()
    _market_context_refreshing = False
    _trend_ai_cache: dict[str, dict[str, Any]] = {}
    _trend_ai_lock = threading.Lock()
    _trend_ai_refreshing: set[str] = set()

    _CURATED_SOURCE_SPECS = [
        {
            "id": "github_octoverse_2025",
            "publisher": "GitHub",
            "title": "Octoverse 2025",
            "url": "https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/",
            "patterns": [
                ("TypeScript", r"TypeScript overtook both Python and JavaScript in August 2025 to become the most used language on GitHub"),
                ("Python", r"Python remains dominant for AI and data science workloads"),
                ("JavaScript", r"JavaScript/TypeScript ecosystem still accounts for more overall activity than Python alone"),
                ("APAC", r"India alone added more than 5 million developers this year"),
            ],
        },
        {
            "id": "stackoverflow_technology_2025",
            "publisher": "Stack Overflow",
            "title": "Developer Survey 2025 Technology",
            "url": "https://survey.stackoverflow.co/2025/technology",
            "patterns": [
                ("Python", r"Python's adoption has accelerated significantly\. It saw a 7 percentage point increase from 2024 to 2025; this speaks to its ability to be the go-to language for AI, data science, and back-end development"),
            ],
        },
        {
            "id": "jetbrains_devecosystem_2024",
            "publisher": "JetBrains",
            "title": "Developer Ecosystem 2024",
            "url": "https://www.jetbrains.com/lp/devecosystem-2024/",
            "patterns": [
                ("TypeScript", r"TypeScript is rapidly gaining traction\. Its adoption has surged from 12% in 2017 up to an impressive 35% in 2024"),
                ("Python", r"The most commonly used programming language for AI and ML is Python"),
                ("Go", r"Go and Rust: most adopted languages The languages most respondents plan to adopt are clearly Go and Rust\. Both languages are built with performance and concurrency in mind"),
                ("Rust", r"Go and Rust: most adopted languages The languages most respondents plan to adopt are clearly Go and Rust\. Both languages are built with performance and concurrency in mind"),
            ],
        },
    ]

    def __init__(self, repo: AnalyticsRepository) -> None:
        self.repo = repo
        self.logger = logging.getLogger("job_ops.analytics")

    def reposts(
        self,
        *,
        country: str,
        countries: list[str],
        company: str,
        min_reposts: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self.repo.company_repost_stats(
            country=country,
            countries=countries,
            company=company,
            min_reposts=min_reposts,
            limit=limit,
        )

    def countries_overview(self) -> list[dict[str, Any]]:
        return self.repo.country_overview()

    def programming_language_hiring_trends(
        self,
        *,
        days: int = 90,
        top_n: int = 6,
        countries: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.repo.programming_language_hiring_trends(days=days, top_n=top_n, countries=countries or [])

    def programming_stack_hiring_trends(
        self,
        *,
        days: int = 90,
        top_n: int = 6,
        countries: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.repo.programming_stack_hiring_trends(days=days, top_n=top_n, countries=countries or [])

    @staticmethod
    def _compact_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", " ".join(soup.stripped_strings)).strip()

    @classmethod
    def _extract_curated_facts(cls, text: str, spec: dict[str, Any]) -> list[dict[str, str]]:
        facts: list[dict[str, str]] = []
        for topic, pattern in spec.get("patterns", []):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            snippet = re.sub(r"\s+", " ", match.group(0)).strip()
            facts.append({"topic": str(topic), "text": snippet})
        return facts

    def _fetch_market_source(self, spec: dict[str, Any]) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        try:
            response = requests.get(
                str(spec["url"]),
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            compact_text = self._compact_text(response.text)
            facts = self._extract_curated_facts(compact_text, spec)
            status = "ok"
            error = ""
        except Exception as exc:
            compact_text = ""
            facts = []
            status = "error"
            error = str(exc)
            self.logger.warning("Analytics market source fetch failed | source=%s error=%s", spec.get("id"), exc)
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        return {
            "id": str(spec["id"]),
            "publisher": str(spec["publisher"]),
            "title": str(spec["title"]),
            "url": str(spec["url"]),
            "status": status,
            "facts": facts,
            "error": error,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "duration_ms": duration_ms,
        }

    def _fetch_market_sources_uncached(self) -> list[dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=min(3, len(self._CURATED_SOURCE_SPECS))) as pool:
            return list(pool.map(self._fetch_market_source, self._CURATED_SOURCE_SPECS))

    def _refresh_market_sources_background(self) -> None:
        try:
            sources = self._fetch_market_sources_uncached()
            if sources:
                with self._market_context_lock:
                    self._market_context_cache = {
                        "expires_at": datetime.now(timezone.utc).timestamp() + MARKET_CONTEXT_TTL_SECONDS,
                        "sources": sources,
                    }
        except Exception as exc:
            self.logger.warning("Analytics market source refresh failed | error=%s", exc)
        finally:
            with self._market_context_lock:
                self._market_context_refreshing = False

    def _start_market_sources_refresh(self) -> None:
        with self._market_context_lock:
            if self._market_context_refreshing:
                return
            self._market_context_refreshing = True
        threading.Thread(target=self._refresh_market_sources_background, name="analytics-market-refresh", daemon=True).start()

    def _load_market_sources(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        now_ts = datetime.now(timezone.utc).timestamp()
        should_refresh_background = False
        with self._market_context_lock:
            cached_sources = list(self._market_context_cache.get("sources") or [])
            expires_at = float(self._market_context_cache.get("expires_at") or 0.0)
            if cached_sources and not force_refresh:
                if expires_at > now_ts:
                    return cached_sources
                if not self._market_context_refreshing:
                    should_refresh_background = True

        if should_refresh_background:
            self._start_market_sources_refresh()
            return cached_sources

        sources = self._fetch_market_sources_uncached()
        with self._market_context_lock:
            self._market_context_cache = {
                "expires_at": datetime.now(timezone.utc).timestamp() + MARKET_CONTEXT_TTL_SECONDS,
                "sources": sources,
            }
        return sources

    @staticmethod
    def _collect_external_language_facts(sources: list[dict[str, Any]]) -> dict[str, list[str]]:
        facts_by_topic: dict[str, list[str]] = {}
        for source in sources:
            for fact in source.get("facts", []):
                topic = str(fact.get("topic") or "").strip()
                text = str(fact.get("text") or "").strip()
                if not topic or not text:
                    continue
                facts_by_topic.setdefault(topic, []).append(text)
        return facts_by_topic

    @staticmethod
    def _language_specific_reason(language: str) -> str:
        normalized = str(language or "").strip().lower()
        if normalized in {"typescript", "javascript"}:
            return "Local demand is usually strongest where product teams and customer-facing web platforms are shipping quickly, so typed frontend and full-stack stacks cluster in those regions."
        if normalized == "python":
            return "Local demand usually follows AI, data, automation, and backend-heavy teams, so Python clusters around regions with more platform, analytics, and startup hiring."
        if normalized in {"go", "rust"}:
            return "Local demand usually appears where infrastructure, streaming, or distributed-system teams are hiring, so these languages tend to cluster around platform-heavy regions."
        if normalized in {"java", "c#"}:
            return "Local demand usually comes from enterprise, fintech, and long-lived backend systems, which often creates a steadier regional footprint instead of a sudden spike."
        return "Local concentration is mainly explained by where this stack appears in the current job mix rather than by a single global trend."

    @staticmethod
    def _stack_group_reason(group: str) -> str:
        normalized = str(group or "").strip().lower()
        if "full stack" in normalized:
            return "These roles cluster where teams need one engineer to move across UI, API, and delivery work with fewer hand-offs."
        if "frontend" in normalized:
            return "These roles cluster around product teams shipping UI-heavy work and iterating quickly on user experience."
        if "backend" in normalized:
            return "These roles cluster around API, services, and platform work where reliability and scale matter."
        if "ai" in normalized:
            return "These roles cluster where teams are productizing LLM, automation, or model-adjacent work."
        if "data" in normalized:
            return "These roles cluster around analytics, pipelines, and warehouse-heavy teams."
        if "devops" in normalized:
            return "These roles cluster around infrastructure, deployment, and reliability work."
        if "mobile" in normalized:
            return "These roles cluster around iOS and Android delivery."
        return "Local concentration is mainly explained by where this stack appears in the current job mix rather than by a single global trend."

    @classmethod
    def _build_language_market_item(
        cls,
        *,
        language_row: dict[str, Any],
        region_breakdown: dict[str, list[dict[str, Any]]],
        external_facts: dict[str, list[str]],
    ) -> dict[str, Any]:
        language = str(language_row.get("language") or "").strip()
        regions = list(region_breakdown.get(language) or [])
        top_region = regions[0] if regions else {"region": "Other", "share_pct": 0.0, "countries": []}
        top_country_names = [str(item.get("country") or "").strip() for item in top_region.get("countries", []) if str(item.get("country") or "").strip()]
        trend_direction = str(language_row.get("trend_direction") or "flat")
        momentum_pct = float(language_row.get("momentum_pct") or 0.0)
        headline = (
            f"{language} is accelerating locally"
            if trend_direction == "up"
            else (f"{language} is cooling slightly" if trend_direction == "down" else f"{language} is holding steady locally")
        )
        local_reasons = [
            f"{language} appears in {int(language_row.get('jobs') or 0)} recent job mentions across the last {int(language_row.get('active_days') or 0)} active days.",
            f"The dominant region is {top_region.get('region') or 'Other'} at {float(top_region.get('share_pct') or 0.0):.1f}% of this language's recent mentions."
            if regions
            else "Region coverage is still incomplete for this language, so treat location concentration as directional only.",
        ]
        if top_country_names:
            local_reasons.append(f"The strongest country signals inside that region are {', '.join(top_country_names[:3])}.")
        local_reasons.append(
            f"Momentum versus the prior 30-day block is {momentum_pct:+.1f}%, which is why the trend line is tagged as {trend_direction}."
        )
        external_reasons = list(external_facts.get(language, []))
        if str(top_region.get("region") or "") == "Other":
            regional_story = "A large share still lands in 'Other', which means geo enrichment is incomplete; read the regional split as directional rather than exact."
        else:
            regional_story = cls._language_specific_reason(language)
        return {
            "language": language,
            "headline": headline,
            "local_reasons": local_reasons,
            "external_reasons": external_reasons,
            "regional_story": regional_story,
        }

    @classmethod
    def _build_stack_market_item(
        cls,
        *,
        group_row: dict[str, Any],
        region_breakdown: dict[str, list[dict[str, Any]]],
        external_facts: dict[str, list[str]],
    ) -> dict[str, Any]:
        group = str(group_row.get("group") or "").strip()
        regions = list(region_breakdown.get(group) or [])
        top_region = regions[0] if regions else {"region": "Other", "share_pct": 0.0, "countries": []}
        top_country_names = [str(item.get("country") or "").strip() for item in top_region.get("countries", []) if str(item.get("country") or "").strip()]
        trend_direction = str(group_row.get("trend_direction") or "flat")
        momentum_pct = float(group_row.get("momentum_pct") or 0.0)
        headline = (
            f"{group} is accelerating locally"
            if trend_direction == "up"
            else (f"{group} is cooling slightly" if trend_direction == "down" else f"{group} is holding steady locally")
        )
        mix_samples = [str(item or "").strip() for item in group_row.get("signal_mix_samples", []) if str(item or "").strip()]
        local_reasons = [
            f"{group} appears in {int(group_row.get('jobs') or 0)} recent job mentions across the last {int(group_row.get('active_days') or 0)} active days.",
            f"The dominant region is {top_region.get('region') or 'Other'} at {float(top_region.get('share_pct') or 0.0):.1f}% of this group's recent mentions."
            if regions
            else "Region coverage is still incomplete for this stack, so treat location concentration as directional only.",
        ]
        if top_country_names:
            local_reasons.append(f"The strongest country signals inside that region are {', '.join(top_country_names[:3])}.")
        local_reasons.append(
            f"Momentum versus the prior 30-day block is {momentum_pct:+.1f}%, which is why the trend line is tagged as {trend_direction}."
        )
        if mix_samples:
            local_reasons.append(f"Common signal mixes include {', '.join(mix_samples[:2])}.")
        external_reasons = []
        if "frontend" in group.lower() or "full stack" in group.lower():
            external_reasons.extend(external_facts.get("TypeScript", [])[:1] or external_facts.get("JavaScript", [])[:1])
        if "backend" in group.lower() or "full stack" in group.lower():
            external_reasons.extend(external_facts.get("Python", [])[:1])
            external_reasons.extend(external_facts.get("Go", [])[:1] or external_facts.get("Rust", [])[:1])
        if "ai" in group.lower() or "data" in group.lower():
            external_reasons.extend(external_facts.get("Python", [])[:1])
        if "devops" in group.lower():
            external_reasons.extend(external_facts.get("Go", [])[:1] or external_facts.get("Rust", [])[:1])
        if not external_reasons and external_facts.get("APAC"):
            external_reasons.append(external_facts["APAC"][0])
        if str(top_region.get("region") or "") == "Other":
            regional_story = "A large share still lands in 'Other', which means geo enrichment is incomplete; read the regional split as directional rather than exact."
        else:
            regional_story = cls._stack_group_reason(group)
        return {
            "group": group,
            "headline": headline,
            "local_reasons": local_reasons,
            "external_reasons": external_reasons,
            "regional_story": regional_story,
        }

    def language_market_context(
        self,
        *,
        days: int = 90,
        top_n: int = 6,
        countries: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        trend = self.programming_language_hiring_trends(days=days, top_n=top_n, countries=countries or [])
        sources = self._load_market_sources(force_refresh=force_refresh)
        external_facts = self._collect_external_language_facts(sources)
        region_breakdown = {
            str(item.get("language") or ""): list(item.get("regions") or [])
            for item in trend.get("region_breakdown", [])
        }
        items = [
            self._build_language_market_item(
                language_row=item,
                region_breakdown=region_breakdown,
                external_facts=external_facts,
            )
            for item in trend.get("top_languages", [])
        ]
        macro_cards = []
        if external_facts.get("TypeScript"):
            macro_cards.append(
                {
                    "title": "Typed web stacks are still gaining ground",
                    "body": external_facts["TypeScript"][0],
                }
            )
        if external_facts.get("Python"):
            macro_cards.append(
                {
                    "title": "AI and data keep lifting Python demand",
                    "body": external_facts["Python"][0],
                }
            )
        if external_facts.get("APAC"):
            macro_cards.append(
                {
                    "title": "Developer growth stays geographically broad",
                    "body": external_facts["APAC"][0],
                }
            )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cache_ttl_seconds": MARKET_CONTEXT_TTL_SECONDS,
            "sources": sources,
            "macro_cards": macro_cards,
            "items": items,
        }

    def stack_market_context(
        self,
        *,
        days: int = 90,
        top_n: int = 6,
        countries: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        trend = self.programming_stack_hiring_trends(days=days, top_n=top_n, countries=countries or [])
        sources = self._load_market_sources(force_refresh=force_refresh)
        external_facts = self._collect_external_language_facts(sources)
        region_breakdown = {
            str(item.get("group") or ""): list(item.get("regions") or [])
            for item in trend.get("region_breakdown", [])
        }
        items = [
            self._build_stack_market_item(
                group_row=item,
                region_breakdown=region_breakdown,
                external_facts=external_facts,
            )
            for item in trend.get("top_groups", [])
        ]
        macro_cards = []
        if external_facts.get("TypeScript"):
            macro_cards.append(
                {
                    "title": "Frontend and full-stack demand still leans typed",
                    "body": external_facts["TypeScript"][0],
                }
            )
        if external_facts.get("Python"):
            macro_cards.append(
                {
                    "title": "Backend and AI work keep Python broad",
                    "body": external_facts["Python"][0],
                }
            )
        if external_facts.get("Go") or external_facts.get("Rust"):
            macro_cards.append(
                {
                    "title": "Infrastructure roles still reward performance-first stacks",
                    "body": (external_facts.get("Go") or external_facts.get("Rust"))[0],
                }
            )
        if external_facts.get("APAC"):
            macro_cards.append(
                {
                    "title": "Developer growth stays geographically broad",
                    "body": external_facts["APAC"][0],
                }
            )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cache_ttl_seconds": MARKET_CONTEXT_TTL_SECONDS,
            "sources": sources,
            "macro_cards": macro_cards,
            "items": items,
        }

    @staticmethod
    def _safe_text_list(values: Any, limit: int = 3) -> list[str]:
        cleaned: list[str] = []
        for value in list(values or []):
            text = str(value or "").strip()
            if text:
                cleaned.append(text)
            if len(cleaned) >= max(0, limit):
                break
        return cleaned

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            raise ValueError("empty_ai_output")
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            raw = fenced.group(1).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("ai_output_not_object")
        return parsed

    @staticmethod
    def _trend_ai_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thesis": {"type": "string"},
                "confidence": {"type": "number"},
                "dimension_notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {"type": "string"},
                            "reading": {"type": "string"},
                            "evidence_basis": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["dimension", "reading", "evidence_basis", "confidence"],
                    },
                },
                "crawl_expansions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "priority": {"type": "string"},
                            "target": {"type": "string"},
                            "source_types": {"type": "array", "items": {"type": "string"}},
                            "question": {"type": "string"},
                            "why_it_matters": {"type": "string"},
                        },
                        "required": ["priority", "target", "source_types", "question", "why_it_matters"],
                    },
                },
                "limitations": {"type": "array", "items": {"type": "string"}},
                "what_would_change_view": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["thesis", "dimension_notes", "crawl_expansions", "limitations", "what_would_change_view"],
        }

    @classmethod
    def _build_trend_ai_summary(
        cls,
        *,
        trend_kind: str,
        trend: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_kind = "language" if str(trend_kind or "").strip().lower().startswith("lang") else "stack"
        entity_key = "language" if normalized_kind == "language" else "group"
        top_key = "top_languages" if normalized_kind == "language" else "top_groups"
        top_items: list[dict[str, Any]] = []
        for item in list(trend.get(top_key) or [])[:5]:
            name = str(item.get(entity_key) or item.get("group") or item.get("language") or "").strip()
            if not name:
                continue
            top_items.append(
                {
                    "name": name,
                    "jobs": int(item.get("jobs") or 0),
                    "share_pct": float(item.get("share_pct") or 0.0),
                    "momentum_pct": float(item.get("momentum_pct") or 0.0),
                    "dominant_region": str(item.get("dominant_region") or "Other").strip(),
                    "dominant_region_share_pct": float(item.get("dominant_region_share_pct") or 0.0),
                    "region_spread": int(item.get("region_spread") or len(item.get("signal_mix_samples") or [])),
                    "signal_mix_samples": cls._safe_text_list(item.get("signal_mix_samples"), 2),
                }
            )
        source_notes: list[dict[str, Any]] = []
        for source in list(context.get("sources") or [])[:3]:
            source_notes.append(
                {
                    "publisher": str(source.get("publisher") or "").strip(),
                    "title": str(source.get("title") or "").strip(),
                    "status": str(source.get("status") or "").strip(),
                    "facts": cls._safe_text_list([fact.get("text") for fact in list(source.get("facts") or [])], 2),
                }
            )
        context_items: list[dict[str, Any]] = []
        for item in list(context.get("items") or [])[:4]:
            name = str(item.get(entity_key) or item.get("group") or item.get("language") or "").strip()
            if not name:
                continue
            context_items.append(
                {
                    "name": name,
                    "headline": str(item.get("headline") or "").strip(),
                    "regional_story": str(item.get("regional_story") or "").strip(),
                    "local_reasons": cls._safe_text_list(item.get("local_reasons"), 2),
                    "external_reasons": cls._safe_text_list(item.get("external_reasons"), 2),
                }
            )
        return {
            "kind": normalized_kind,
            "window": {
                "days": int(trend.get("days") or 90),
                "date_start": str(trend.get("date_start") or "").strip(),
                "date_end": str(trend.get("date_end") or "").strip(),
            },
            "jobs_considered": int(trend.get("jobs_considered") or 0),
            "top_items": top_items,
            "geo_coverage": trend.get("geo_coverage") or {},
            "macro_cards": list(context.get("macro_cards") or [])[:4],
            "context_items": context_items,
            "source_notes": source_notes,
            "crawl_recommendations": list(trend.get("crawl_recommendations") or [])[:5],
            "dimension_palette": TREND_AI_DIMENSIONS,
        }

    @staticmethod
    def _build_trend_ai_prompt(summary: dict[str, Any]) -> str:
        kind = str(summary.get("kind") or "language").strip()
        kind_label = "programming language" if kind == "language" else "stack group"
        return (
            "You are a local market analyst for Job Ops.\n"
            "Use only the supplied data.\n"
            "Treat economic, social/cultural, policy/regulatory, and geopolitical/conflict explanations as hypotheses unless the evidence is explicit.\n"
            "Do not invent facts beyond the supplied trend snapshot and source notes.\n"
            "Return JSON only.\n\n"
            f"Focus: {kind_label} trend analysis with macro context and crawl expansion.\n"
            f"Input snapshot: {json.dumps(summary, ensure_ascii=False, separators=(',', ':'))}"
        )

    @staticmethod
    def _resolve_ai_base_url() -> str:
        upstream_base_url = str(os.getenv("LLM_UPSTREAM_BASE_URL") or "").strip().rstrip("/")
        if upstream_base_url.endswith("/v1"):
            upstream_base_url = ""
        for value in (
            os.getenv("ANALYTICS_AI_BASE_URL"),
            os.getenv("OLLAMA_BASE_URL"),
            upstream_base_url,
            "http://127.0.0.1:11434",
        ):
            candidate = str(value or "").strip()
            if candidate:
                return candidate.rstrip("/")
        return "http://127.0.0.1:11434"

    def _fallback_trend_ai(self, *, summary: dict[str, Any]) -> dict[str, Any]:
        kind = str(summary.get("kind") or "language").strip()
        top_items = list(summary.get("top_items") or [])
        lead = top_items[0] if top_items else {}
        lead_name = str(lead.get("name") or ("the stack" if kind == "stack" else "the language")).strip()
        momentum = float(lead.get("momentum_pct") or 0.0)
        lead_region = str(lead.get("dominant_region") or "Other").strip()
        thesis = (
            f"{lead_name} is accelerating locally, but the stronger story is the regional concentration and the missing external context needed to validate why."
            if momentum > 0
            else f"{lead_name} is not broad enough yet to support a single macro explanation; the sample is better treated as a directional signal."
        )
        dimensions = [
            {
                "dimension": "economic",
                "reading": f"The pattern likely reflects budget and delivery pressure around {lead_name}, especially where hiring is concentrated in {lead_region}.",
                "evidence_basis": "Local job concentration and recent momentum",
                "confidence": 0.62,
            },
            {
                "dimension": "labor_market",
                "reading": "The sample suggests skills are unevenly distributed across regions, so scarcity and location concentration are both relevant.",
                "evidence_basis": "Dominant region share and region spread",
                "confidence": 0.7,
            },
            {
                "dimension": "social_cultural",
                "reading": "Team operating style may favor the stack where product or collaboration norms are strongest, but this is still a hypothesis.",
                "evidence_basis": "Regional clustering only",
                "confidence": 0.45,
            },
            {
                "dimension": "policy_regulatory",
                "reading": "If the demand is tied to cross-border hiring or compliance-heavy industries, policy friction could matter, but evidence is indirect.",
                "evidence_basis": "No direct policy source yet",
                "confidence": 0.35,
            },
            {
                "dimension": "geopolitical_conflict",
                "reading": "Conflict, sanctions, or supply-chain shifts are only plausible if the adjacent industry mix points that way; do not assume it from the chart alone.",
                "evidence_basis": "No direct geopolitical evidence yet",
                "confidence": 0.3,
            },
            {
                "dimension": "industry_cycle",
                "reading": "The current demand could simply reflect a sector-specific hiring cycle rather than a broad market shift.",
                "evidence_basis": "Recent 90-day trend shape",
                "confidence": 0.66,
            },
        ]
        crawl_recommendations = []
        for item in list(summary.get("crawl_recommendations") or [])[:3]:
            crawl_recommendations.append(
                {
                    "priority": "medium",
                    "target": str(item.get("group") or item.get("language") or lead_name).strip(),
                    "source_types": ["career pages", "company posts", "job backfill"],
                    "question": str(item.get("reason") or "What additional pages would explain the current concentration?").strip(),
                    "why_it_matters": "This would tighten the explanation and reduce overfitting to the current sample.",
                }
            )
        if not crawl_recommendations:
            crawl_recommendations = [
                {
                    "priority": "high",
                    "target": "company career pages and recent openings",
                    "source_types": ["career pages", "ATS pages"],
                    "question": f"Which companies are adding {lead_name} hiring now, and in which regions?",
                    "why_it_matters": "This would show whether the trend is broad hiring or a few concentrated employers.",
                },
                {
                    "priority": "high",
                    "target": "earnings calls and investor letters",
                    "source_types": ["earnings call transcripts", "shareholder letters"],
                    "question": "Are leaders describing budget expansion, cost pressure, or product acceleration that explains the demand shift?",
                    "why_it_matters": "This would connect the chart to economic and strategy drivers.",
                },
                {
                    "priority": "medium",
                    "target": "labor market and regional tech reports",
                    "source_types": ["labor statistics", "regional reports"],
                    "question": "Is the concentration specific to a region, or is it showing up across the wider market?",
                    "why_it_matters": "This would separate local clustering from a broader cycle.",
                },
            ]
        return {
            "trend_kind": kind,
            "model": TUNING_ANALYTICS_AI_MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "thesis": thesis,
            "confidence": 0.55 if momentum != 0 else 0.45,
            "dimension_notes": dimensions,
            "crawl_expansions": crawl_recommendations,
            "limitations": [
                "The chart snapshot is directional, not causal proof.",
                "External market context is still lightweight and may miss the real driver.",
                "Geopolitical and cultural readings are hypotheses until extra sources confirm them.",
            ],
            "what_would_change_view": [
                "A second source set confirms the same macro explanation.",
                "Regional coverage widens enough to change the dominant geography.",
                "Company-specific crawl shows the signal comes from a few employers rather than the broader market.",
            ],
            "cache_ttl_seconds": TUNING_ANALYTICS_AI_CACHE_TTL_SECONDS,
            "cache_state": "fallback",
        }

    def _call_trend_ai_model(self, *, summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
        base_url = self._resolve_ai_base_url()
        prompt = self._build_trend_ai_prompt(summary)
        payload = {
            "model": TUNING_ANALYTICS_AI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON that matches the requested schema.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": self._trend_ai_schema(),
            "options": {
                "temperature": 0.2,
                "num_predict": 420,
                "num_ctx": 2048,
                "num_thread": max(2, min(4, int(os.cpu_count() or 2))),
                "top_k": 20,
                "top_p": 0.9,
                "repeat_penalty": 1.05,
            },
            "keep_alive": "30m",
        }
        response = requests.post(
            f"{base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=TUNING_ANALYTICS_AI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        content = str((data.get("message") or {}).get("content") or "").strip()
        if not content:
            raise ValueError("empty_ai_output")
        parsed = self._extract_json_object(content)
        usage = {
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
            "total_tokens": int((data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)),
            "total_duration": data.get("total_duration"),
            "load_duration": data.get("load_duration"),
            "prompt_eval_duration": data.get("prompt_eval_duration"),
            "eval_duration": data.get("eval_duration"),
            "llm_backend": "ollama_chat",
            "upstream_base_url": base_url,
            "upstream_model": TUNING_ANALYTICS_AI_MODEL,
        }
        return parsed, usage, TUNING_ANALYTICS_AI_MODEL

    def _normalize_trend_ai_output(
        self,
        *,
        raw: dict[str, Any],
        summary: dict[str, Any],
        usage: dict[str, Any],
        model: str,
        cache_state: str,
    ) -> dict[str, Any]:
        fallback = self._fallback_trend_ai(summary=summary)
        kind = str(summary.get("kind") or raw.get("trend_kind") or "language").strip()
        thesis = str(raw.get("thesis") or fallback["thesis"]).strip()
        confidence = raw.get("confidence")
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = float(fallback.get("confidence") or 0.0)
        dimension_notes: list[dict[str, Any]] = []
        raw_dimension_notes = raw.get("dimension_notes") or raw.get("dimensions") or fallback["dimension_notes"]
        for note in list(raw_dimension_notes or [])[:8]:
            if not isinstance(note, dict):
                continue
            dimension_notes.append(
                {
                    "dimension": str(note.get("dimension") or "").strip() or "unknown",
                    "reading": str(note.get("reading") or note.get("summary") or "").strip(),
                    "evidence_basis": str(note.get("evidence_basis") or note.get("evidence") or "").strip(),
                    "confidence": float(note.get("confidence") or confidence_value or 0.0),
                }
            )
        crawl_expansions: list[dict[str, Any]] = []
        raw_crawl_expansions = raw.get("crawl_expansions") or raw.get("crawl_targets") or fallback["crawl_expansions"]
        for item in list(raw_crawl_expansions or [])[:8]:
            if not isinstance(item, dict):
                continue
            crawl_expansions.append(
                {
                    "priority": str(item.get("priority") or "medium").strip(),
                    "target": str(item.get("target") or "").strip(),
                    "source_types": self._safe_text_list(item.get("source_types"), 4),
                    "question": str(item.get("question") or "").strip(),
                    "why_it_matters": str(item.get("why_it_matters") or item.get("reason") or "").strip(),
                }
            )
        limitations = self._safe_text_list(raw.get("limitations") or fallback["limitations"], 6)
        what_would_change_view = self._safe_text_list(raw.get("what_would_change_view") or fallback["what_would_change_view"], 6)
        normalized = {
            "trend_kind": kind,
            "model": str(raw.get("model") or model or TUNING_ANALYTICS_AI_MODEL).strip(),
            "generated_at": str(raw.get("generated_at") or fallback["generated_at"]).strip(),
            "thesis": thesis,
            "confidence": confidence_value,
            "dimension_notes": dimension_notes,
            "crawl_expansions": crawl_expansions,
            "limitations": limitations,
            "what_would_change_view": what_would_change_view,
            "cache_ttl_seconds": int(raw.get("cache_ttl_seconds") or fallback["cache_ttl_seconds"]),
            "cache_state": cache_state,
            "usage": usage,
            "input_snapshot": summary,
        }
        return normalized

    def _trend_ai_cache_key(self, *, summary: dict[str, Any]) -> str:
        payload = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()

    def _store_trend_ai_snapshot(
        self,
        *,
        summary: dict[str, Any],
        result: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        cache_key = self._trend_ai_cache_key(summary=summary)
        cache_state = str(result.get("cache_state") or source or "db").strip() or "db"
        expires_at_dt = datetime.now(timezone.utc) + timedelta(
            seconds=int(result.get("cache_ttl_seconds") or TUNING_ANALYTICS_AI_CACHE_TTL_SECONDS),
        )
        expires_at = expires_at_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return self.repo.upsert_trend_ai_snapshot(
            cache_key=cache_key,
            trend_kind=str(summary.get("kind") or "language").strip(),
            summary=summary,
            result=result,
            model=str(result.get("model") or TUNING_ANALYTICS_AI_MODEL).strip(),
            source=str(source or "nightly").strip() or "nightly",
            cache_state=cache_state,
            expires_at=expires_at,
        )

    def trend_ai_insights(
        self,
        *,
        trend_kind: str,
        trend: dict[str, Any],
        context: dict[str, Any],
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        summary = self._build_trend_ai_summary(trend_kind=trend_kind, trend=trend, context=context)
        cache_key = self._trend_ai_cache_key(summary=summary)
        snapshot = self.repo.get_trend_ai_snapshot(cache_key)
        if snapshot:
            result = dict(snapshot.get("result_json") or {})
            if result:
                result.setdefault("trend_kind", str(snapshot.get("trend_kind") or summary.get("kind") or trend_kind).strip())
                result.setdefault("model", str(snapshot.get("model") or TUNING_ANALYTICS_AI_MODEL).strip())
                result.setdefault("generated_at", str(snapshot.get("generated_at") or "").strip())
                result.setdefault("cache_state", str(snapshot.get("cache_state") or "db").strip() or "db")
                result.setdefault("usage", {})
                result.setdefault("input_snapshot", summary)
                return result

        fallback = self._fallback_trend_ai(summary=summary)
        fallback["trend_kind"] = str(summary.get("kind") or trend_kind).strip()
        fallback["model"] = TUNING_ANALYTICS_AI_MODEL
        fallback["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        fallback["cache_state"] = "db_fallback"
        fallback["usage"] = {"source": "deterministic_db_fallback"}
        self._store_trend_ai_snapshot(summary=summary, result=fallback, source="request_fallback")
        return fallback

    def refresh_trend_ai_snapshots(self) -> dict[str, Any]:
        nightly_windows = [30, 60, 90, 120]
        nightly_top_n = 6
        refreshed: list[dict[str, Any]] = []
        for trend_kind in ("language", "stack"):
            for days in nightly_windows:
                if trend_kind == "language":
                    trend = self.programming_language_hiring_trends(days=days, top_n=nightly_top_n, countries=[])
                    context = self.language_market_context(days=days, top_n=nightly_top_n, countries=[], force_refresh=False)
                else:
                    trend = self.programming_stack_hiring_trends(days=days, top_n=nightly_top_n, countries=[])
                    context = self.stack_market_context(days=days, top_n=nightly_top_n, countries=[], force_refresh=False)
                summary = self._build_trend_ai_summary(trend_kind=trend_kind, trend=trend, context=context)
                try:
                    raw, usage, model = self._call_trend_ai_model(summary=summary)
                    normalized = self._normalize_trend_ai_output(
                        raw=raw,
                        summary=summary,
                        usage=usage,
                        model=model,
                        cache_state="nightly",
                    )
                except Exception as exc:
                    self.logger.warning("Analytics trend AI nightly refresh failed | kind=%s days=%s error=%s", trend_kind, days, exc)
                    normalized = self._fallback_trend_ai(summary=summary)
                    normalized["usage"] = {"error": str(exc)}
                    normalized["cache_state"] = "nightly_fallback"
                stored = self._store_trend_ai_snapshot(summary=summary, result=normalized, source="nightly")
                refreshed.append(
                    {
                        "trend_kind": trend_kind,
                        "days": days,
                        "cache_key": self._trend_ai_cache_key(summary=summary),
                        "cache_state": str(stored.get("cache_state") or normalized.get("cache_state") or "nightly").strip(),
                        "generated_at": str(stored.get("generated_at") or normalized.get("generated_at") or "").strip(),
                    }
                )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "count": len(refreshed),
            "snapshots": refreshed,
        }

    def applied_jobs_trend(self, source: str = "auto") -> dict[str, Any]:
        return self.repo.applied_jobs_trend(source=source)

    def applied_jobs_trend_debug(self) -> dict[str, Any]:
        return self.repo.applied_jobs_trend_debug()
