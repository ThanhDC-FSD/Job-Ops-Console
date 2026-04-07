from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app.services.automation_service import AutomationService
from app.services.learning_service import LearningService


class SchedulerRuntime:
    def __init__(
        self,
        automation_service: AutomationService,
        learning_service: LearningService | None = None,
    ) -> None:
        self.automation_service = automation_service
        self.learning_service = learning_service
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.logger = logging.getLogger("job_ops.scheduler")

    def start(self) -> None:
        if not self.scheduler.running:
            self.sync_jobs()
            self.scheduler.start()
            self.logger.info("Scheduler started")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self.logger.info("Scheduler stopped")

    def sync_jobs(self) -> None:
        removed = 0
        for job in self.scheduler.get_jobs():
            if (
                job.id.startswith("schedule:")
                or job.id.startswith("schedule-override:")
                or job.id.startswith("action-run:")
                or job.id.startswith("learning-schedule:")
            ):
                self.scheduler.remove_job(job.id)
                removed += 1

        scheduled = 0
        schedules = self.automation_service.list_schedules()
        for schedule in schedules:
            if not bool(schedule.get("enabled", 1)):
                continue
            schedule_id = int(schedule["id"])
            cron_expr = str(schedule.get("cron_expr") or "").strip()
            if not cron_expr:
                continue
            timezone_name = str(schedule.get("timezone") or "UTC")
            try:
                trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone_name)
            except Exception as exc:
                self.logger.error("Invalid cron for schedule=%s cron=%s error=%s", schedule_id, cron_expr, exc)
                continue
            self.scheduler.add_job(
                self.automation_service.run_schedule_pipeline,
                trigger=trigger,
                args=[schedule_id],
                id=f"schedule:{schedule_id}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            scheduled += 1

        override_jobs = 0
        for override in self.automation_service.repo.list_pending_overrides():
            override_id = int(override["id"])
            run_at_raw = str(override.get("override_run_at") or "").strip()
            if not run_at_raw:
                continue
            try:
                run_at = datetime.fromisoformat(run_at_raw)
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=timezone.utc)
            except Exception as exc:
                self.logger.error("Invalid override run time | override_id=%s run_at=%s error=%s", override_id, run_at_raw, exc)
                continue
            self.scheduler.add_job(
                self.automation_service.run_schedule_override,
                trigger=DateTrigger(run_date=run_at),
                args=[override_id],
                id=f"schedule-override:{override_id}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            override_jobs += 1

        action_run_jobs = 0
        for row in self.automation_service.repo.list_pending_scheduled_runs():
            run_id = int(row["id"])
            detail = dict(row.get("detail_json") or {})
            run_at_raw = str(detail.get("scheduled_for") or "").strip()
            if not run_at_raw:
                continue
            try:
                run_at = datetime.fromisoformat(run_at_raw)
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=timezone.utc)
            except Exception as exc:
                self.logger.error("Invalid pending action run time | run_id=%s run_at=%s error=%s", run_id, run_at_raw, exc)
                continue
            self.scheduler.add_job(
                self.automation_service.execute_pending_run,
                trigger=DateTrigger(run_date=run_at),
                args=[run_id],
                id=f"action-run:{run_id}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            action_run_jobs += 1

        self.logger.info(
            "Scheduler sync done | removed=%s scheduled=%s override_jobs=%s action_run_jobs=%s",
            removed,
            scheduled,
            override_jobs,
            action_run_jobs,
        )
        self._ensure_idle_sync_job()
        # Learning ETL now runs via automation schedules (pipeline_type=learning_etl).

    def _ensure_idle_sync_job(self) -> None:
        """Keep the low-priority idle DB sync job registered so it can copy when there is slack."""
        self.scheduler.add_job(
            self.automation_service.sync_dev_cd_databases,
            trigger=CronTrigger(minute="*/15"),
            id="idle_db_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    # NOTE: learning queue processor removed to avoid continuous background load.
