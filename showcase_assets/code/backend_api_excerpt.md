# Backend API Pattern Excerpt

This excerpt highlights the **Controller -> Service -> Repository** separation used in the project. The goal is to keep HTTP concerns, orchestration logic, and persistence logic isolated from each other.

```python
# controller
def build_job_router(service: JobService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["jobs"])

    @router.get("/jobs")
    def jobs(...):
        return service.list_jobs(
            stage=stage,
            country=country,
            countries=countries,
            constraint_mode=constraint_mode,
            summary_only=summary_only,
            limit=limit,
            offset=offset,
        )

# service
class JobService:
    def __init__(self, repo: JobRepository) -> None:
        self.repo = repo

    def list_jobs(...):
        result = self.repo.list_jobs(...)
        items = [self._enrich_generated_cv_artifacts(dict(item)) for item in (result.get("items") or [])]
        return {"total": int(result.get("total") or 0), "items": items}

# repository
class JobRepository:
    def list_jobs(...):
        select_sql = f"""
            SELECT
              jp.id,
              jp.title,
              jp.company,
              COALESCE(jat.cv_source_path, '') AS cv_source_path,
              {self._effective_priority_flag_sql(...)} AS effective_priority_flag
            FROM job_posts jp
            LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
            LEFT JOIN company_preferences cp
              ON LOWER(TRIM(COALESCE(cp.company_name, ''))) = LOWER(TRIM(COALESCE(jp.company, '')))
            WHERE {where_clause}
        """
```

Why this matters:

- `Controller` handles request/response boundaries
- `Service` handles workflow orchestration and response enrichment
- `Repository` stays focused on SQL and persistence

Design pattern showcased:

- layered architecture
- repository pattern
- dependency injection by constructor composition
