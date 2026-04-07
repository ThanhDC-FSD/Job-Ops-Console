from __future__ import annotations

from typing import Any

from app.repositories.analytics_repository import AnalyticsRepository


class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository) -> None:
        self.repo = repo

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

    def applied_jobs_trend(self, source: str = "auto") -> dict[str, Any]:
        return self.repo.applied_jobs_trend(source=source)

    def applied_jobs_trend_debug(self) -> dict[str, Any]:
        return self.repo.applied_jobs_trend_debug()
