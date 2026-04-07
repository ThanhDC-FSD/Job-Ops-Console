# Backend Design Patterns Excerpt

This excerpt is intentionally focused on patterns that are **actually present in the backend**, rather than forcing a label that does not fit the code.

## 1. Composition Root and App-Scoped Object Graph

The backend creates its main dependencies in one place and wires them together explicitly.

```python
def create_app() -> FastAPI:
    db = Database()
    meta_repo = MetaRepository(db)

    job_service = JobService(JobRepository(db))
    analytics_service = AnalyticsService(AnalyticsRepository(db))
    fit_service = FitService(FitRepository(db))
    cv_rewrite_service = CvRewriteService(PROJECT_ROOT)
    automation_service = AutomationService(ScheduleRepository(db), fit_service=fit_service)
    scheduler_runtime = SchedulerRuntime(automation_service)

    app = FastAPI(title="LinkedIn Job Ops API", version="1.0.0")

    app.include_router(build_job_router(job_service))
    app.include_router(build_analytics_router(analytics_service))
    app.include_router(build_automation_router(
        automation_service,
        fit_service,
        cv_rewrite_service,
        job_service,
        scheduler_runtime,
    ))

    return app
```

Why this matters:

- dependency wiring is centralized
- object construction is explicit and readable
- services are reused at the application level instead of being rebuilt per request

Pattern interpretation:

- **composition root**
- **manual dependency injection**
- **singleton-like application lifetime**, but not a strict GoF `Singleton`

## 2. Repository Pattern with Service Coordination

The code keeps SQL-heavy logic in repositories and orchestration logic in services.

```python
class JobService:
    def __init__(self, repo: JobRepository) -> None:
        self.repo = repo

    def list_jobs(...):
        result = self.repo.list_jobs(...)
        items = [self._enrich_generated_cv_artifacts(dict(item)) for item in result.get("items", [])]
        return {"total": int(result.get("total") or 0), "items": items}


class JobRepository:
    def list_jobs(...):
        # filtering, joins, inferred rule SQL, pagination
        ...
```

Pattern interpretation:

- **repository pattern**
- **service layer orchestration**
- **layered architecture**

## 3. Pipeline-Style Generation Workflow

The CV generation flow is organized as a staged workflow rather than one large script.

```python
def run_with_text(...):
    run_folder = self._next_run_folder(jd_slug)
    output_basename = self._build_output_basename(...)
    version_number = self._next_artifact_version(company_documents_dir)

    llm_payload = self._call_llm(...)
    cv_text = str(llm_payload.get("cv_text", "")).strip()

    cv_out.write_text(cv_text + "\\n", encoding="utf-8")
    portfolio_txt_out.write_text(self._build_portfolio_tagged_text(...), encoding="utf-8")

    self._run_subprocess([... render_cv_docx.py ...])
    self._run_subprocess([... render_cv_docx.py ...])
```

Pattern interpretation:

- **pipeline / staged processing**
- **separation of generation and rendering**
- **artifact versioning workflow**

## Practical Note

The current backend does **not** strongly use a formal `Factory pattern`, and it does **not** implement a classic `Singleton` class with global static access.

What it does use is often more useful in practice:

- explicit dependency composition
- app-scoped shared services
- repository and service separation
- staged workflow orchestration

For a production-oriented backend, these patterns are usually more valuable to show than claiming a textbook pattern that is not actually present.
