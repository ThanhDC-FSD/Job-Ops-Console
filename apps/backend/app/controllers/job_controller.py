import logging

from fastapi import APIRouter, HTTPException, Query

from app.schemas.api_models import CompanyPriorityPayload, JobManualApplyPayload, JobPriorityPayload, JobsDeletePayload
from app.services.job_service import JobService


def build_job_router(service: JobService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["jobs"])

    @router.get("/dashboard")
    def dashboard() -> dict:
        return service.dashboard()

    @router.get("/jobs")
    def list_jobs(
        stage: str = Query(default="all"),
        country: str = Query(default=""),
        countries: str = Query(default=""),
        regions: str = Query(default=""),
        exclude_countries: str = Query(default=""),
        languages: str = Query(default=""),
        programming_languages: str = Query(default=""),
        work_models: str = Query(default=""),
        employment_types: str = Query(default=""),
        easy_apply: int = Query(default=-1),
        constraint_mode: str = Query(default="medium"),
        has_cv: int = Query(default=-1),
        apply_error: int = Query(default=-1),
        priority_flag: int = Query(default=-1),
        sort_by: str = Query(default="posted_date_desc"),
        posted_within_days: int = Query(default=0, ge=0, le=3650),
        company: str = Query(default=""),
        search: str = Query(default=""),
        summary_only: int = Query(default=1),
        limit: int = Query(default=40, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        selected_countries = [s.strip() for s in countries.split(",") if s.strip()]
        selected_regions = [s.strip() for s in regions.split(",") if s.strip()]
        selected_exclude_countries = [s.strip() for s in exclude_countries.split(",") if s.strip()]
        selected_languages = [s.strip().lower() for s in languages.split(",") if s.strip()]
        selected_programming_languages = [s.strip() for s in programming_languages.split(",") if s.strip()]
        selected_work_models = [s.strip() for s in work_models.split(",") if s.strip()]
        selected_employment_types = [s.strip() for s in employment_types.split(",") if s.strip()]
        return service.list_jobs(
            stage=stage,
            country=country,
            countries=selected_countries,
            regions=selected_regions,
            exclude_countries=selected_exclude_countries,
            languages=selected_languages,
            programming_languages=selected_programming_languages,
            work_models=selected_work_models,
            employment_types=selected_employment_types,
            easy_apply=easy_apply,
            constraint_mode=constraint_mode,
            has_cv=has_cv,
            apply_error=apply_error,
            priority_flag=priority_flag,
            sort_by=sort_by,
            posted_within_days=posted_within_days,
            company=company,
            search=search,
            summary_only=bool(summary_only),
            limit=limit,
            offset=offset,
        )

    job_logger = logging.getLogger("job_ops.controllers.job")

    @router.get("/jobs/{job_post_id}")
    def job_detail(job_post_id: int, constraint_mode: str = Query(default="medium")) -> dict:
        try:
            row = service.job_detail(job_post_id, constraint_mode=constraint_mode)
        except Exception as exc:
            job_logger.exception("Job detail failure | id=%s constraint=%s", job_post_id, constraint_mode, exc)
            raise HTTPException(status_code=500, detail="Failed to load job detail") from exc
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return row

    @router.get("/jobs/{job_post_id}/cv-preview")
    def job_cv_preview(job_post_id: int, constraint_mode: str = Query(default="medium")) -> dict:
        row = service.cv_preview(job_post_id, constraint_mode=constraint_mode)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return row

    @router.post("/jobs/generated-artifacts/repair")
    def repair_generated_artifacts(
        limit: int = Query(default=100, ge=1, le=500),
        only_missing: int = Query(default=1),
        constraint_mode: str = Query(default="medium"),
    ) -> dict:
        return service.repair_generated_artifacts(
            limit=limit,
            only_missing=bool(only_missing),
            constraint_mode=constraint_mode,
        )

    @router.delete("/jobs")
    def delete_jobs(payload: JobsDeletePayload) -> dict:
        deleted = service.delete_jobs(payload.job_ids)
        return {"ok": True, "deleted": deleted, "requested": len(payload.job_ids)}

    @router.patch("/jobs/{job_post_id}/priority")
    def update_job_priority(job_post_id: int, payload: JobPriorityPayload) -> dict:
        service.update_job_priority_status(
            job_post_id,
            priority_flag=payload.priority_flag,
            note=payload.note,
        )
        row = service.job_detail(job_post_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"ok": True, "item": row}

    @router.patch("/companies/priority")
    def update_company_priority(payload: CompanyPriorityPayload) -> dict:
        service.update_company_priority_status(
            payload.company_name,
            priority_flag=payload.priority_flag,
            note=payload.note,
        )
        return {"ok": True, "company_name": payload.company_name, "priority_flag": payload.priority_flag}

    @router.patch("/jobs/{job_post_id}/manual-apply")
    def mark_job_applied_manual(job_post_id: int, payload: JobManualApplyPayload) -> dict:
        service.mark_job_applied_manual(job_post_id, note=payload.note)
        row = service.job_detail(job_post_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"ok": True, "item": row}

    @router.get("/countries")
    def countries() -> dict:
        return {"items": service.countries()}

    @router.get("/regions")
    def regions() -> dict:
        return {"items": service.regions()}

    @router.get("/regions/countries")
    def region_countries() -> dict:
        return {"items": service.region_countries()}

    @router.get("/programming-languages")
    def programming_languages() -> dict:
        return {"items": service.programming_languages()}

    @router.get("/programming-languages/groups")
    def programming_language_groups() -> dict:
        return {"items": service.programming_language_groups()}

    return router
