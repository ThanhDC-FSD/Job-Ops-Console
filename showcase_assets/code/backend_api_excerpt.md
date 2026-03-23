# Backend API And Filtering Excerpt

This excerpt highlights how the backend exposes a **single operator-facing API surface** while still keeping HTTP parsing, orchestration, and SQL concerns separated.

## Controller Layer

The router accepts many UI-facing filters, normalizes comma-separated values, and forwards a clean payload into the service layer.

```python
def build_job_router(service: JobService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["jobs"])

    @router.get("/jobs")
    def list_jobs(
        stage: str = Query(default="all"),
        countries: str = Query(default=""),
        regions: str = Query(default=""),
        languages: str = Query(default=""),
        programming_languages: str = Query(default=""),
        easy_apply: int = Query(default=-1),
        constraint_mode: str = Query(default="medium"),
        has_cv: int = Query(default=-1),
        summary_only: int = Query(default=1),
        limit: int = Query(default=40, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        selected_countries = [s.strip() for s in countries.split(",") if s.strip()]
        selected_regions = [s.strip() for s in regions.split(",") if s.strip()]
        selected_languages = [s.strip().lower() for s in languages.split(",") if s.strip()]
        selected_programming_languages = [s.strip() for s in programming_languages.split(",") if s.strip()]
        return service.list_jobs(
            stage=stage,
            countries=selected_countries,
            regions=selected_regions,
            languages=selected_languages,
            programming_languages=selected_programming_languages,
            easy_apply=easy_apply,
            constraint_mode=constraint_mode,
            has_cv=has_cv,
            summary_only=bool(summary_only),
            limit=limit,
            offset=offset,
        )

    @router.get("/jobs/{job_post_id}")
    def job_detail(job_post_id: int, constraint_mode: str = Query(default="medium")) -> dict:
        row = service.job_detail(job_post_id, constraint_mode=constraint_mode)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return row

    @router.get("/jobs/{job_post_id}/cv-preview")
    def job_cv_preview(job_post_id: int, constraint_mode: str = Query(default="medium")) -> dict:
        row = service.cv_preview(job_post_id, constraint_mode=constraint_mode)
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return row
```

Why this matters:

- UI filters stay simple because the backend accepts the same shape the console naturally emits
- detail and preview endpoints are split from list endpoints, which keeps large payloads optional
- request validation happens at the API boundary instead of leaking into repository code

## Service Layer

The service enriches raw repository rows with generated artifact paths, validation outputs, and operator-facing fields without mixing SQL into HTTP handlers.

```python
class JobService:
    def __init__(self, repo: JobRepository) -> None:
        self.repo = repo

    def list_jobs(...):
        result = self.repo.list_jobs(...)
        items = [
            self._enrich_generated_cv_artifacts(dict(item))
            for item in (result.get("items") or [])
        ]
        return {
            "total": int(result.get("total") or 0),
            "items": items,
        }

    def cv_preview(self, job_post_id: int, constraint_mode: str = "medium") -> dict | None:
        row = self.repo.get_job_detail(job_post_id, constraint_mode=constraint_mode)
        if row is None:
            return None
        return self._build_cv_preview_payload(dict(row))
```

Why this matters:

- service methods keep the UI stable even if artifact naming or enrichment rules change
- the operator console gets one consistent response shape for jobs, detail, and CV preview
- generated files are surfaced as metadata rather than forcing the frontend to infer paths

## Repository Layer

The repository keeps the filtering and prioritization rules centralized in SQL so the UI can ask for a rich dataset with one request.

```python
class JobRepository:
    def list_jobs(...):
        select_sql = f"""
            SELECT
              jp.id,
              jp.title,
              jp.company,
              jp.location,
              COALESCE(jat.cv_source_path, '') AS cv_source_path,
              {self._effective_priority_flag_sql(...)} AS effective_priority_flag,
              {self._effective_priority_note_sql(...)} AS effective_priority_note
            FROM job_posts jp
            LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
            LEFT JOIN company_preferences cp
              ON LOWER(TRIM(COALESCE(cp.company_name, ''))) = LOWER(TRIM(COALESCE(jp.company, '')))
            WHERE {where_clause}
            ORDER BY {order_by_clause}
            LIMIT ? OFFSET ?
        """
```

Why this matters:

- company rules, job-level overrides, and application state are merged once in persistence logic
- the frontend does not need its own duplicated rule engine
- SQLite stays viable on a weaker local machine because filtering happens in the query, not after loading everything into memory

Design patterns showcased:

- layered architecture
- repository pattern
- response enrichment in a service boundary
- query-driven filtering for local-first applications
