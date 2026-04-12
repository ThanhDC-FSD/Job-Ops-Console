from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "apps" / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if "apscheduler" not in sys.modules:
    apscheduler_module = types.ModuleType("apscheduler")
    schedulers_module = types.ModuleType("apscheduler.schedulers")
    background_module = types.ModuleType("apscheduler.schedulers.background")
    triggers_module = types.ModuleType("apscheduler.triggers")
    cron_module = types.ModuleType("apscheduler.triggers.cron")
    date_module = types.ModuleType("apscheduler.triggers.date")

    class _BackgroundScheduler:  # pragma: no cover - test bootstrap stub
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _CronTrigger:  # pragma: no cover - test bootstrap stub
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _DateTrigger:  # pragma: no cover - test bootstrap stub
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    background_module.BackgroundScheduler = _BackgroundScheduler
    cron_module.CronTrigger = _CronTrigger
    date_module.DateTrigger = _DateTrigger
    sys.modules["apscheduler"] = apscheduler_module
    sys.modules["apscheduler.schedulers"] = schedulers_module
    sys.modules["apscheduler.schedulers.background"] = background_module
    sys.modules["apscheduler.triggers"] = triggers_module
    sys.modules["apscheduler.triggers.cron"] = cron_module
    sys.modules["apscheduler.triggers.date"] = date_module

from app.services.scheduler_runtime import SchedulerRuntime


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def get_jobs(self) -> list[object]:
        return []

    def remove_job(self, job_id: str) -> None:
        raise AssertionError(f"Unexpected remove_job call: {job_id}")

    def add_job(self, func, **kwargs):  # noqa: ANN001
        self.jobs.append({"func": func, "kwargs": kwargs})


class SchedulerRuntimeTest(unittest.TestCase):
    def test_pending_action_run_uses_misfire_grace_window(self) -> None:
        automation_service = MagicMock()
        automation_service.list_schedules.return_value = []
        automation_service.repo.list_pending_overrides.return_value = []
        automation_service.repo.list_pending_scheduled_runs.return_value = [
            {
                "id": 246,
                "detail_json": {"scheduled_for": "2026-04-11T01:38:00+00:00"},
            }
        ]

        runtime = SchedulerRuntime(automation_service=automation_service, learning_service=None)
        fake_scheduler = _FakeScheduler()
        runtime.scheduler = fake_scheduler

        runtime.sync_jobs()

        action_jobs = [job for job in fake_scheduler.jobs if job["kwargs"].get("id") == "action-run:246"]
        self.assertEqual(len(action_jobs), 1)
        self.assertEqual(action_jobs[0]["kwargs"]["misfire_grace_time"], 60)
        self.assertEqual(action_jobs[0]["kwargs"]["max_instances"], 1)
        self.assertTrue(action_jobs[0]["kwargs"]["coalesce"])

    def test_nightly_trend_ai_refresh_job_is_registered(self) -> None:
        automation_service = MagicMock()
        automation_service.list_schedules.return_value = []
        automation_service.repo.list_pending_overrides.return_value = []
        automation_service.repo.list_pending_scheduled_runs.return_value = []

        analytics_service = MagicMock()

        runtime = SchedulerRuntime(
            automation_service=automation_service,
            analytics_service=analytics_service,
            learning_service=None,
        )
        fake_scheduler = _FakeScheduler()
        runtime.scheduler = fake_scheduler

        runtime.sync_jobs()

        trend_jobs = [job for job in fake_scheduler.jobs if job["kwargs"].get("id") == "analytics-trend-ai:nightly-refresh"]
        self.assertEqual(len(trend_jobs), 1)
        self.assertEqual(trend_jobs[0]["kwargs"]["max_instances"], 1)
        self.assertTrue(trend_jobs[0]["kwargs"]["coalesce"])


if __name__ == "__main__":
    unittest.main()
