from __future__ import annotations

import logging
import json
import os
import sqlite3
import subprocess
import threading
import time
import ast
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.config import (
    PROJECT_ROOT,
    AUTO_SHUTDOWN_AFTER_ETL,
    ETL_SHUTDOWN_DELAY_SECONDS,
    ETL_SHUTDOWN_MESSAGE,
)
from app.repositories.schedule_repository import ScheduleRepository
from app.services.fit_service import FitService


class AutomationService:
    _BLOCKED_WINDOW_START = dt_time(hour=18, minute=0)
    _BLOCKED_WINDOW_END = dt_time(hour=22, minute=0)
    _SHUTDOWN_ACTIONS = {"crawl_filtered", "crawl_applied"}
    _SHUTDOWN_TRIGGERS = {"scheduler"}
    _PAUSE_EXIT_CODE = 2
    _PAUSE_DIR = PROJECT_ROOT / "tmp_seek_automation" / "pauses"
    _CHECKPOINT_DIR = PROJECT_ROOT / "tmp_seek_automation" / "checkpoints"

    def __init__(self, repo: ScheduleRepository, fit_service: FitService | None = None) -> None:
        self.repo = repo
        self.fit_service = fit_service
        self.logger = logging.getLogger("job_ops.automation")
        self._active_processes: dict[int, subprocess.Popen[str]] = {}
        self._active_process_lock = threading.Lock()

    @staticmethod
    def _read_apply_trace_upload_events(limit: int = 20) -> list[str]:
        trace_path = PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "linkedin_apply.trace.log"
        if not trace_path.exists():
            return []
        try:
            lines = trace_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []
        matched = [
            line for line in lines
            if " | cv_path_resolved | " in line
            or " | cv_upload_set | " in line
            or " | cv_upload_input_missing | " in line
            or " | cv_upload_failed | " in line
        ]
        return matched[-limit:]

    @staticmethod
    def _clean_python_env() -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONHOME"] = ""
        env["PYTHONPATH"] = ""
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    @staticmethod
    def _is_lock_skip(stdout_lines: list[str]) -> bool:
        for line in stdout_lines[-20:]:
            text = str(line or "").strip()
            if text.startswith("[LOCK]") and "Skip overlapping execution." in text:
                return True
        return False

    @staticmethod
    def _is_cancelled_status(status: str | None) -> bool:
        return str(status or "").strip().lower() in {"cancelled", "canceled", "stopped"}

    @staticmethod
    def _extract_run_pid(detail: dict[str, Any] | None) -> int | None:
        if not isinstance(detail, dict):
            return None
        try:
            pid = int(detail.get("pid") or 0)
        except Exception:
            return None
        return pid if pid > 0 else None

    def _register_active_process(self, run_id: int, process: subprocess.Popen[str]) -> None:
        with self._active_process_lock:
            self._active_processes[int(run_id)] = process

    def _pop_active_process(self, run_id: int) -> subprocess.Popen[str] | None:
        with self._active_process_lock:
            return self._active_processes.pop(int(run_id), None)

    def _get_active_process(self, run_id: int) -> subprocess.Popen[str] | None:
        with self._active_process_lock:
            return self._active_processes.get(int(run_id))

    @classmethod
    def _pause_flag_path(cls, run_id: int) -> Path:
        return cls._PAUSE_DIR / f"run_{int(run_id)}.pause"

    @classmethod
    def _checkpoint_path(cls, run_id: int, action_type: str) -> Path:
        safe_action = str(action_type or "unknown").strip().lower()
        return cls._CHECKPOINT_DIR / f"run_{int(run_id)}_{safe_action}.json"

    @staticmethod
    def _extract_pause_checkpoint(line: str) -> str:
        text = str(line or "")
        marker = "checkpoint="
        if marker not in text:
            return ""
        tail = text.split(marker, 1)[1].strip()
        if not tail:
            return ""
        if " " in tail:
            tail = tail.split(" ", 1)[0].strip()
        return tail.strip()

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        return self.repo.get_run(run_id)

    @staticmethod
    def _read_lock_metadata(lock_path: Path) -> dict[str, str]:
        try:
            raw = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            raw = ""
        if not raw:
            return {"pid": "", "started_at": "", "run_id": ""}
        parts = [part.strip() for part in raw.split("|")]
        return {
            "pid": parts[0] if len(parts) >= 1 else "",
            "started_at": parts[1] if len(parts) >= 2 else "",
            "run_id": parts[2] if len(parts) >= 3 else "",
        }

    @staticmethod
    def _lock_path_for_action(action_type: str) -> Path | None:
        lock_name_by_action = {
            "crawl_filtered": "linkedin_jobs_jd.lock",
        }
        file_name = lock_name_by_action.get(str(action_type or "").strip().lower())
        if not file_name:
            return None
        return PROJECT_ROOT / "tmp_seek_automation" / "locks" / file_name

    def _release_action_lock(self, action_type: str, *, run_id: int | None = None, pid: int | None = None) -> bool:
        lock_path = self._lock_path_for_action(action_type)
        if lock_path is None or not lock_path.exists():
            return False
        metadata = self._read_lock_metadata(lock_path)
        lock_run_id = str(metadata.get("run_id") or "").strip()
        lock_pid = str(metadata.get("pid") or "").strip()
        if run_id is not None and lock_run_id and lock_run_id != str(run_id):
            self.logger.info(
                "Skipped lock release because lock belongs to another run | action=%s target_run_id=%s lock_run_id=%s",
                action_type,
                run_id,
                lock_run_id,
            )
            return False
        if pid is not None and lock_pid and lock_pid != str(pid):
            self.logger.info(
                "Skipped lock release because lock belongs to another pid | action=%s target_pid=%s lock_pid=%s",
                action_type,
                pid,
                lock_pid,
            )
            return False
        try:
            lock_path.unlink(missing_ok=True)
            self.logger.warning(
                "Automation lock released | action=%s run_id=%s pid=%s path=%s",
                action_type,
                run_id,
                pid,
                lock_path,
            )
            return True
        except Exception:
            self.logger.exception(
                "Failed to release automation lock | action=%s run_id=%s pid=%s path=%s",
                action_type,
                run_id,
                pid,
                lock_path,
            )
            return False

    @staticmethod
    def _kill_process_tree(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            return completed.returncode == 0
        try:
            os.kill(pid, 9)
            return True
        except OSError:
            return False

    def force_stop_run(self, run_id: int, *, release_lock: bool = True) -> dict[str, Any]:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        detail = dict(row.get("detail_json") or {})
        action_type = str(row.get("action_type") or "").strip()
        current_status = str(row.get("status") or "").strip().lower()
        active_process = self._get_active_process(run_id)
        pid = active_process.pid if active_process is not None else self._extract_run_pid(detail)
        killed = self._kill_process_tree(int(pid or 0)) if pid else False
        lock_released = self._release_action_lock(action_type, run_id=run_id, pid=pid) if release_lock else False
        now_iso = datetime.now().astimezone().replace(microsecond=0).isoformat()
        detail.update(
            {
                "pid": int(pid or 0) if pid else None,
                "force_stop_requested_at": now_iso,
                "force_stop_killed_process": bool(killed),
                "force_stop_lock_released": bool(lock_released),
                "partial_db_state_possible": True,
                "progress_message": "Cancelled manually. Process stopped and lock released." if (killed or lock_released) else "Cancelled manually.",
            }
        )
        if current_status not in {"success", "failed", "skipped"}:
            self._update_run_with_retry(
                run_id,
                status="cancelled",
                detail=detail,
                finished=True,
                attempts=10,
                base_delay_seconds=0.5,
                context="force_stop",
            )
        refreshed = self.repo.get_run(run_id) or {"id": run_id, "status": "cancelled", "detail_json": detail}
        return {
            "ok": True,
            "run_id": run_id,
            "status": refreshed.get("status") or "cancelled",
            "pid": pid,
            "process_killed": bool(killed),
            "lock_released": bool(lock_released),
            "detail": refreshed.get("detail_json") or detail,
        }

    def request_pause_run(self, run_id: int) -> dict[str, Any]:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        status = str(row.get("status") or "").strip().lower()
        if status not in {"running"}:
            raise ValueError(f"Run not running: {run_id} status={status}")
        pause_path = self._pause_flag_path(run_id)
        pause_path.parent.mkdir(parents=True, exist_ok=True)
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        try:
            pause_path.write_text(now_iso, encoding="utf-8")
        except Exception:
            self.logger.exception("Failed to write pause flag | run_id=%s path=%s", run_id, pause_path)
            raise
        detail = dict(row.get("detail_json") or {})
        detail.update(
            {
                "pause_requested_at": now_iso,
                "pause_flag_path": str(pause_path),
                "pause_status": "requested",
            }
        )
        self._update_run_with_retry(
            run_id,
            status="running",
            detail=detail,
            attempts=6,
            base_delay_seconds=0.4,
            best_effort=True,
            context="pause_requested",
        )
        self.logger.warning("Pause requested | run_id=%s path=%s", run_id, pause_path)
        return {"ok": True, "run_id": run_id, "status": "running", "pause_flag_path": str(pause_path)}

    def resume_run(self, run_id: int) -> dict[str, Any]:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        status = str(row.get("status") or "").strip().lower()
        if status != "paused":
            raise ValueError(f"Run not paused: {run_id} status={status}")
        action_type = str(row.get("action_type") or "").strip()
        if not action_type:
            raise ValueError(f"Run missing action_type: {run_id}")
        detail = dict(row.get("detail_json") or {})
        checkpoint_path = str(detail.get("pause_checkpoint_path") or "").strip()
        if not checkpoint_path:
            checkpoint_path = str(self._checkpoint_path(run_id, action_type))
        if not checkpoint_path:
            raise ValueError(f"Missing checkpoint path for run: {run_id}")
        pause_flag_path = self._pause_flag_path(run_id)
        if pause_flag_path.exists():
            pause_flag_path.unlink(missing_ok=True)
        args = ["--resume-checkpoint", checkpoint_path]
        schedule_id = row.get("schedule_id")
        new_run = self.start_action_run(
            action_type=action_type,
            args=args,
            schedule_id=int(schedule_id) if schedule_id is not None else None,
            triggered_by="manual_resume",
        )
        detail.update(
            {
                "pause_resumed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "resume_run_id": new_run.get("run_id"),
            }
        )
        self._update_run_with_retry(
            run_id,
            status="paused",
            detail=detail,
            attempts=6,
            base_delay_seconds=0.4,
            best_effort=True,
            context="pause_resumed",
        )
        return {
            "ok": True,
            "run_id": int(new_run.get("run_id")),
            "status": new_run.get("status"),
            "action_type": action_type,
            "args": args,
            "resume_from_run_id": run_id,
        }

    def _get_pending_scheduled_run(self, run_id: int) -> dict[str, Any]:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        status = str(row.get("status") or "").strip().lower()
        if status != "pending":
            raise ValueError(f"Run not pending: {run_id} status={status}")
        detail = dict(row.get("detail_json") or {})
        scheduled_for = str(detail.get("scheduled_for") or "").strip()
        if not scheduled_for:
            raise ValueError(f"Run is not a scheduled pending run: {run_id}")
        row["detail_json"] = detail
        row["scheduled_for"] = scheduled_for
        return row

    def recall_pending_run(self, run_id: int) -> dict[str, Any]:
        row = self._get_pending_scheduled_run(run_id)
        detail = dict(row.get("detail_json") or {})
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        detail["recall_requested_at"] = now_iso
        detail["progress_message"] = "Recall requested"
        self._update_run_with_retry(
            run_id,
            status="pending",
            detail=detail,
            attempts=6,
            base_delay_seconds=0.4,
            context="recall_pending_run",
        )
        self.logger.info("Pending run recall requested | run_id=%s scheduled_for=%s", run_id, row.get("scheduled_for"))
        return {
            "ok": True,
            "run_id": run_id,
            "status": "pending",
            "action_type": row.get("action_type"),
            "scheduled_for": row.get("scheduled_for"),
            "recall_requested_at": now_iso,
        }

    def reschedule_pending_run(self, run_id: int, run_at: str) -> dict[str, Any]:
        row = self._get_pending_scheduled_run(run_id)
        normalized_run_at = self._normalize_occurrence_at(run_at)
        if not normalized_run_at:
            raise ValueError("Invalid run_at")
        detail = dict(row.get("detail_json") or {})
        detail["scheduled_for"] = normalized_run_at
        detail["rescheduled_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        detail["progress_message"] = "Rescheduled"
        self._update_run_with_retry(
            run_id,
            status="pending",
            detail=detail,
            attempts=6,
            base_delay_seconds=0.4,
            context="reschedule_pending_run",
        )
        self.logger.info(
            "Pending run rescheduled | run_id=%s old_scheduled_for=%s new_scheduled_for=%s",
            run_id,
            row.get("scheduled_for"),
            normalized_run_at,
        )
        return {
            "ok": True,
            "run_id": run_id,
            "status": "pending",
            "action_type": row.get("action_type"),
            "scheduled_for": normalized_run_at,
        }

    @staticmethod
    def _is_uploadable_cv_path(path_value: str) -> bool:
        return Path(str(path_value or "").strip()).suffix.lower() in {".pdf", ".docx", ".doc", ".rtf"}

    @staticmethod
    def _normalize_occurrence_at(value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        return dt.isoformat()

    @staticmethod
    def _coerce_schedule_for_override(schedule: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(schedule)
        crawl_config = dict(schedule.get("crawl_config_json") or {})
        crawl_config.update(dict(payload.get("crawl_config") or {}))
        merged["name"] = str(payload.get("name") or schedule.get("name") or "").strip() or str(schedule.get("name") or "")
        merged["timezone"] = str(payload.get("timezone") or schedule.get("timezone") or "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh"
        merged["crawl_config_json"] = crawl_config
        merged["auto_eval_fit"] = bool(payload.get("auto_eval_fit", schedule.get("auto_eval_fit", True)))
        merged["fit_cv_profile"] = str(payload.get("fit_cv_profile") or schedule.get("fit_cv_profile") or "full_doc_stlye")
        merged["auto_generate_cv"] = bool(payload.get("auto_generate_cv", schedule.get("auto_generate_cv", False)))
        merged["fit_threshold"] = float(payload.get("fit_threshold", schedule.get("fit_threshold", 75)) or 75)
        return merged

    @staticmethod
    def _current_occurrence_at(schedule: dict[str, Any]) -> str:
        timezone_name = str(schedule.get("timezone") or "UTC")
        try:
            zone = ZoneInfo(timezone_name)
        except Exception:
            zone = timezone.utc
        now_zone = datetime.now(zone).replace(second=0, microsecond=0)
        return now_zone.astimezone(timezone.utc).isoformat()

    def list_schedules(self) -> list[dict[str, Any]]:
        return self.repo.list_schedules()

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        created = self.repo.create_schedule(payload)
        self.logger.info("Schedule created | id=%s name=%s", created.get("id"), created.get("name"))
        return created

    def update_schedule(self, schedule_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        updated = self.repo.update_schedule(schedule_id, payload)
        self.logger.info("Schedule updated | id=%s exists=%s", schedule_id, updated is not None)
        return updated

    def update_schedule_occurrence(self, schedule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        schedule = self.repo.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule not found: {schedule_id}")
        target_occurrence_at = self._normalize_occurrence_at(payload.get("occurrence_at"))
        override_run_at = self._normalize_occurrence_at(payload.get("run_at"))
        if not target_occurrence_at or not override_run_at:
            raise ValueError("Invalid occurrence_at or run_at")
        override_payload = {
            "name": payload.get("name", schedule.get("name")),
            "timezone": payload.get("timezone", schedule.get("timezone")),
            "crawl_config": dict(payload.get("crawl_config") or {}),
            "auto_eval_fit": bool(payload.get("auto_eval_fit", schedule.get("auto_eval_fit", True))),
            "fit_cv_profile": payload.get("fit_cv_profile", schedule.get("fit_cv_profile", "full_doc_stlye")),
            "auto_generate_cv": bool(payload.get("auto_generate_cv", schedule.get("auto_generate_cv", False))),
            "fit_threshold": float(payload.get("fit_threshold", schedule.get("fit_threshold", 75)) or 75),
        }
        updated = self.repo.upsert_schedule_override(
            schedule_id=schedule_id,
            target_occurrence_at=target_occurrence_at,
            override_run_at=override_run_at,
            override_payload=override_payload,
        )
        self.logger.info(
            "Schedule occurrence override upserted | schedule_id=%s override_id=%s target=%s run_at=%s",
            schedule_id,
            updated.get("id"),
            target_occurrence_at,
            override_run_at,
        )
        return updated

    def cancel_schedule_occurrence_override(self, schedule_id: int, override_id: int) -> dict[str, Any]:
        schedule = self.repo.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule not found: {schedule_id}")
        override = self.repo.get_schedule_override(override_id)
        if override is None or int(override.get("schedule_id") or 0) != int(schedule_id):
            raise ValueError(f"Override not found: {override_id}")
        cancelled = self.repo.cancel_schedule_override(override_id)
        self.logger.info(
            "Schedule occurrence override cancelled | schedule_id=%s override_id=%s",
            schedule_id,
            override_id,
        )
        return cancelled or override

    def delete_schedule(self, schedule_id: int) -> bool:
        deleted = self.repo.delete_schedule(schedule_id)
        self.logger.info("Schedule deleted | id=%s deleted=%s", schedule_id, deleted)
        return deleted

    @staticmethod
    def _run_has_shutdown_cli_flag(run: dict[str, Any]) -> bool:
        detail = dict(run.get("detail_json") or {})
        cmd = [str(part).strip().lower() for part in (detail.get("cmd") or [])]
        scheduled_args = [str(part).strip().lower() for part in (detail.get("scheduled_args") or [])]
        return "--shutdown-when-completed" in cmd or "--shutdown-when-completed" in scheduled_args

    def _annotate_run_shutdown_metadata(self, run: dict[str, Any]) -> dict[str, Any]:
        detail = dict(run.get("detail_json") or {})
        schedule_flag = False
        schedule_id = run.get("schedule_id")
        if schedule_id is not None:
            try:
                schedule = self.repo.get_schedule(int(schedule_id))
            except Exception:
                schedule = None
            if schedule is not None:
                schedule_flag = bool(schedule.get("shutdown_when_completed"))
        cli_flag = self._run_has_shutdown_cli_flag(run)
        run["scheduled_for"] = str(detail.get("scheduled_for") or "").strip()
        run["shutdown_when_completed"] = bool(schedule_flag or cli_flag)
        if schedule_flag and cli_flag:
            run["shutdown_source"] = "schedule+cli"
        elif schedule_flag:
            run["shutdown_source"] = "schedule"
        elif cli_flag:
            run["shutdown_source"] = "cli"
        else:
            run["shutdown_source"] = ""
        return run

    def list_runs(self, limit: int) -> list[dict[str, Any]]:
        rows = self.repo.list_runs(limit)
        return [self._annotate_run_shutdown_metadata(dict(row)) for row in rows]

    def delete_run(self, run_id: int) -> bool:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        status = str(row.get("status") or "").strip().lower()
        if status in {"running", "pending"}:
            raise ValueError(f"Run is active and cannot be deleted: {run_id} status={status}")
        deleted = self.repo.delete_run(run_id)
        self.logger.info("Run deleted | id=%s status=%s deleted=%s", run_id, status, deleted)
        return deleted

    def _build_action_command(self, action_type: str, args: list[str]) -> list[str]:
        if action_type == "crawl_filtered":
            return ["cmd", "/c", str(PROJECT_ROOT / "scripts" / "bat" / "run_linkedin_jobs_jd.bat"), *args]
        if action_type == "crawl_applied":
            return ["cmd", "/c", str(PROJECT_ROOT / "scripts" / "bat" / "run_linkedin_jobs_applied_tracker.bat"), *args]
        if action_type == "generate_cv":
            return ["cmd", "/c", str(PROJECT_ROOT / "scripts" / "bat" / "render_cv_docx.bat"), *args]
        if action_type == "force_db_sync":
            python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            return [str(python_exe), str(PROJECT_ROOT / "scripts" / "python" / "sync_job_databases_safe.py"), *args]
        if action_type == "learning_etl":
            python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            return [str(python_exe), str(PROJECT_ROOT / "scripts" / "python" / "run_learning_etl.py"), *args]
        if action_type == "repair_recent_jobs":
            python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            return [str(python_exe), str(PROJECT_ROOT / "scripts" / "python" / "repair_recent_jobs.py"), *args]
        if action_type == "repair_generated_artifacts":
            python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            return [str(python_exe), str(PROJECT_ROOT / "scripts" / "python" / "repair_generated_artifacts.py"), *args]
        if action_type == "predict_interview_qa":
            python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            return [str(python_exe), str(PROJECT_ROOT / "scripts" / "python" / "predict_night.py"), *args]
        raise ValueError(f"Unsupported action_type: {action_type}")

    @staticmethod
    def _tail_text(lines: list[str], max_chars: int = 12000) -> str:
        text = "\n".join(lines[-200:])
        return text[-max_chars:]

    @staticmethod
    def _is_database_locked_error(exc: BaseException) -> bool:
        return "database is locked" in str(exc).lower()

    def _retry_on_locked(
        self,
        action: Callable[[], Any],
        *,
        attempts: int = 6,
        base_delay_seconds: float = 0.4,
        context: str = "db_write",
        run_id: int | None = None,
    ) -> Any:
        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                result = action()
                if attempt > 1:
                    self.logger.info(
                        "Automation DB write recovered | run_id=%s context=%s attempt=%s",
                        run_id,
                        context,
                        attempt,
                    )
                return result
            except sqlite3.OperationalError as exc:
                if not self._is_database_locked_error(exc):
                    raise
                last_exc = exc
                if attempt >= attempts:
                    raise
                delay = min(3.0, base_delay_seconds * (2 ** (attempt - 1)))
                self.logger.warning(
                    "Automation DB write locked; retrying | run_id=%s context=%s attempt=%s/%s delay_s=%.2f",
                    run_id,
                    context,
                    attempt,
                    attempts,
                    delay,
                )
                time.sleep(delay)
        if last_exc is not None:
            raise last_exc

    def _update_run_with_retry(
        self,
        run_id: int,
        *,
        status: str | None = None,
        detail: dict[str, Any] | None = None,
        finished: bool = False,
        attempts: int = 6,
        base_delay_seconds: float = 0.4,
        best_effort: bool = False,
        context: str = "update",
    ) -> None:
        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                self.repo.update_run(run_id, status=status, detail=detail, finished=finished)
                if attempt > 1:
                    self.logger.info(
                        "Automation run update recovered | run_id=%s context=%s attempt=%s",
                        run_id,
                        context,
                        attempt,
                    )
                return
            except sqlite3.OperationalError as exc:
                if not self._is_database_locked_error(exc):
                    raise
                last_exc = exc
                if attempt >= attempts:
                    if best_effort:
                        self.logger.warning(
                            "Automation run update skipped after retries | run_id=%s context=%s attempts=%s error=%s",
                            run_id,
                            context,
                            attempts,
                            str(exc),
                        )
                        return
                    raise
                delay = min(3.0, base_delay_seconds * (2 ** (attempt - 1)))
                self.logger.warning(
                    "Automation run update locked; retrying | run_id=%s context=%s attempt=%s/%s delay_s=%.2f",
                    run_id,
                    context,
                    attempt,
                    attempts,
                    delay,
                )
                time.sleep(delay)
        if last_exc is not None and not best_effort:
            raise last_exc

    @staticmethod
    def _infer_phase(action_type: str, line: str, current_phase: str) -> str:
        text = str(line or "").strip()
        if not text:
            return current_phase
        if "[LOCK]" in text:
            return "locked"
        if "[API] Found" in text or "[INPUT] Found" in text or "[Playwright] Found" in text:
            return "fetch_jobs"
        if "Enriching" in text:
            return "extract_job_detail"
        if text.startswith("[DB WRITE]") or text.startswith("[DB]"):
            return "db_write"
        if text.startswith("[REPAIR]"):
            return "repair_recent"
        if text.startswith("[ARTIFACT REPAIR]"):
            return "repair_generated_artifacts"
        if text.startswith("[PREDICT]"):
            return "predict_interview_qa"
        if text.startswith("[DETAIL VALIDATION]"):
            return "detail_validation"
        if text.startswith("[FIT]"):
            return "evaluate_fit"
        if text.startswith("[CV SYNC]"):
            return "sync_cv"
        if text.startswith("Saved JSON") or text.startswith("Saved CSV") or text.startswith("Saved DB"):
            return "persist_outputs"
        if text.startswith("[PHASE]"):
            lowered = text.lower()
            if "extract" in lowered:
                return "extract_job_detail"
            if "db" in lowered:
                return "db_write"
            if "fit" in lowered:
                return "evaluate_fit"
            if "cv" in lowered:
                return "sync_cv"
            if "validation" in lowered:
                return "detail_validation"
        return current_phase

    def _issue_shutdown_command(self) -> None:
        if not AUTO_SHUTDOWN_AFTER_ETL:
            return
        if os.name != "nt":
            self.logger.info("Shutdown suppressed | platform=%s not supported for automated shutdown", os.name)
            return
        cmd = [
            "shutdown",
            "/s",
            "/t",
            str(ETL_SHUTDOWN_DELAY_SECONDS),
            "/c",
            ETL_SHUTDOWN_MESSAGE,
        ]
        try:
            subprocess.run(cmd, check=False)
            self.logger.info("Shutdown command issued after ETL completion | cmd=%s", cmd)
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Failed to issue shutdown command after ETL | error=%s", exc)

    def _maybe_shutdown_after_action(self, action_type: str, triggered_by: str | None, schedule_id: int | None = None) -> None:
        if not AUTO_SHUTDOWN_AFTER_ETL:
            return
        if action_type not in self._SHUTDOWN_ACTIONS:
            return
        if not triggered_by:
            return
        if triggered_by not in self._SHUTDOWN_TRIGGERS:
            return
        if schedule_id is not None:
            try:
                schedule = self.repo.get_schedule(int(schedule_id))
            except Exception:
                schedule = None
            if schedule:
                cfg = schedule.get("crawl_config_json") or schedule.get("crawl_config") or {}
                if not bool(cfg.get("shutdown_when_completed")):
                    self.logger.debug(
                        "Shutdown skipped for schedule | schedule_id=%s flag=off triggered_by=%s",
                        schedule_id,
                        triggered_by,
                    )
                    return
        self._issue_shutdown_command()

    def _run_log_path(self, run_id: int, action_type: str) -> Path:
        log_dir = PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "etl_runs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"automation_run_{run_id}_{action_type}.log"

    def sync_dev_cd_databases(self) -> bool:
        """Copy the crawling database into the API/CD schema copy when idle."""
        if self.repo.has_active_runs():
            self.logger.info("Skipping idle DB sync because automation runs are active")
            return False
        source_path = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
        target_path = PROJECT_ROOT / "apps" / "backend" / "app" / "job_ops_schema.sqlite"
        if not source_path.exists():
            self.logger.warning("Idle DB sync skipped | source missing: %s", source_path)
            return False
        if target_path.exists():
            source_mtime = source_path.stat().st_mtime
            target_mtime = target_path.stat().st_mtime
            if target_mtime >= source_mtime:
                self.logger.debug("Idle DB sync no-op | target already up to date")
                return False
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=10.0) as source_conn:
                with sqlite3.connect(str(target_path), timeout=10.0) as target_conn:
                    source_conn.backup(target_conn)
                    target_conn.execute("PRAGMA wal_checkpoint(FULL);")
            self.logger.info("Idle DB sync complete | %s -> %s", source_path, target_path)
        except Exception:
            self.logger.exception("Idle DB sync failed | %s -> %s", source_path, target_path)
            return False
        return True

    def _is_in_blocked_window(self, timezone_name: str) -> bool:
        zone_name = str(timezone_name or "UTC").strip() or "UTC"
        try:
            zone = ZoneInfo(zone_name)
        except Exception:
            zone = ZoneInfo("UTC")
        now_time = datetime.now(zone).time()
        return self._BLOCKED_WINDOW_START <= now_time < self._BLOCKED_WINDOW_END

    def start_action_run(
        self,
        *,
        action_type: str,
        args: list[str] | None = None,
        schedule_id: int | None = None,
        triggered_by: str = "manual_api",
        status: str = "running",
        extra_detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args = args or []
        if action_type == "learning_etl" and self.repo.has_active_run(action_type=action_type):
            detail = {
                "cmd": [],
                "phase": "skipped",
                "progress_message": "Skipped: another learning_etl run is active.",
                "stdout": "",
                "stderr": "",
                "returncode": None,
            }
            run_id = int(
                self._retry_on_locked(
                    lambda: self.repo.insert_run(
                        schedule_id=schedule_id,
                        action_type=action_type,
                        status="skipped",
                        detail=detail,
                        triggered_by=triggered_by,
                    ),
                    attempts=10,
                    base_delay_seconds=0.5,
                    context="insert_skipped_run",
                )
            )
            self.logger.info(
                "Trigger action skipped | run_id=%s action=%s reason=already_running",
                run_id,
                action_type,
            )
            return {"run_id": run_id, "status": "skipped", **detail}
        cmd = self._build_action_command(action_type, args)
        detail = {
            "cmd": cmd,
            "phase": "scheduled" if status == "pending" else "queued",
            "progress_message": "Scheduled" if status == "pending" else "Queued",
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }
        if extra_detail:
            detail.update(extra_detail)
        run_id = int(
            self._retry_on_locked(
                lambda: self.repo.create_run(
                    schedule_id=schedule_id,
                    action_type=action_type,
                    triggered_by=triggered_by,
                    status=status,
                    detail=detail,
                ),
                attempts=10,
                base_delay_seconds=0.5,
                context="create_run",
            )
        )
        log_path = self._run_log_path(run_id, action_type)
        detail["log_path"] = str(log_path)
        self._update_run_with_retry(run_id, detail=detail, context="queue_log_path")
        self.logger.info(
            "Trigger action queued | run_id=%s action=%s schedule_id=%s triggered_by=%s args=%s",
            run_id,
            action_type,
            schedule_id,
            triggered_by,
            args,
        )
        if action_type == "predict_interview_qa":
            self.logger.info(
                "Predict interview QA queued | run_id=%s triggered_by=%s args_count=%s has_cv_path=%s has_jd=%s scheduled=%s",
                run_id,
                triggered_by,
                len(args),
                any(str(arg).startswith("--cv-path") for arg in args),
                any(str(arg).startswith("--jd-text-base64") for arg in args),
                status == "pending",
            )
        return {"run_id": run_id, "status": status, **detail}

    def schedule_action_run(
        self,
        *,
        action_type: str,
        args: list[str] | None = None,
        run_at: str,
        schedule_id: int | None = None,
        triggered_by: str = "manual_api",
    ) -> dict[str, Any]:
        normalized_run_at = self._normalize_occurrence_at(run_at)
        if not normalized_run_at:
            raise ValueError("Invalid run_at")
        return self.start_action_run(
            action_type=action_type,
            args=args or [],
            schedule_id=schedule_id,
            triggered_by=triggered_by,
            status="pending",
            extra_detail={
                "scheduled_for": normalized_run_at,
                "scheduled_args": list(args or []),
            },
        )

    def execute_pending_run(self, run_id: int) -> dict[str, Any]:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        if str(row.get("status") or "").strip().lower() != "pending":
            return {
                "run_id": run_id,
                "status": row.get("status"),
            }
        detail = dict(row.get("detail_json") or {})
        args = list(detail.get("scheduled_args") or [])
        detail["phase"] = "queued"
        detail["progress_message"] = "Queued"
        detail["scheduled_released_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._update_run_with_retry(
            run_id,
            status="running",
            detail=detail,
            context="release_pending_run",
        )
        return self.execute_action_run(
            run_id=run_id,
            action_type=str(row.get("action_type") or ""),
            args=args,
            schedule_id=row.get("schedule_id"),
            triggered_by=str(row.get("triggered_by") or "manual_api"),
        )

    def execute_action_run(
        self,
        *,
        run_id: int,
        action_type: str,
        args: list[str] | None = None,
        schedule_id: int | None = None,
        triggered_by: str = "manual_api",
    ) -> dict[str, Any]:
        args = args or []
        cmd = self._build_action_command(action_type, args)
        log_path = self._run_log_path(run_id, action_type)
        phase = "starting"
        stdout_lines: list[str] = []
        detail: dict[str, Any] = {
            "cmd": cmd,
            "phase": phase,
            "progress_message": "Starting",
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "log_path": str(log_path),
        }
        self._update_run_with_retry(
            run_id,
            status="running",
            detail=detail,
            attempts=8,
            base_delay_seconds=0.5,
            context="start",
        )
        self.logger.info(
            "Trigger action start | run_id=%s action=%s schedule_id=%s triggered_by=%s args=%s",
            run_id,
            action_type,
            schedule_id,
            triggered_by,
            args,
        )
        if action_type == "predict_interview_qa":
            self.logger.info(
                "Predict interview QA start | run_id=%s triggered_by=%s args_count=%s log_path=%s",
                run_id,
                triggered_by,
                len(args),
                log_path,
            )
        started = time.perf_counter()
        try:
            with log_path.open("a", encoding="utf-8", errors="ignore") as log_file:
                env = self._clean_python_env()
                env["AUTOMATION_RUN_ID"] = str(run_id)
                process = subprocess.Popen(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    bufsize=1,
                    env=env,
                )
                self._register_active_process(run_id, process)
                detail["pid"] = int(process.pid or 0)
                self._update_run_with_retry(
                    run_id,
                    status="running",
                    detail=detail,
                    attempts=8,
                    base_delay_seconds=0.5,
                    best_effort=True,
                    context="pid_registered",
                )
                line_count = 0
                last_flush = time.perf_counter()
                if process.stdout is not None:
                    for raw_line in process.stdout:
                        line = str(raw_line or "").rstrip()
                        log_file.write(line + "\n")
                        log_file.flush()
                        if not line:
                            continue
                        line_count += 1
                        stdout_lines.append(line)
                        phase = self._infer_phase(action_type, line, phase)
                        if "[PAUSE]" in line:
                            checkpoint_path = self._extract_pause_checkpoint(line)
                            if checkpoint_path:
                                detail["pause_checkpoint_path"] = checkpoint_path
                        detail.update(
                            {
                                "phase": phase,
                                "progress_message": line[-500:],
                                "stdout": self._tail_text(stdout_lines),
                                "stdout_tail_lines": stdout_lines[-20:],
                                "line_count": line_count,
                                "returncode": None,
                            }
                        )
                        now = time.perf_counter()
                        if line_count == 1 or line_count % 8 == 0 or (now - last_flush) >= 2.0:
                            self._update_run_with_retry(
                                run_id,
                                status="running",
                                detail=detail,
                                attempts=5,
                                base_delay_seconds=0.35,
                                best_effort=True,
                                context="progress",
                            )
                            last_flush = now
                process.wait()
                detail["returncode"] = int(process.returncode or 0)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            current_run = self.repo.get_run(run_id) or {}
            if self._is_cancelled_status(str(current_run.get("status") or "")):
                detail["elapsed_ms"] = elapsed_ms
                detail["progress_message"] = str(
                    (current_run.get("detail_json") or {}).get("progress_message")
                    or detail.get("progress_message")
                    or "Cancelled manually."
                )
                self.logger.info(
                    "Trigger action cancelled | run_id=%s action=%s returncode=%s elapsed_ms=%s",
                    run_id,
                    action_type,
                    detail["returncode"],
                    elapsed_ms,
                )
                return {"run_id": run_id, "status": "cancelled", **detail}
            if int(detail.get("returncode") or 0) == self._PAUSE_EXIT_CODE or any("[PAUSE]" in line for line in stdout_lines[-10:]):
                detail["elapsed_ms"] = elapsed_ms
                detail["progress_message"] = detail.get("progress_message") or "Paused by request."
                detail["pause_requested_at"] = (current_run.get("detail_json") or {}).get("pause_requested_at")
                detail["pause_status"] = "paused"
                self._update_run_with_retry(
                    run_id,
                    status="paused",
                    detail=detail,
                    finished=True,
                    attempts=6,
                    base_delay_seconds=0.5,
                    best_effort=True,
                    context="paused",
                )
                self.logger.warning(
                    "Trigger action paused | run_id=%s action=%s returncode=%s elapsed_ms=%s",
                    run_id,
                    action_type,
                    detail["returncode"],
                    elapsed_ms,
                )
                return {"run_id": run_id, "status": "paused", **detail}
            status = "success" if int(detail["returncode"] or 0) == 0 else "failed"
            if status == "success" and self._is_lock_skip(stdout_lines):
                status = "skipped"
                detail["progress_message"] = "Skipped: overlapping crawl run is already active."
                detail["skip_reason"] = "overlapping_execution"
            detail["elapsed_ms"] = elapsed_ms
            self._update_run_with_retry(
                run_id,
                status=status,
                detail=detail,
                finished=True,
                attempts=10,
                base_delay_seconds=0.5,
                context="final",
            )
            self.logger.info(
                "Trigger action done | run_id=%s action=%s status=%s returncode=%s elapsed_ms=%s",
                run_id,
                action_type,
                status,
                detail["returncode"],
                elapsed_ms,
            )
            return {"run_id": run_id, "status": status, **detail}
        except Exception as exc:
            current_run = self.repo.get_run(run_id) or {}
            if self._is_cancelled_status(str(current_run.get("status") or "")):
                self.logger.info(
                    "Trigger action stop acknowledged after cancellation | run_id=%s action=%s",
                    run_id,
                    action_type,
                )
                return {
                    "run_id": run_id,
                    "status": "cancelled",
                    **dict(current_run.get("detail_json") or detail),
                }
            detail["stderr"] = str(exc)
            detail["progress_message"] = str(exc)
            try:
                self._update_run_with_retry(
                    run_id,
                    status="failed",
                    detail=detail,
                    finished=True,
                    attempts=10,
                    base_delay_seconds=0.5,
                    best_effort=True,
                    context="final_failure",
                )
            except Exception:
                self.logger.exception(
                    "Failed to persist failed automation run state | run_id=%s action=%s",
                    run_id,
                    action_type,
                )
            self.logger.exception(
                "Trigger action failed | run_id=%s action=%s error=%s",
                run_id,
                action_type,
                str(exc),
            )
            raise
        finally:
            self._pop_active_process(run_id)
            self._maybe_shutdown_after_action(action_type, triggered_by, schedule_id)

    def trigger_action(
        self,
        action_type: str,
        args: list[str] | None = None,
        schedule_id: int | None = None,
        triggered_by: str = "manual_api",
    ) -> dict[str, Any]:
        args = args or []
        started = self.start_action_run(
            action_type=action_type,
            args=args,
            schedule_id=schedule_id,
            triggered_by=triggered_by,
        )
        if str(started.get("status") or "").lower() != "running":
            return started
        return self.execute_action_run(
            run_id=int(started["run_id"]),
            action_type=action_type,
            args=args,
            schedule_id=schedule_id,
            triggered_by=triggered_by,
        )

    def _run_schedule_pipeline_core(
        self,
        *,
        schedule_id: int,
        schedule: dict[str, Any],
        triggered_by: str,
        override_id: int | None = None,
    ) -> dict[str, Any]:
        timezone_name = str(schedule.get("timezone") or "UTC")
        if self._is_in_blocked_window(timezone_name):
            self.logger.info(
                "Scheduled pipeline skipped | schedule_id=%s timezone=%s reason=blocked_window override_id=%s",
                schedule_id,
                timezone_name,
                override_id,
            )
            return {
                "schedule_id": schedule_id,
                "status": "skipped",
                "reason": "blocked_window",
                "timezone": timezone_name,
                "override_id": override_id,
            }

        crawl_config = schedule.get("crawl_config_json", {}) or {}
        pipeline_type = schedule.get("pipeline_type", "filtered_jobs")
        repair_recent_enabled = bool(crawl_config.get("repair_recent_enabled", False))
        artifact_repair_enabled = bool(crawl_config.get("artifact_repair_enabled", False))
        actions: list[dict[str, Any]] = []

        if pipeline_type == "filtered_jobs":
            args = []
            if crawl_config.get("window_days"):
                args.extend(["--window-days", str(crawl_config["window_days"])])
            if crawl_config.get("max_jobs"):
                args.extend(["--max-jobs", str(crawl_config["max_jobs"])])
            if crawl_config.get("url"):
                args.extend(["--url", str(crawl_config["url"])])
            if crawl_config.get("constraint_mode"):
                args.extend(["--constraint-mode", str(crawl_config["constraint_mode"])])
            actions.append(
                self.trigger_action(
                    action_type="crawl_filtered",
                    args=args,
                    schedule_id=schedule_id,
                    triggered_by=triggered_by,
                )
            )
            crawl_result = actions[-1]
            if repair_recent_enabled and str(crawl_result.get("status") or "").lower() == "success":
                repair_args: list[str] = []
                if crawl_config.get("repair_recent_days"):
                    repair_args.extend(["--recent-days", str(crawl_config["repair_recent_days"])])
                if crawl_config.get("constraint_mode"):
                    repair_args.extend(["--constraint-mode", str(crawl_config["constraint_mode"])])
                if crawl_config.get("repair_targeted_only"):
                    repair_args.append("--targeted-only")
                if crawl_config.get("repair_disable_llm"):
                    repair_args.append("--disable-llm")
                repair_args.extend(["--max-candidates", "30"])
                actions.append(
                    self.trigger_action(
                        action_type="repair_recent_jobs",
                        args=repair_args,
                        schedule_id=schedule_id,
                        triggered_by=triggered_by,
                    )
                )
            if artifact_repair_enabled and str(crawl_result.get("status") or "").lower() == "success":
                artifact_args: list[str] = []
                if crawl_config.get("artifact_repair_days"):
                    artifact_args.extend(["--recent-days", str(crawl_config["artifact_repair_days"])])
                if crawl_config.get("artifact_repair_limit"):
                    artifact_args.extend(["--limit", str(crawl_config["artifact_repair_limit"])])
                if crawl_config.get("constraint_mode"):
                    artifact_args.extend(["--constraint-mode", str(crawl_config["constraint_mode"])])
                if crawl_config.get("artifact_repair_only_missing", True):
                    artifact_args.append("--only-missing")
                actions.append(
                    self.trigger_action(
                        action_type="repair_generated_artifacts",
                        args=artifact_args,
                        schedule_id=schedule_id,
                        triggered_by=triggered_by,
                    )
                )
        elif pipeline_type == "applied_jobs":
            args = []
            if crawl_config.get("constraint_mode"):
                args.extend(["--constraint-mode", str(crawl_config["constraint_mode"])])
            actions.append(
                self.trigger_action(
                    action_type="crawl_applied",
                    args=args,
                    schedule_id=schedule_id,
                    triggered_by=triggered_by,
                )
            )
        elif pipeline_type == "learning_etl":
            args = []
            if crawl_config:
                args.extend(["--payload", json.dumps(crawl_config, ensure_ascii=False)])
            actions.append(
                self.trigger_action(
                    action_type="learning_etl",
                    args=args,
                    schedule_id=schedule_id,
                    triggered_by=triggered_by,
                )
            )
        elif pipeline_type == "interview_prediction":
            args = ["--mode", "nightly"]
            if crawl_config.get("prediction_limit"):
                args.extend(["--limit", str(crawl_config["prediction_limit"])])
            if crawl_config.get("prediction_recent_days"):
                args.extend(["--recent-days", str(crawl_config["prediction_recent_days"])])
            if crawl_config.get("cv_path"):
                args.extend(["--cv-path", str(crawl_config["cv_path"])])
            if bool(crawl_config.get("prediction_force", False)):
                args.append("--force")
            actions.append(
                self.trigger_action(
                    action_type="predict_interview_qa",
                    args=args,
                    schedule_id=schedule_id,
                    triggered_by=triggered_by,
                )
            )
        else:
            raise ValueError(f"Unsupported pipeline_type: {pipeline_type}")

        if (
            pipeline_type in {"filtered_jobs", "applied_jobs"}
            and bool(schedule.get("auto_eval_fit", 1))
            and self.fit_service is not None
            and not repair_recent_enabled
        ):
            constraint_mode = str(crawl_config.get("constraint_mode", "medium") or "medium").strip().lower()
            if constraint_mode not in {"hard", "medium", "soft"}:
                constraint_mode = "medium"
            fit_result = self.fit_service.evaluate_jobs(
                cv_path=Path(PROJECT_ROOT / "input" / "full_doc_stlye.txt"),
                stage="applied" if pipeline_type == "applied_jobs" else "all",
                limit=int(crawl_config.get("max_jobs", 200)),
                constraint_mode=constraint_mode,
            )
            run_id = self.repo.insert_run(
                schedule_id=schedule_id,
                action_type="evaluate_fit",
                status="success",
                detail=fit_result,
                triggered_by=triggered_by,
            )
            actions.append({"run_id": run_id, "status": "success", "fit_result": fit_result})

        if pipeline_type in {"filtered_jobs", "applied_jobs"} and bool(schedule.get("auto_generate_cv", 0)):
            actions.append(
                self.trigger_action(
                    action_type="generate_cv",
                    args=[],
                    schedule_id=schedule_id,
                    triggered_by=triggered_by,
                )
            )

        self.logger.info(
            "Schedule pipeline done | schedule_id=%s override_id=%s actions=%s triggered_by=%s",
            schedule_id,
            override_id,
            len(actions),
            triggered_by,
        )
        return {"schedule_id": schedule_id, "actions": actions, "override_id": override_id}

    def run_schedule_pipeline(self, schedule_id: int) -> dict[str, Any]:
        self.logger.info("Schedule pipeline start | schedule_id=%s", schedule_id)
        schedule = self.repo.get_schedule(schedule_id)
        if schedule is None:
            self.logger.error("Schedule pipeline failed | schedule_id=%s not found", schedule_id)
            raise ValueError(f"Schedule not found: {schedule_id}")
        occurrence_at = self._current_occurrence_at(schedule)
        pending_override = self.repo.get_pending_override_for_occurrence(schedule_id, occurrence_at)
        if pending_override is not None:
            self.logger.info(
                "Scheduled pipeline skipped due to single-occurrence override | schedule_id=%s override_id=%s occurrence_at=%s",
                schedule_id,
                pending_override.get("id"),
                occurrence_at,
            )
            return {
                "schedule_id": schedule_id,
                "status": "skipped",
                "reason": "single_occurrence_overridden",
                "override_id": pending_override.get("id"),
                "occurrence_at": occurrence_at,
            }
        return self._run_schedule_pipeline_core(
            schedule_id=schedule_id,
            schedule=schedule,
            triggered_by="scheduler",
        )

    def run_schedule_override(self, override_id: int) -> dict[str, Any]:
        override = self.repo.get_schedule_override(override_id)
        if override is None:
            raise ValueError(f"Override not found: {override_id}")
        if str(override.get("status") or "").strip().lower() != "pending":
            return {
                "schedule_id": override.get("schedule_id"),
                "override_id": override_id,
                "status": override.get("status"),
            }
        schedule_id = int(override.get("schedule_id") or 0)
        schedule = self.repo.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError(f"Schedule not found: {schedule_id}")
        merged_schedule = self._coerce_schedule_for_override(
            schedule,
            dict(override.get("override_payload_json") or {}),
        )
        try:
            result = self._run_schedule_pipeline_core(
                schedule_id=schedule_id,
                schedule=merged_schedule,
                triggered_by="scheduler_override",
                override_id=override_id,
            )
        except Exception as exc:
            self.repo.fail_schedule_override(
                override_id,
                result={
                    "schedule_id": schedule_id,
                    "override_id": override_id,
                    "status": "failed",
                    "error": str(exc),
                },
            )
            raise
        self.repo.complete_schedule_override(override_id, result=result)
        return result

    def linkedin_easy_apply(self, *, job_ids: list[int], cv_paths: list[str], dry_run: bool = False) -> dict[str, Any]:
        cleaned_job_ids = [int(x) for x in job_ids if int(x) > 0]
        cleaned_cv_paths = [str(x).strip() for x in cv_paths if str(x).strip()]
        if not cleaned_job_ids:
            raise ValueError("job_ids is required")
        if not cleaned_cv_paths:
            raise ValueError("cv_paths is required")
        invalid_cv_paths = [x for x in cleaned_cv_paths if not self._is_uploadable_cv_path(x)]
        if invalid_cv_paths:
            raise ValueError("Apply requires an uploadable CV file (.pdf/.docx/.doc/.rtf). Generate CV first.")
        cv_files = [Path(p).name for p in cleaned_cv_paths]
        self.logger.info(
            "LinkedIn apply validate ok | jobs=%s cvs=%s sample_job_ids=%s sample_cv_files=%s",
            len(cleaned_job_ids),
            len(cleaned_cv_paths),
            cleaned_job_ids[:10],
            cv_files[:5],
        )

        cmd = [
            str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
            str(PROJECT_ROOT / "scripts" / "python" / "linkedin_easy_apply.py"),
            "--db-path",
            str(PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"),
            "--job-ids",
            ",".join(str(x) for x in cleaned_job_ids),
            "--cv-paths",
            ",".join(cleaned_cv_paths),
        ]
        keep_browser_open_env = str(os.getenv("LINKEDIN_KEEP_BROWSER_OPEN", "0") or "").strip().lower()
        if keep_browser_open_env in {"1", "true", "yes", "on"}:
            cmd.append("--keep-browser-open")
        allow_fallback_env = str(os.getenv("LINKEDIN_ALLOW_PLAYWRIGHT_LAUNCH", "1") or "").strip().lower()
        if allow_fallback_env not in {"0", "false", "no", "off"}:
            cmd.append("--allow-playwright-launch")
        if dry_run:
            cmd.append("--dry-run")
        self.logger.info(
            "LinkedIn apply start | jobs=%s cvs=%s dry_run=%s cmd=%s",
            len(cleaned_job_ids),
            len(cleaned_cv_paths),
            dry_run,
            cmd,
        )
        started = time.perf_counter()
        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=self._clean_python_env(),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status = "success" if completed.returncode == 0 else "failed"
        detail = {
            "cmd": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-16000:],
            "stderr": completed.stderr[-16000:],
        }
        run_id = self.repo.insert_run(
            schedule_id=None,
            action_type="linkedin_easy_apply",
            status=status,
            detail=detail,
            triggered_by="manual_api",
        )
        self.logger.info(
            "LinkedIn apply done | status=%s run_id=%s returncode=%s elapsed_ms=%s stdout_len=%s stderr_len=%s",
            status,
            run_id,
            completed.returncode,
            elapsed_ms,
            len(completed.stdout or ""),
            len(completed.stderr or ""),
        )
        for trace_line in self._read_apply_trace_upload_events(limit=10):
            self.logger.info("LinkedIn apply upload trace | %s", trace_line)
        if status == "failed":
            stderr_text = str(completed.stderr or "")
            if "Please run the following command to download new browsers" in stderr_text or "playwright install" in stderr_text:
                hint = (
                    "Playwright browser runtime is missing. Run: "
                    f"'{(PROJECT_ROOT / '.venv' / 'Scripts' / 'python.exe')} -m playwright install chromium'"
                )
                self.logger.error(
                    "LinkedIn apply failed | run_id=%s returncode=%s reason=playwright_browser_missing",
                    run_id,
                    completed.returncode,
                )
                raise ValueError(hint)
            if "Cannot connect to existing Chrome via CDP" in stderr_text:
                hint = (
                    "Cannot connect to Chrome CDP. Either: "
                    "1) open Chrome with '--remote-debugging-port=9222', "
                    "or 2) set LINKEDIN_ALLOW_PLAYWRIGHT_LAUNCH=1 to allow fallback launch."
                )
                self.logger.error(
                    "LinkedIn apply failed | run_id=%s returncode=%s reason=cdp_connect_failed",
                    run_id,
                    completed.returncode,
                )
                raise ValueError(hint)
            if "LinkedIn login required in .pw-profile" in stderr_text:
                hint = (
                    "LinkedIn login required. Open Chrome with profile folder "
                    f"'{(PROJECT_ROOT / '.pw-profile').resolve()}' and sign in once, then retry Apply."
                )
                self.logger.error(
                    "LinkedIn apply failed | run_id=%s returncode=%s reason=linkedin_login_required",
                    run_id,
                    completed.returncode,
                )
                raise ValueError(hint)
            stdout_text = str(completed.stdout or "").strip()
            parsed_status = self._parse_apply_statuses(stdout_text)
            if parsed_status:
                self.logger.error(
                    "LinkedIn apply failed | run_id=%s returncode=%s statuses=%s stdout_tail=%s",
                    run_id,
                    completed.returncode,
                    parsed_status.get("statuses"),
                    stdout_text[-1200:],
                )
                return {
                    "ok": False,
                    "run_id": run_id,
                    "returncode": completed.returncode,
                    "statuses": parsed_status.get("statuses", []),
                    "diagnostics": parsed_status.get("diagnostics", []),
                    **detail,
                }
            self.logger.error(
                "LinkedIn apply failed | run_id=%s returncode=%s stdout_tail=%s stderr_tail=%s",
                run_id,
                completed.returncode,
                completed.stdout[-1200:],
                completed.stderr[-1200:],
            )
            raise ValueError(f"LinkedIn apply failed: returncode={completed.returncode}")
        return {"ok": True, "run_id": run_id, **detail}

    @staticmethod
    def _parse_apply_statuses(stdout_text: str) -> dict[str, Any] | None:
        raw = str(stdout_text or "").strip()
        if not raw:
            return None
        try:
            payload = ast.literal_eval(raw)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        statuses: list[str] = []
        diagnostics: list[str] = []
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            st = str(item.get("status") or "").strip()
            if st:
                statuses.append(st)
            diag = item.get("diagnostic")
            if isinstance(diag, dict):
                url = str(diag.get("url") or "").strip()
                has_easy = bool(diag.get("has_easy_apply_button"))
                has_apply = bool(diag.get("has_apply_button"))
                login_wall = bool(diag.get("login_wall"))
                diagnostics.append(f"url={url} easy={has_easy} apply={has_apply} login_wall={login_wall}")
            debug_artifacts = item.get("debug_artifacts")
            if isinstance(debug_artifacts, dict):
                shot = str(debug_artifacts.get("screenshot_path") or "").strip()
                html = str(debug_artifacts.get("html_path") or "").strip()
                if shot:
                    diagnostics.append(f"screenshot={shot}")
                if html:
                    diagnostics.append(f"html={html}")
            mode = str(item.get("runtime_mode") or "").strip()
            if mode:
                diagnostics.append(f"runtime_mode={mode}")
            external_apply_url = str(item.get("external_apply_url") or "").strip()
            if external_apply_url:
                diagnostics.append(f"external_apply_url={external_apply_url}")
            external_apply_runtime = str(item.get("external_apply_runtime") or "").strip()
            if external_apply_runtime:
                diagnostics.append(f"external_apply_runtime={external_apply_runtime}")
            trace_log_path = str(item.get("trace_log_path") or "").strip()
            if trace_log_path:
                diagnostics.append(f"trace_log={trace_log_path}")
        unique_statuses = sorted(set(statuses))
        if not unique_statuses:
            return None
        return {"statuses": unique_statuses, "diagnostics": diagnostics[:8]}
