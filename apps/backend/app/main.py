import asyncio
import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    APP_ENV,
    BACKEND_HOST,
    BACKEND_PORT,
    CLEAR_LOGS_ON_STARTUP,
    DB_PATH,
    FRONTEND_ORIGIN,
    PROJECT_ROOT,
    RUN_STARTUP_BOOTSTRAP_ACTIONS,
    DIAGNOSTICS,
)
from app.controllers.analytics_controller import build_analytics_router
from app.controllers.automation_controller import build_automation_router
from app.controllers.job_controller import build_job_router
from app.controllers.learning_controller import build_learning_router
from app.controllers.local_llm_controller import build_local_llm_router
from app.logging_setup import clear_logs_directory, setup_logging
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.database import Database
from app.repositories.fit_repository import FitRepository
from app.repositories.learning_repository import LearningRepository
from app.repositories.job_repository import JobRepository
from app.repositories.meta_repository import MetaRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.analytics_service import AnalyticsService
from app.services.automation_service import AutomationService
from app.services.cv_rewrite_service import CvRewriteService
from app.services.fit_service import FitService
from app.services.job_service import JobService
from app.services.learning_service import LearningService
from app.services.scheduler_runtime import SchedulerRuntime


def create_app() -> FastAPI:
    if APP_ENV == "dev" and CLEAR_LOGS_ON_STARTUP:
        clear_logs_directory()
    setup_logging()
    logger = logging.getLogger("job_ops.api")

    db = Database()
    meta_repo = MetaRepository(db)
    meta_repo.ensure_app_tables(run_maintenance=False)
    meta_repo.seed_default_schedule_if_empty()

    job_service = JobService(JobRepository(db))
    analytics_service = AnalyticsService(AnalyticsRepository(db))
    fit_service = FitService(FitRepository(db))
    cv_rewrite_service = CvRewriteService(PROJECT_ROOT)
    automation_service = AutomationService(ScheduleRepository(db), fit_service=fit_service)
    learning_service = LearningService(LearningRepository(db), ScheduleRepository(db))
    learning_service.ensure_seed_if_empty(seed_path=PROJECT_ROOT / "learning_plan.md")
    learning_service.ensure_default_job(enqueue_if_empty=True)
    scheduler_runtime = SchedulerRuntime(automation_service, learning_service=learning_service)

    app = FastAPI(title="LinkedIn Job Ops API", version="1.0.0")

    def _build_frontend_origins() -> list[str]:
        origins = {FRONTEND_ORIGIN} if FRONTEND_ORIGIN else set()
        for host in ("127.0.0.1", "localhost"):
            for port in ("5180", "5182", "9999"):
                origins.add(f"http://{host}:{port}")
        return sorted(filter(None, origins))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_frontend_origins(),
        allow_origin_regex=r"chrome-extension://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_log_middleware(request: Request, call_next):
        started = perf_counter()
        body_bytes = b""
        req_for_call = request
        if DIAGNOSTICS or request.method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
            except Exception:
                body_bytes = b""

            async def _receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            req_for_call = Request(request.scope, receive=_receive)

        try:
            response = await call_next(req_for_call)
        except Exception as exc:
            logger.exception(
                "Unhandled exception | method=%s path=%s client=%s",
                request.method,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                {"detail": "Internal server error"},
                status_code=500,
            )

        duration_ms = (perf_counter() - started) * 1000
        logger.info(
            "HTTP %s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        if response.status_code in (404, 405):
            try:
                body_text = None
                if body_bytes:
                    try:
                        body_text = body_bytes.decode("utf-8")
                    except Exception:
                        body_text = str(body_bytes)
                logger.warning(
                    "Missing route or method | method=%s path=%s status=%s client=%s headers=%s body=%s",
                    request.method,
                    request.url.path,
                    response.status_code,
                    request.client.host if request.client else "unknown",
                    dict(request.headers),
                    body_text,
                )
            except Exception:
                logger.exception("Failed to log 404 diagnostic details")

        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "db_path": str(DB_PATH), "env": APP_ENV}

    app.include_router(build_job_router(job_service))
    app.include_router(build_analytics_router(analytics_service))
    app.include_router(build_automation_router(automation_service, fit_service, cv_rewrite_service, job_service, scheduler_runtime))
    app.include_router(build_learning_router(learning_service))
    app.include_router(build_local_llm_router())

    if APP_ENV == "dev" or DIAGNOSTICS:
        @app.get("/debug/routes")
        def debug_routes():
            routes = []
            for r in app.routes:
                try:
                    methods = list(getattr(r, "methods", []))
                except Exception:
                    methods = []
                routes.append({
                    "path": getattr(r, "path", str(r)),
                    "name": getattr(r, "name", None),
                    "methods": methods,
                })
            return routes

    async def _run_startup_bootstrap_actions() -> None:
        try:
            logger.info("Startup bootstrap actions begin")
            await asyncio.to_thread(
                automation_service.trigger_action,
                "crawl_filtered",
                ["--window-days", "30"],
                None,
                "startup",
            )
            await asyncio.to_thread(
                automation_service.trigger_action,
                "crawl_applied",
                [],
                None,
                "startup",
            )
            logger.info("Startup bootstrap actions done")
        except Exception:
            logger.exception("Startup bootstrap actions failed")

    @app.on_event("startup")
    def on_startup() -> None:
        try:
            loop = asyncio.get_running_loop()
            prev_handler = loop.get_exception_handler()

            def _loop_exception_handler(current_loop, context):
                exc = context.get("exception")
                message = str(context.get("message") or "")
                if (
                    isinstance(exc, ConnectionResetError)
                    and getattr(exc, "winerror", None) == 10054
                    and "_ProactorBasePipeTransport._call_connection_lost" in message
                ):
                    logger.debug("Ignore asyncio proactor reset noise | message=%s", message)
                    return
                if prev_handler is not None:
                    prev_handler(current_loop, context)
                else:
                    current_loop.default_exception_handler(context)

            loop.set_exception_handler(_loop_exception_handler)
        except Exception:
            logger.exception("Failed to install asyncio exception filter")
        logger.info("Backend startup | env=%s db_path=%s", APP_ENV, DB_PATH)
        scheduler_runtime.start()
        if RUN_STARTUP_BOOTSTRAP_ACTIONS:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_run_startup_bootstrap_actions())
            except Exception:
                logger.exception("Failed to schedule startup bootstrap actions")
        else:
            logger.info("Startup bootstrap actions skipped | RUN_STARTUP_BOOTSTRAP_ACTIONS=0")

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        logger.info("Backend shutdown")
        scheduler_runtime.shutdown()

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=BACKEND_HOST, port=BACKEND_PORT, reload=True)
