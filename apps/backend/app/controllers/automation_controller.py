from pathlib import Path

import logging
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import PROJECT_ROOT
from app.schemas.api_models import (
    ActionArgsPayload,
    ActionTriggerPayload,
    CvRewriteFromJobPayload,
    CvRewriteFromJobsPayload,
    CvRewriteRenderPayload,
    FitEvaluatePayload,
    LinkedinApplyPayload,
    SchedulePayload,
    ScheduleOccurrenceUpdatePayload,
    ScheduleUpdatePayload,
)
from app.services.automation_service import AutomationService
from app.services.cv_rewrite_service import CvRewriteService
from app.services.fit_service import FitService
from app.services.job_service import JobService
from app.services.scheduler_runtime import SchedulerRuntime


def build_automation_router(
    automation: AutomationService,
    fit: FitService,
    cv_rewrite: CvRewriteService,
    jobs: JobService,
    scheduler_runtime: SchedulerRuntime | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["automation"])
    logger = logging.getLogger("job_ops.automation")
    extension_sync_log = (PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "linkedin_extension.sync.log").resolve()
    gmt7 = timezone(timedelta(hours=7))

    def _is_uploadable_cv_path(path_value: str) -> bool:
        return Path(str(path_value or "").strip()).suffix.lower() in {".pdf", ".docx", ".doc", ".rtf"}

    def _is_generated_cv_artifact_path(path_value: str) -> bool:
        raw = str(path_value or "").strip()
        if not raw:
            return False
        try:
            resolved = Path(raw)
            if not resolved.is_absolute():
                resolved = (PROJECT_ROOT / resolved).resolve()
            else:
                resolved = resolved.resolve()
        except Exception:
            return False
        generated_roots = [
            (PROJECT_ROOT / "documents").resolve(),
            (PROJECT_ROOT / "input" / "Raw_CV").resolve(),
        ]
        return any(root == resolved or root in resolved.parents for root in generated_roots)

    def _default_apply_cv_payload() -> CvRewriteFromJobPayload:
        return CvRewriteFromJobPayload(
            cv_master_path="input/full_doc_stlye.txt",
            guide_path="CV_REWRITE_STRICT_GUIDE.md",
            user_prompt=(
                "Bay gio hay dua vao [full_doc_stlye.txt](input/full_doc_stlye.txt) + "
                "JD lay tu DB theo job_id dang chon, cung voi "
                "[CV_REWRITE_STRICT_GUIDE.md](CV_REWRITE_STRICT_GUIDE.md), "
                "va thuc hien cac cong viec trong guide."
            ),
            llm_model="qwen2.5:1.5b-instruct",
            temperature=0.2,
            render_docx=True,
            render_pdf=True,
            run_fit_report=True,
        )

    def _post_apply_crawl_check(job_ids: list[int], run_id: int | None, apply_ok: bool, statuses: list[str] | None) -> None:
        try:
            logger.info(
                "LinkedIn post-apply crawl start | run_id=%s jobs=%s apply_ok=%s statuses=%s",
                run_id,
                job_ids[:10],
                apply_ok,
                statuses or [],
            )
            crawl_result = automation.trigger_action(
                action_type="crawl_applied",
                args=[],
                schedule_id=None,
                triggered_by="post_apply_check",
            )
            logger.info(
                "LinkedIn post-apply crawl done | run_id=%s crawl_run_id=%s status=%s returncode=%s",
                run_id,
                crawl_result.get("run_id"),
                crawl_result.get("status"),
                crawl_result.get("returncode"),
            )
        except Exception:
            logger.exception(
                "LinkedIn post-apply crawl failed | run_id=%s jobs=%s apply_ok=%s statuses=%s",
                run_id,
                job_ids[:10],
                apply_ok,
                statuses or [],
            )

    def _build_manual_review_note(statuses: list[str] | None) -> str:
        normalized = [str(x or "").strip().lower() for x in (statuses or []) if str(x or "").strip()]
        if "apply_timeout" in normalized:
            return "Manual apply needed: automation timed out, likely blocked at Additional Questions. Please complete this job manually on LinkedIn."
        if normalized:
            return f"Manual apply review needed: automation ended with statuses: {', '.join(sorted(set(normalized)))}."
        return "Manual apply review needed: automation did not complete successfully."

    def _manual_review_note_from_sync_log(item: dict) -> tuple[int, str] | None:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        job_id = payload.get("job_id")
        try:
            job_id = int(job_id)
        except Exception:
            return None
        if job_id <= 0:
            return None

        event = str(item.get("event") or "").strip().lower()
        if not event:
            return None

        note = ""
        if event == "page.console":
            level = str(payload.get("level") or "").strip().lower()
            if level not in {"error", "assert"}:
                return None
            text = str(payload.get("text") or "").strip()
            location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
            location_url = str(location.get("url") or "").strip()
            note = f"Apply error from browser console: {text or 'unknown console error'}"
            if location_url:
                note += f" | source={location_url}"
        elif event == "page.request_failed":
            request_url = str(payload.get("url") or payload.get("request_url") or "").strip()
            failure_text = str(payload.get("failure_text") or payload.get("error_text") or payload.get("text") or "").strip()
            note = f"Apply error from network request failure: {failure_text or 'request failed'}"
            if request_url:
                note += f" | url={request_url}"
        elif event == "page.error":
            text = str(payload.get("text") or payload.get("message") or "").strip()
            note = f"Apply error from page exception: {text or 'unhandled page error'}"
        else:
            return None

        return (job_id, note[:1000])

    def _rewrite_render_cv_from_job_impl(job_id: int, payload: CvRewriteFromJobPayload) -> dict:
        logger.info(
            "rewrite-render/from-job start | job_id=%s model=%s render_docx=%s render_pdf=%s fit_report=%s",
            job_id,
            payload.llm_model,
            payload.render_docx,
            payload.render_pdf,
            payload.run_fit_report,
        )
        row = jobs.job_detail(job_id, constraint_mode="medium")
        if row is None:
            logger.error("rewrite-render/from-job failed | job_id=%s reason=job_not_found", job_id)
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
        existing_cv_path = str(row.get("cv_source_path") or "").strip()
        if existing_cv_path:
            existing_cv_file = Path(existing_cv_path)
            if not existing_cv_file.is_absolute():
                existing_cv_file = (PROJECT_ROOT / existing_cv_file).resolve()
            if existing_cv_file.exists() and existing_cv_file.is_file():
                existing_path_norm = str(existing_cv_file)
                if _is_uploadable_cv_path(existing_path_norm) and not _is_generated_cv_artifact_path(existing_path_norm):
                    pdf_path = str(row.get("generated_pdf_path") or "").strip()
                    docx_path = str(row.get("generated_docx_path") or "").strip()
                    cv_text_path = str(row.get("generated_cv_text_path") or "").strip()
                    lower = existing_path_norm.lower()
                    if not pdf_path and lower.endswith(".pdf"):
                        pdf_path = existing_path_norm
                    if not docx_path and lower.endswith(".docx"):
                        docx_path = existing_path_norm
                    logger.info("rewrite-render/from-job skip | job_id=%s reason=cv_already_exists path=%s", job_id, existing_path_norm)
                    return {
                        "ok": True,
                        "job_id": job_id,
                        "title": row.get("title", ""),
                        "skipped_existing": True,
                        "run_folder": "",
                        "cv_path": cv_text_path,
                        "portfolio_path": str(row.get("portfolio_path") or ""),
                        "cover_letter_path": str(row.get("cover_letter_path") or ""),
                        "cover_letter_docx_path": str(row.get("generated_cover_letter_docx_path") or ""),
                        "cover_letter_pdf_path": str(row.get("generated_cover_letter_pdf_path") or ""),
                        "fit_report_path": "",
                        "docx_path": docx_path,
                        "pdf_path": pdf_path,
                        "headline": str(row.get("generated_headline") or ""),
                        "summary": str(row.get("generated_summary") or ""),
                        "experience_summary": str(row.get("generated_experience_summary") or ""),
                        "llm_model": str(row.get("generated_llm_model") or payload.llm_model or ""),
                        "llm_backend": str(row.get("generated_llm_backend") or ""),
                        "llm_usage": dict(row.get("generated_llm_usage") or {"skipped_existing": True}),
                        "cv_text": "",
                    }
                logger.info(
                    "rewrite-render/from-job continue | job_id=%s reason=existing_path_regenerate path=%s",
                    job_id,
                    existing_path_norm,
                )
        jd_text = str(row.get("jd_text") or "").strip()
        if not jd_text:
            jd_text = _extract_jd_from_payload(row)
            if jd_text:
                logger.warning("rewrite-render/from-job fallback | job_id=%s source=latest_payload", job_id)
            else:
                jd_text = _build_minimal_jd_text(row)
                logger.warning("rewrite-render/from-job fallback | job_id=%s source=minimal_context", job_id)

        cv_path = Path(payload.cv_master_path)
        if not cv_path.is_absolute():
            cv_path = (PROJECT_ROOT / cv_path).resolve()
        guide_path = Path(payload.guide_path)
        if not guide_path.is_absolute():
            guide_path = (PROJECT_ROOT / guide_path).resolve()
        if not cv_path.exists():
            logger.error("rewrite-render/from-job failed | job_id=%s reason=cv_path_not_found path=%s", job_id, cv_path)
            raise HTTPException(status_code=400, detail=f"CV path not found: {cv_path}")
        if not guide_path.exists():
            logger.error("rewrite-render/from-job failed | job_id=%s reason=guide_path_not_found path=%s", job_id, guide_path)
            raise HTTPException(status_code=400, detail=f"Guide path not found: {guide_path}")

        cv_master = cv_path.read_text(encoding="utf-8", errors="ignore")
        guide_text = guide_path.read_text(encoding="utf-8", errors="ignore")
        default_slug_parts = [
            str(row.get("company") or "").strip(),
            str(row.get("title") or "").strip(),
            str(row.get("linkedin_posted_date") or "").strip(),
        ]
        slug_hint = payload.output_slug or "_".join([p for p in default_slug_parts if p])[:120]
        jd_name_parts = [
            str(row.get("company") or "").strip(),
            str(row.get("title") or "").strip(),
            str(row.get("linkedin_posted_date") or "").strip(),
        ]
        jd_source_name = "_".join([p for p in jd_name_parts if p]).strip() or "job_context"
        jd_source_name = f"{jd_source_name[:120]}.txt"
        documents_date_folder = cv_rewrite._documents_date_folder()
        company_folder_name = cv_rewrite._build_company_folder_name(str(row.get("company") or ""))
        next_version = jobs.next_generated_artifact_version(
            documents_date_folder=documents_date_folder,
            company_folder_name=company_folder_name,
        )
        try:
            result = cv_rewrite.run_with_text(
                cv_master=cv_master,
                jd_text=jd_text,
                guide_text=guide_text,
                jd_source_name=jd_source_name,
                job_context={
                    "job_id": job_id,
                    "title": str(row.get("title") or ""),
                    "company": str(row.get("company") or ""),
                    "location": str(row.get("location") or ""),
                    "linkedin_posted_date": str(row.get("linkedin_posted_date") or ""),
                    "jd_source": str(row.get("jd_source") or ""),
                    "_artifact_version_number": next_version,
                },
                user_prompt=payload.user_prompt,
                output_slug=slug_hint,
                llm_model=payload.llm_model,
                temperature=float(payload.temperature),
                render_docx=bool(payload.render_docx),
                render_pdf=bool(payload.render_pdf),
                run_fit_report=bool(payload.run_fit_report),
            )
        except ValueError as exc:
            logger.exception("rewrite-render/from-job failed | job_id=%s error=%s", job_id, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info(
            "rewrite-render/from-job done | job_id=%s version=%s materialized=false",
            job_id,
            result.version_number,
        )
        jobs.save_generated_artifact_set(
            job_post_id=job_id,
            documents_date_folder=result.documents_date_folder,
            company_folder_name=result.company_folder_name,
            version_number=result.version_number,
            run_folder_name=result.run_folder,
            output_slug=result.output_slug,
            output_basename=result.output_basename,
            cv_text=result.cv_text,
            portfolio_text=result.portfolio_text,
            cover_letter_text=result.cover_letter_text,
            fit_report_text=result.fit_report_text,
            headline=result.headline,
            summary=result.summary,
            experience_summary=result.experience_summary,
            llm_model=result.llm_model,
            llm_backend=result.llm_backend,
            llm_usage_json=json.dumps(result.llm_usage or {}, ensure_ascii=False),
            source_kind="rewrite",
        )
        jobs.update_generated_cv_path(
            job_id,
            "",
            portfolio_path="",
            cover_letter_path="",
            cover_letter_docx_path="",
            cover_letter_pdf_path="",
            generated_headline=result.headline,
            generated_summary=result.summary,
            generated_experience_summary=result.experience_summary,
            generated_llm_model=result.llm_model,
            generated_llm_backend=result.llm_backend,
            generated_llm_usage_json=json.dumps(result.llm_usage or {}, ensure_ascii=False),
        )
        refreshed = jobs.job_detail(job_id, constraint_mode="medium") or {}
        return {
            "ok": True,
            "job_id": job_id,
            "title": row.get("title", ""),
            "skipped_existing": False,
            "run_folder": result.run_folder,
            "cv_path": result.cv_path,
            "portfolio_path": str(refreshed.get("portfolio_path") or result.portfolio_path or ""),
            "cover_letter_path": result.cover_letter_path,
            "cover_letter_docx_path": result.cover_letter_docx_path,
            "cover_letter_pdf_path": result.cover_letter_pdf_path,
            "fit_report_path": result.fit_report_path,
            "docx_path": result.docx_path,
            "pdf_path": result.pdf_path,
            "headline": result.headline,
            "summary": result.summary,
            "experience_summary": result.experience_summary,
            "llm_backend": result.llm_backend,
            "llm_model": result.llm_model,
            "llm_usage": result.llm_usage,
            "cv_text": result.cv_text,
        }

    def _extract_jd_from_payload(row: dict) -> str:
        latest_payload = row.get("latest_payload")
        if not isinstance(latest_payload, dict):
            raw = str(row.get("latest_payload_json") or "").strip()
            if raw:
                try:
                    latest_payload = json.loads(raw)
                except Exception:
                    latest_payload = {}
            else:
                latest_payload = {}
        for key in (
            "jd",
            "job_description",
            "jobDescription",
            "description",
            "description_text",
            "descriptionText",
            "content",
            "details",
            "summary",
        ):
            text = str(latest_payload.get(key) or "").strip()
            if len(text) >= 30:
                return text
        return ""

    def _build_minimal_jd_text(row: dict) -> str:
        title = str(row.get("title") or "").strip()
        company = str(row.get("company") or "").strip()
        location = str(row.get("location") or "").strip()
        posted = str(row.get("linkedin_posted_date") or row.get("latest_posted_time") or "").strip()
        return "\n".join(
            [
                "JOB CONTEXT (fallback when JD text is unavailable):",
                f"- Title: {title or 'N/A'}",
                f"- Company: {company or 'N/A'}",
                f"- Location: {location or 'N/A'}",
                f"- Posted: {posted or 'N/A'}",
            ]
        )

    @router.get("/schedules")
    def schedules() -> dict:
        return {"items": automation.list_schedules()}

    @router.post("/schedules")
    def create_schedule(payload: SchedulePayload) -> dict:
        created = automation.create_schedule(payload.model_dump())
        if scheduler_runtime is not None:
            scheduler_runtime.sync_jobs()
        return created

    @router.patch("/schedules/{schedule_id}")
    def update_schedule(schedule_id: int, payload: ScheduleUpdatePayload) -> dict:
        updated = automation.update_schedule(schedule_id, payload.model_dump())
        if updated is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        if scheduler_runtime is not None:
            scheduler_runtime.sync_jobs()
        return updated

    @router.patch("/schedules/{schedule_id}/occurrence")
    def update_schedule_occurrence(schedule_id: int, payload: ScheduleOccurrenceUpdatePayload) -> dict:
        try:
            updated = automation.update_schedule_occurrence(schedule_id, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if scheduler_runtime is not None:
            scheduler_runtime.sync_jobs()
        return updated

    @router.delete("/schedules/{schedule_id}/occurrence/{override_id}")
    def cancel_schedule_occurrence(schedule_id: int, override_id: int) -> dict:
        try:
            cancelled = automation.cancel_schedule_occurrence_override(schedule_id, override_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if scheduler_runtime is not None:
            scheduler_runtime.sync_jobs()
        return cancelled

    @router.delete("/schedules/{schedule_id}")
    def delete_schedule(schedule_id: int) -> dict:
        deleted = automation.delete_schedule(schedule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Schedule not found")
        if scheduler_runtime is not None:
            scheduler_runtime.sync_jobs()
        return {"deleted": True, "schedule_id": schedule_id}

    @router.post("/schedules/{schedule_id}/run-now")
    def run_schedule_now(schedule_id: int) -> dict:
        try:
            result = automation.run_schedule_pipeline(schedule_id)
            return {"ok": True, **result}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/runs")
    def runs(limit: int = 50) -> dict:
        return {"items": automation.list_runs(limit)}

    @router.post("/runs/{run_id}/force-stop")
    def force_stop_run(run_id: int) -> dict:
        try:
            return automation.force_stop_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/runs/{run_id}/pause")
    def pause_run(run_id: int) -> dict:
        try:
            return automation.request_pause_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/runs/{run_id}")
    def delete_run(run_id: int) -> dict:
        try:
            deleted = automation.delete_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"ok": True, "run_id": run_id, "deleted": True}

    @router.post("/runs/{run_id}/resume")
    def resume_run(run_id: int, background_tasks: BackgroundTasks) -> dict:
        try:
            started = automation.resume_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if str(started.get("status") or "").lower() == "running":
            background_tasks.add_task(
                automation.execute_action_run,
                run_id=int(started["run_id"]),
                action_type=str(started.get("action_type") or ""),
                args=list(started.get("args") or []),
                schedule_id=None,
                triggered_by="manual_resume",
            )
        return started

    @router.get("/files/content")
    def file_content(path: str = Query(..., min_length=1)) -> FileResponse:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (PROJECT_ROOT / file_path).resolve()
        else:
            file_path = file_path.resolve()
        project_root = PROJECT_ROOT.resolve()
        try:
            file_path.relative_to(project_root)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Only project files are allowed.") from exc
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        suffix = file_path.suffix.lower()
        media_type = "application/pdf" if suffix == ".pdf" else "text/html; charset=utf-8" if suffix == ".html" else None
        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type=media_type,
            content_disposition_type="inline" if suffix in {".pdf", ".html"} else "attachment",
        )

    @router.get("/files/text")
    def file_text(path: str = Query(..., min_length=1)) -> dict:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (PROJECT_ROOT / file_path).resolve()
        else:
            file_path = file_path.resolve()
        project_root = PROJECT_ROOT.resolve()
        try:
            file_path.relative_to(project_root)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Only project files are allowed.") from exc
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        if file_path.suffix.lower() not in {".txt", ".md", ".log"}:
            raise HTTPException(status_code=400, detail="Only .txt/.md/.log files are supported.")
        if file_path.stat().st_size > 2_000_000:
            raise HTTPException(status_code=400, detail="File is too large to preview.")
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        return {"path": str(file_path), "content": content}

    @router.post("/actions/run-crawl-filtered")
    def run_crawl_filtered(background_tasks: BackgroundTasks, payload: ActionArgsPayload = Body(default_factory=ActionArgsPayload)) -> dict:
        return _enqueue_action(
            action_type="crawl_filtered",
            args=payload.args,
            background_tasks=background_tasks,
            triggered_by="manual_api",
        )

    @router.post("/actions/run-crawl-applied")
    def run_crawl_applied(background_tasks: BackgroundTasks, payload: ActionArgsPayload = Body(default_factory=ActionArgsPayload)) -> dict:
        return _enqueue_action(
            action_type="crawl_applied",
            args=payload.args,
            background_tasks=background_tasks,
            triggered_by="manual_api",
        )

    @router.post("/actions/run-learning-etl")
    def run_learning_etl(background_tasks: BackgroundTasks, payload: ActionArgsPayload = Body(default_factory=ActionArgsPayload)) -> dict:
        return _enqueue_action(
            action_type="learning_etl",
            args=payload.args,
            background_tasks=background_tasks,
            triggered_by="manual_api",
        )

    @router.post("/actions/trigger")
    def trigger_action(payload: ActionTriggerPayload, background_tasks: BackgroundTasks) -> dict:
        return _enqueue_action(
            action_type=payload.action_type,
            args=payload.args,
            run_at=payload.run_at,
            background_tasks=background_tasks,
            schedule_id=payload.schedule_id,
            triggered_by=payload.triggered_by,
        )

    def _enqueue_action(
        action_type: str,
        args: list[str],
        background_tasks: BackgroundTasks,
        run_at: str = "",
        *,
        schedule_id: int | None = None,
        triggered_by: str = "manual_api",
    ) -> dict:
        if str(run_at or "").strip():
            started = automation.schedule_action_run(
                action_type=action_type,
                args=args,
                run_at=run_at,
                schedule_id=schedule_id,
                triggered_by=triggered_by,
            )
            if scheduler_runtime is not None:
                scheduler_runtime.sync_jobs()
            return started
        started = automation.start_action_run(
            action_type=action_type,
            args=args,
            schedule_id=schedule_id,
            triggered_by=triggered_by,
        )
        if str(started.get("status") or "").lower() == "running":
            background_tasks.add_task(
                automation.execute_action_run,
                run_id=int(started["run_id"]),
                action_type=action_type,
                args=args,
                schedule_id=schedule_id,
                triggered_by=triggered_by,
            )
        return started

    @router.post("/linkedin/apply")
    def linkedin_apply(payload: LinkedinApplyPayload, background_tasks: BackgroundTasks) -> dict:
        job_ids = [int(x) for x in payload.job_ids if int(x) > 0]
        cv_paths = [str(x).strip() for x in payload.cv_paths if str(x).strip()]
        resolved_cv_paths = [x for x in cv_paths if _is_uploadable_cv_path(x)]
        if not resolved_cv_paths and job_ids:
            logger.info(
                "LinkedIn apply API auto-generate start | jobs=%s requested_cv_count=%s sample_job_ids=%s",
                len(job_ids),
                len(cv_paths),
                job_ids[:10],
            )
            generated_paths: list[str] = []
            gen_payload = _default_apply_cv_payload()
            for job_id in job_ids:
                preview_row = jobs.cv_preview(job_id, constraint_mode="medium") or {}
                generated_path = str(
                    preview_row.get("generated_pdf_path")
                    or preview_row.get("generated_docx_path")
                    or preview_row.get("cv_source_path")
                    or ""
                ).strip()
                if not _is_uploadable_cv_path(generated_path):
                    generated = _rewrite_render_cv_from_job_impl(job_id, gen_payload)
                    generated_path = str(generated.get("pdf_path") or generated.get("docx_path") or "").strip()
                if not _is_uploadable_cv_path(generated_path):
                    preview_row = jobs.cv_preview(job_id, constraint_mode="medium") or {}
                    generated_path = str(
                        preview_row.get("generated_pdf_path")
                        or preview_row.get("generated_docx_path")
                        or preview_row.get("cv_source_path")
                        or ""
                    ).strip()
                if not _is_uploadable_cv_path(generated_path):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to generate uploadable CV for job_id={job_id}",
                    )
                generated_paths.append(generated_path)
            resolved_cv_paths = generated_paths
            logger.info(
                "LinkedIn apply API auto-generate done | jobs=%s generated_cv_count=%s sample_cv_files=%s",
                len(job_ids),
                len(resolved_cv_paths),
                [Path(x).name for x in resolved_cv_paths[:5]],
            )
        if not resolved_cv_paths:
            raise HTTPException(
                status_code=400,
                detail="Apply requires an uploadable CV file (.pdf/.docx/.doc/.rtf).",
            )
        cv_names = [Path(x).name for x in resolved_cv_paths[:5]]
        logger.info(
            "LinkedIn apply API request | jobs=%s cvs=%s dry_run=%s sample_job_ids=%s sample_cv_files=%s",
            len(job_ids),
            len(resolved_cv_paths),
            bool(payload.dry_run),
            job_ids[:10],
            cv_names,
        )
        try:
            result = automation.linkedin_easy_apply(
                job_ids=job_ids,
                cv_paths=resolved_cv_paths,
                dry_run=payload.dry_run,
            )
            if not payload.dry_run:
                background_tasks.add_task(
                    _post_apply_crawl_check,
                    job_ids,
                    result.get("run_id"),
                    bool(result.get("ok", True)),
                    result.get("statuses"),
                )
            if not bool(result.get("ok", True)):
                manual_note = _build_manual_review_note(result.get("statuses"))
                for job_id in job_ids:
                    jobs.update_manual_review_status(job_id, required=True, note=manual_note)
                logger.warning(
                    "LinkedIn apply API non-success | run_id=%s returncode=%s statuses=%s diagnostics=%s jobs=%s cvs=%s",
                    result.get("run_id"),
                    result.get("returncode"),
                    result.get("statuses"),
                    result.get("diagnostics"),
                    len(job_ids),
                    len(resolved_cv_paths),
                )
                return result
            for job_id in job_ids:
                jobs.update_manual_review_status(job_id, required=False, note="")
            logger.info(
                "LinkedIn apply API success | run_id=%s returncode=%s jobs=%s cvs=%s",
                result.get("run_id"),
                result.get("returncode"),
                len(job_ids),
                len(resolved_cv_paths),
            )
            return result
        except ValueError as exc:
            logger.warning(
                "LinkedIn apply API validation failed | jobs=%s cvs=%s dry_run=%s error=%s",
                len(job_ids),
                len(resolved_cv_paths),
                bool(payload.dry_run),
                exc,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            logger.exception(
                "LinkedIn apply API unexpected failure | jobs=%s cvs=%s dry_run=%s",
                len(job_ids),
                len(resolved_cv_paths),
                bool(payload.dry_run),
            )
            raise

    @router.post("/linkedin/extension-logs")
    def linkedin_extension_logs(payload: dict = Body(default={})) -> dict:
        source = str(payload.get("source") or "").strip() or "unknown"
        runtime_mode = str(payload.get("runtime_mode") or "").strip()
        logs = payload.get("logs") or []
        if not isinstance(logs, list):
            raise HTTPException(status_code=400, detail="logs must be a list")
        if len(logs) > 1000:
            logs = logs[-1000:]
        ingested = 0
        manual_review_updates: dict[int, str] = {}
        try:
            extension_sync_log.parent.mkdir(parents=True, exist_ok=True)
            with extension_sync_log.open("a", encoding="utf-8", errors="ignore") as fh:
                for item in logs:
                    if not isinstance(item, dict):
                        continue
                    rec = {
                        "synced_at_gmt7": datetime.now(gmt7).strftime("%Y-%m-%d %H:%M:%S GMT+7"),
                        "source": source,
                        "runtime_mode": runtime_mode,
                        "log": item,
                    }
                    item_at = str((item or {}).get("at") or "").strip()
                    if item_at:
                        try:
                            parsed = datetime.fromisoformat(item_at.replace("Z", "+00:00"))
                            rec["event_at_gmt7"] = parsed.astimezone(gmt7).strftime("%Y-%m-%d %H:%M:%S GMT+7")
                        except Exception:
                            rec["event_at_gmt7"] = item_at
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    sync_issue = _manual_review_note_from_sync_log(item)
                    if sync_issue is not None:
                        job_id, note = sync_issue
                        manual_review_updates[job_id] = note
                    ingested += 1
        except Exception:
            logger.exception("LinkedIn extension logs sync failed | source=%s runtime_mode=%s", source, runtime_mode)
            raise HTTPException(status_code=500, detail="Failed to persist extension logs")

        for job_id, note in manual_review_updates.items():
            try:
                jobs.update_manual_review_status(job_id, required=True, note=note)
            except Exception:
                logger.exception(
                    "LinkedIn extension log apply-error mark failed | source=%s runtime_mode=%s job_id=%s",
                    source,
                    runtime_mode or "-",
                    job_id,
                )
            else:
                logger.warning(
                    "LinkedIn extension log marked apply error | source=%s runtime_mode=%s job_id=%s note=%s",
                    source,
                    runtime_mode or "-",
                    job_id,
                    note,
                )

        logger.info(
            "LinkedIn extension logs synced | source=%s runtime_mode=%s received=%s ingested=%s apply_error_jobs=%s",
            source,
            runtime_mode or "-",
            len(logs),
            ingested,
            len(manual_review_updates),
        )
        return {
            "ok": True,
            "received": len(logs),
            "ingested": ingested,
            "apply_error_jobs": sorted(manual_review_updates.keys()),
            "log_path": str(extension_sync_log),
        }

    @router.get("/cv/files")
    def list_cv_files(ext: str = Query(default="pdf,docx")) -> dict:
        extensions = {f".{x.strip().lower().lstrip('.')}" for x in str(ext).split(",") if x.strip()}
        if not extensions:
            extensions = {".pdf", ".docx"}
        docs_root = (PROJECT_ROOT / "documents").resolve()
        if not docs_root.exists():
            return {"items": []}
        files = []
        for p in docs_root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in extensions:
                continue
            rel = str(p.resolve().relative_to(docs_root)).replace("\\", "/")
            files.append({"name": rel, "path": str(p.resolve()), "ext": p.suffix.lower().lstrip(".")})
        files.sort(key=lambda x: x["name"].lower())
        return {"items": files}

    @router.post("/fit/evaluate")
    def evaluate_fit(payload: FitEvaluatePayload) -> dict:
        cv_path = Path(payload.cv_path)
        if not cv_path.is_absolute():
            cv_path = (PROJECT_ROOT / cv_path).resolve()
        if not cv_path.exists():
            raise HTTPException(status_code=400, detail=f"CV path not found: {cv_path}")
        return fit.evaluate_jobs(
            cv_path=cv_path,
            stage=payload.stage,
            limit=payload.limit,
            constraint_mode=payload.constraint_mode,
            posted_within_days=payload.posted_within_days,
            sort_by=payload.sort_by,
        )

    @router.post("/cv/rewrite-render")
    def rewrite_render_cv(payload: CvRewriteRenderPayload) -> dict:
        cv_path = Path(payload.cv_master_path)
        if not cv_path.is_absolute():
            cv_path = (PROJECT_ROOT / cv_path).resolve()
        jd_path = Path(payload.jd_path)
        if not jd_path.is_absolute():
            jd_path = (PROJECT_ROOT / jd_path).resolve()
        guide_path = Path(payload.guide_path)
        if not guide_path.is_absolute():
            guide_path = (PROJECT_ROOT / guide_path).resolve()

        if not cv_path.exists():
            raise HTTPException(status_code=400, detail=f"CV path not found: {cv_path}")
        if not jd_path.exists():
            raise HTTPException(status_code=400, detail=f"JD path not found: {jd_path}")
        if not guide_path.exists():
            raise HTTPException(status_code=400, detail=f"Guide path not found: {guide_path}")

        try:
            result = cv_rewrite.run(
                cv_master_path=cv_path,
                jd_path=jd_path,
                guide_path=guide_path,
                user_prompt=payload.user_prompt,
                output_slug=payload.output_slug,
                llm_model=payload.llm_model,
                temperature=float(payload.temperature),
                render_docx=bool(payload.render_docx),
                render_pdf=bool(payload.render_pdf),
                run_fit_report=bool(payload.run_fit_report),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "ok": True,
            "run_folder": result.run_folder,
            "cv_path": result.cv_path,
            "cover_letter_path": result.cover_letter_path,
            "cover_letter_docx_path": result.cover_letter_docx_path,
            "cover_letter_pdf_path": result.cover_letter_pdf_path,
            "fit_report_path": result.fit_report_path,
            "docx_path": result.docx_path,
            "pdf_path": result.pdf_path,
            "llm_backend": result.llm_backend,
            "llm_model": result.llm_model,
            "llm_usage": result.llm_usage,
            "cv_text": result.cv_text,
        }

    @router.post("/cv/rewrite-render/from-job/{job_id}")
    def rewrite_render_cv_from_job(job_id: int, payload: CvRewriteFromJobPayload) -> dict:
        return _rewrite_render_cv_from_job_impl(job_id, payload)

    @router.post("/cv/rewrite-render/from-jobs")
    def rewrite_render_cv_from_jobs(payload: CvRewriteFromJobsPayload) -> dict:
        logger.info("rewrite-render/from-jobs start | count=%s", len(payload.job_ids))
        results: list[dict] = []
        errors: list[dict] = []
        base = CvRewriteFromJobPayload(
            cv_master_path=payload.cv_master_path,
            guide_path=payload.guide_path,
            user_prompt=payload.user_prompt,
            output_slug=payload.output_slug,
            llm_model=payload.llm_model,
            temperature=payload.temperature,
            render_docx=payload.render_docx,
            render_pdf=payload.render_pdf,
            run_fit_report=payload.run_fit_report,
        )
        for job_id in payload.job_ids:
            try:
                results.append(rewrite_render_cv_from_job(job_id, base))
            except HTTPException as exc:
                errors.append({"job_id": job_id, "error": str(exc.detail)})
        logger.info("rewrite-render/from-jobs done | ok=%s errors=%s", len(results), len(errors))
        return {
            "ok": len(results) > 0,
            "results": results,
            "errors": errors,
        }

    return router
