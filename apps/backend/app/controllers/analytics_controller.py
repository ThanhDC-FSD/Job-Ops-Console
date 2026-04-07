from fastapi import APIRouter, Query

from app.services.analytics_service import AnalyticsService


def build_analytics_router(service: AnalyticsService) -> APIRouter:
    router = APIRouter(prefix="/api/analytics", tags=["analytics"])

    @router.get("/reposts")
    def reposts(
        country: str = Query(default=""),
        countries: str = Query(default=""),
        company: str = Query(default=""),
        min_reposts: int = Query(default=1, ge=1),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict:
        selected_countries = [s.strip() for s in countries.split(",") if s.strip()]
        items = service.reposts(
            country=country,
            countries=selected_countries,
            company=company,
            min_reposts=min_reposts,
            limit=limit,
        )
        return {"items": items}

    @router.get("/countries-overview")
    def countries_overview() -> dict:
        return {"items": service.countries_overview()}

    @router.get("/applied-jobs-trend")
    def applied_jobs_trend(source: str = Query(default="auto")) -> dict:
        return service.applied_jobs_trend(source=source)

    @router.get("/applied-jobs-trend/debug")
    def applied_jobs_trend_debug() -> dict:
        return service.applied_jobs_trend_debug()

    return router
