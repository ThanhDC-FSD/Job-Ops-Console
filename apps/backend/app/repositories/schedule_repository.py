from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.repositories.database import Database


class ScheduleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_schedules(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            sql = "SELECT * FROM automation_schedules ORDER BY id DESC"
            if limit:
                sql += " LIMIT ?"
                rows = conn.execute(sql, (int(limit),)).fetchall()
            else:
                rows = conn.execute(sql).fetchall()
        pending_overrides = {
            (int(item.get("schedule_id") or 0), str(item.get("target_occurrence_at") or "")): item
            for item in self.list_pending_overrides()
        }
        items = []
        for row in rows:
            item = dict(row)
            item["crawl_config_json"] = json.loads(item.get("crawl_config_json") or "{}")
            next_run_at = self._next_run_at(item.get("cron_expr"), item.get("timezone"))
            item["next_run_at"] = next_run_at
            override = pending_overrides.get((int(item["id"]), self._normalize_iso_minute(next_run_at)))
            item["occurrence_override"] = override
            if override:
                item["next_run_display_at"] = self._effective_next_run_at(
                    cron_expr=item.get("cron_expr"),
                    timezone_name=item.get("timezone"),
                    series_next_run_at=next_run_at,
                    override_run_at=override.get("override_run_at"),
                )
            else:
                item["next_run_display_at"] = next_run_at
            items.append(item)
        return items

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO automation_schedules (
                  name, enabled, cron_expr, timezone, pipeline_type, crawl_config_json,
                  auto_eval_fit, fit_cv_profile, auto_generate_cv, fit_threshold, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"],
                    int(payload.get("enabled", True)),
                    payload["cron_expr"],
                    payload.get("timezone", "Asia/Ho_Chi_Minh"),
                    payload["pipeline_type"],
                    json.dumps(payload.get("crawl_config", {}), ensure_ascii=False),
                    int(payload.get("auto_eval_fit", True)),
                    payload.get("fit_cv_profile", "full_doc_stlye"),
                    int(payload.get("auto_generate_cv", False)),
                    float(payload.get("fit_threshold", 75)),
                    now,
                    now,
                ),
            )
            new_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM automation_schedules WHERE id = ?", (new_id,)).fetchone()
        item = dict(row)
        item["crawl_config_json"] = json.loads(item.get("crawl_config_json") or "{}")
        return item

    def update_schedule(self, schedule_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            exists = conn.execute("SELECT id FROM automation_schedules WHERE id = ?", (schedule_id,)).fetchone()
            if exists is None:
                return None
            conn.execute(
                """
                UPDATE automation_schedules
                SET name = ?, enabled = ?, cron_expr = ?, timezone = ?, crawl_config_json = ?, auto_eval_fit = ?,
                    fit_cv_profile = ?, auto_generate_cv = ?, fit_threshold = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.get("name", "New Schedule"),
                    int(payload.get("enabled", True)),
                    payload["cron_expr"],
                    payload.get("timezone", "Asia/Ho_Chi_Minh"),
                    json.dumps(payload.get("crawl_config", {}), ensure_ascii=False),
                    int(payload.get("auto_eval_fit", True)),
                    payload.get("fit_cv_profile", "full_doc_stlye"),
                    int(payload.get("auto_generate_cv", False)),
                    float(payload.get("fit_threshold", 75)),
                    now,
                    schedule_id,
                ),
            )
            row = conn.execute("SELECT * FROM automation_schedules WHERE id = ?", (schedule_id,)).fetchone()
        item = dict(row)
        item["crawl_config_json"] = json.loads(item.get("crawl_config_json") or "{}")
        return item

    def list_pending_overrides(self, schedule_id: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = ["pending"]
        where = "WHERE status = ?"
        if schedule_id is not None:
            where += " AND schedule_id = ?"
            params.append(int(schedule_id))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM automation_schedule_overrides
                {where}
                ORDER BY override_run_at ASC, id ASC
                """,
                tuple(params),
            ).fetchall()
        return [self._decode_override_row(row) for row in rows]

    def get_schedule_override(self, override_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM automation_schedule_overrides WHERE id = ?",
                (int(override_id),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_override_row(row)

    def get_pending_override_for_occurrence(self, schedule_id: int, occurrence_at: str | None) -> dict[str, Any] | None:
        normalized = self._normalize_iso_minute(occurrence_at)
        if not normalized:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM automation_schedule_overrides
                WHERE schedule_id = ?
                  AND status = 'pending'
                  AND target_occurrence_at = ?
                LIMIT 1
                """,
                (int(schedule_id), normalized),
            ).fetchone()
        if row is None:
            return None
        return self._decode_override_row(row)

    def upsert_schedule_override(
        self,
        *,
        schedule_id: int,
        target_occurrence_at: str,
        override_run_at: str,
        override_payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        normalized_target = self._normalize_iso_minute(target_occurrence_at)
        normalized_run = self._normalize_iso_minute(override_run_at)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_schedule_overrides (
                  schedule_id, target_occurrence_at, override_run_at, override_payload_json,
                  status, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', '{}', ?, ?)
                ON CONFLICT(schedule_id, target_occurrence_at)
                DO UPDATE SET
                  override_run_at = excluded.override_run_at,
                  override_payload_json = excluded.override_payload_json,
                  status = 'pending',
                  result_json = '{}',
                  updated_at = excluded.updated_at
                """,
                (
                    int(schedule_id),
                    normalized_target,
                    normalized_run,
                    json.dumps(override_payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM automation_schedule_overrides
                WHERE schedule_id = ?
                  AND target_occurrence_at = ?
                LIMIT 1
                """,
                (int(schedule_id), normalized_target),
            ).fetchone()
        return self._decode_override_row(row)

    def cancel_schedule_override(self, override_id: int) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE automation_schedule_overrides
                SET status = 'cancelled',
                    updated_at = ?
                WHERE id = ?
                """,
                (now, int(override_id)),
            )
            row = conn.execute(
                "SELECT * FROM automation_schedule_overrides WHERE id = ?",
                (int(override_id),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_override_row(row)

    def complete_schedule_override(self, override_id: int, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE automation_schedule_overrides
                SET status = 'completed',
                    result_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(result or {}, ensure_ascii=False), now, int(override_id)),
            )
            row = conn.execute(
                "SELECT * FROM automation_schedule_overrides WHERE id = ?",
                (int(override_id),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_override_row(row)

    def fail_schedule_override(self, override_id: int, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE automation_schedule_overrides
                SET status = 'failed',
                    result_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(result or {}, ensure_ascii=False), now, int(override_id)),
            )
            row = conn.execute(
                "SELECT * FROM automation_schedule_overrides WHERE id = ?",
                (int(override_id),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_override_row(row)

    def insert_run(self, *, schedule_id: int | None, action_type: str, status: str, detail: dict[str, Any], triggered_by: str) -> int:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO automation_runs (schedule_id, triggered_by, action_type, status, detail_json, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (schedule_id, triggered_by, action_type, status, json.dumps(detail, ensure_ascii=False), now, now),
            )
            return int(cur.lastrowid)

    def create_run(
        self,
        *,
        schedule_id: int | None,
        action_type: str,
        triggered_by: str,
        status: str = "running",
        detail: dict[str, Any] | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO automation_runs (schedule_id, triggered_by, action_type, status, detail_json, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (schedule_id, triggered_by, action_type, status, json.dumps(detail or {}, ensure_ascii=False), now, None),
            )
            return int(cur.lastrowid)

    def update_run(
        self,
        run_id: int,
        *,
        status: str | None = None,
        detail: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> None:
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if detail is not None:
            sets.append("detail_json = ?")
            params.append(json.dumps(detail, ensure_ascii=False))
        if finished:
            sets.append("finished_at = ?")
            params.append(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        if not sets:
            return
        params.append(run_id)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE automation_runs SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM automation_runs ORDER BY id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["detail_json"] = json.loads(item.get("detail_json") or "{}")
            items.append(item)
        return items

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM automation_runs WHERE id = ?",
                (int(run_id),),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["detail_json"] = json.loads(item.get("detail_json") or "{}")
        return item

    def list_pending_scheduled_runs(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM automation_runs
                WHERE status = 'pending'
                ORDER BY id ASC
                """
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["detail_json"] = json.loads(item.get("detail_json") or "{}")
            scheduled_for = str((item.get("detail_json") or {}).get("scheduled_for") or "").strip()
            if scheduled_for:
                items.append(item)
        return items

    def get_schedule(self, schedule_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM automation_schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["crawl_config_json"] = json.loads(item.get("crawl_config_json") or "{}")
        return item

    def delete_schedule(self, schedule_id: int) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM automation_schedules WHERE id = ?", (schedule_id,))
            return int(cur.rowcount or 0) > 0

    def has_active_runs(self) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM automation_runs WHERE status = 'running' LIMIT 1"
            ).fetchone()
        return row is not None

    def has_active_run(self, *, action_type: str | None = None) -> bool:
        if not action_type:
            return self.has_active_runs()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM automation_runs WHERE status = 'running' AND action_type = ? LIMIT 1",
                (action_type,),
            ).fetchone()
        return row is not None

    def list_schedule_jobs(self, job_type: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if job_type:
            where = "WHERE job_type = ?"
            params.append(job_type)
        with self.db.connect() as conn:
            sql = f"SELECT * FROM schedule_jobs {where} ORDER BY id DESC"
            if limit:
                sql += " LIMIT ?"
                params.append(int(limit))
            rows = conn.execute(sql, tuple(params)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = json.loads(item.get("payload_json") or "{}")
            item["next_run_at"] = self._next_run_at(item.get("cron_expr"), item.get("timezone"))
            items.append(item)
        return items

    @staticmethod
    def _next_run_at(cron_expr: str | None, timezone_name: str | None) -> str:
        expr = (cron_expr or "").strip()
        if not expr:
            return ""
        zone = timezone.utc
        try:
            if timezone_name:
                zone = ZoneInfo(timezone_name)
        except Exception:
            zone = timezone.utc
        try:
            trigger = CronTrigger.from_crontab(expr, timezone=zone)
            dt = trigger.get_next_fire_time(None, datetime.now(zone))
            return dt.isoformat() if dt else ""
        except Exception:
            return ""

    @staticmethod
    def _next_run_after(cron_expr: str | None, timezone_name: str | None, after_value: str | None) -> str:
        expr = (cron_expr or "").strip()
        after_iso = str(after_value or "").strip()
        if not expr or not after_iso:
            return ""
        zone = timezone.utc
        try:
            if timezone_name:
                zone = ZoneInfo(timezone_name)
        except Exception:
            zone = timezone.utc
        try:
            after_dt = datetime.fromisoformat(after_iso)
            if after_dt.tzinfo is None:
                after_dt = after_dt.replace(tzinfo=timezone.utc)
            after_dt = after_dt.astimezone(zone)
            trigger = CronTrigger.from_crontab(expr, timezone=zone)
            dt = trigger.get_next_fire_time(after_dt, after_dt)
            return dt.isoformat() if dt else ""
        except Exception:
            return ""

    @classmethod
    def _effective_next_run_at(
        cls,
        *,
        cron_expr: str | None,
        timezone_name: str | None,
        series_next_run_at: str | None,
        override_run_at: str | None,
    ) -> str:
        series_iso = cls._normalize_iso_minute(series_next_run_at)
        override_iso = cls._normalize_iso_minute(override_run_at)
        if not override_iso:
            return series_iso
        next_after_series = cls._normalize_iso_minute(
            cls._next_run_after(cron_expr, timezone_name, series_iso),
        )
        if not next_after_series:
            return override_iso
        return min(override_iso, next_after_series)

    @staticmethod
    def _normalize_iso_minute(value: str | None) -> str:
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
    def _decode_override_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["override_payload_json"] = json.loads(item.get("override_payload_json") or "{}")
        item["result_json"] = json.loads(item.get("result_json") or "{}")
        return item

    def create_schedule_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO schedule_jobs (
                  job_type, name, enabled, cron_expr, timezone, payload_json, last_enqueued_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["job_type"],
                    payload["name"],
                    int(payload.get("enabled", True)),
                    payload.get("cron_expr", ""),
                    payload.get("timezone", "Asia/Ho_Chi_Minh"),
                    json.dumps(payload.get("payload", {}), ensure_ascii=False),
                    None,
                    now,
                    now,
                ),
            )
            job_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM schedule_jobs WHERE id = ?", (job_id,)).fetchone()
        item = dict(row)
        item["payload_json"] = json.loads(item.get("payload_json") or "{}")
        return item

    def get_schedule_job(self, job_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM schedule_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload_json"] = json.loads(item.get("payload_json") or "{}")
        return item

    def mark_schedule_job_enqueued(self, job_id: int) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE schedule_jobs SET last_enqueued_at = ?, updated_at = ? WHERE id = ?",
                (now, now, job_id),
            )

    def update_schedule_job(self, job_id: int, *, cron_expr: str | None = None, timezone_name: str | None = None) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if cron_expr is not None:
            sets.append("cron_expr = ?")
            params.append(cron_expr)
        if timezone_name is not None:
            sets.append("timezone = ?")
            params.append(timezone_name)
        if not sets:
            return self.get_schedule_job(job_id)
        params.append(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        params.append(job_id)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE schedule_jobs SET {', '.join(sets)}, updated_at = ? WHERE id = ?", tuple(params))
            row = conn.execute("SELECT * FROM schedule_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload_json"] = json.loads(item.get("payload_json") or "{}")
        item["next_run_at"] = self._next_run_at(item.get("cron_expr"), item.get("timezone"))
        return item

    def find_queue_item(self, queue_key: str, statuses: tuple[str, ...] = ("pending", "running")) -> dict[str, Any] | None:
        if not queue_key:
            return None
        placeholders = ",".join("?" for _ in statuses)
        params: list[Any] = [queue_key, *statuses]
        with self.db.connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM schedule_queue
                WHERE queue_key = ?
                  AND status IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload_json"] = json.loads(item.get("payload_json") or "{}")
        item["result_json"] = json.loads(item.get("result_json") or "{}")
        return item

    def enqueue_queue_item(
        self,
        *,
        job_id: int | None,
        job_type: str,
        queue_key: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO schedule_queue (
                  job_id, job_type, queue_key, status, payload_json, attempts, max_attempts,
                  run_after, started_at, finished_at, error_text, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, 0, ?, ?, NULL, NULL, '', '{}', ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    queue_key,
                    json.dumps(payload, ensure_ascii=False),
                    max(1, int(max_attempts)),
                    now,
                    now,
                    now,
                ),
            )
            queue_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM schedule_queue WHERE id = ?", (queue_id,)).fetchone()
        item = dict(row)
        item["payload_json"] = json.loads(item.get("payload_json") or "{}")
        item["result_json"] = json.loads(item.get("result_json") or "{}")
        return item

    def claim_next_queue_item(self, *, job_type: str) -> dict[str, Any] | None:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        now = now_dt.isoformat()
        stale_minutes = int(os.getenv("QUEUE_STALE_MINUTES", "60") or "60")
        stale_cutoff = now_dt
        if stale_minutes > 0:
            stale_cutoff = now_dt - timedelta(minutes=stale_minutes)
        with self.db.connect() as conn:
            running_rows = conn.execute(
                """
                SELECT id, started_at, updated_at
                FROM schedule_queue
                WHERE job_type = ?
                  AND status = 'running'
                """,
                (job_type,),
            ).fetchall()
            if running_rows:
                has_active = False
                for row in running_rows:
                    last_seen_raw = row["updated_at"] or row["started_at"]
                    last_seen_at = None
                    if last_seen_raw:
                        try:
                            last_seen_at = datetime.fromisoformat(str(last_seen_raw))
                            if last_seen_at.tzinfo is None:
                                last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
                        except Exception:
                            last_seen_at = None
                    if stale_minutes > 0 and last_seen_at and last_seen_at < stale_cutoff:
                        conn.execute(
                            """
                            UPDATE schedule_queue
                            SET status = 'failed',
                                error_text = ?,
                                finished_at = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            ("stale_running_timeout", now, now, int(row["id"])),
                        )
                    else:
                        has_active = True
                if has_active:
                    return None
            row = conn.execute(
                """
                SELECT *
                FROM schedule_queue
                WHERE job_type = ?
                  AND status = 'pending'
                  AND (run_after IS NULL OR run_after <= ?)
                ORDER BY created_at, id
                LIMIT 1
                """,
                (job_type, now),
            ).fetchone()
            if row is None:
                return None
            queue_id = int(row["id"])
            conn.execute(
                """
                UPDATE schedule_queue
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, queue_id),
            )
            claimed = conn.execute("SELECT * FROM schedule_queue WHERE id = ?", (queue_id,)).fetchone()
        item = dict(claimed)
        item["payload_json"] = json.loads(item.get("payload_json") or "{}")
        item["result_json"] = json.loads(item.get("result_json") or "{}")
        return item

    def touch_queue_item(self, queue_id: int, *, status_detail: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            if status_detail is None:
                conn.execute(
                    """
                    UPDATE schedule_queue
                    SET updated_at = ?
                    WHERE id = ?
                    """,
                    (now, queue_id),
                )
                return
            row = conn.execute(
                "SELECT result_json FROM schedule_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if row is None:
                return
            current = json.loads(row.get("result_json") or "{}")
            progress = dict(current.get("progress") or {})
            progress.update(status_detail)
            progress["updated_at"] = now
            current["progress"] = progress
            conn.execute(
                """
                UPDATE schedule_queue
                SET result_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(current, ensure_ascii=False), now, queue_id),
            )

    def complete_queue_item(self, queue_id: int, result: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE schedule_queue
                SET status = 'completed',
                    result_json = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(result or {}, ensure_ascii=False), now, now, queue_id),
            )

    def fail_queue_item(self, queue_id: int, *, error_text: str, retry_seconds: int = 0) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT attempts, max_attempts FROM schedule_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"] or 0)
            max_attempts = int(row["max_attempts"] or 0)
            should_retry = attempts < max_attempts
            status = "pending" if should_retry else "failed"
            run_after = now
            if should_retry and retry_seconds > 0:
                next_time = datetime.now(timezone.utc).replace(microsecond=0).timestamp() + int(retry_seconds)
                run_after = datetime.fromtimestamp(next_time, tz=timezone.utc).replace(microsecond=0).isoformat()
            conn.execute(
                """
                UPDATE schedule_queue
                SET status = ?,
                    error_text = ?,
                    run_after = ?,
                    finished_at = CASE WHEN ? = 'failed' THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, error_text[:2000], run_after, status, now, now, queue_id),
            )

    def list_queue_items(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(max(1, int(limit)))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT q.*, j.name AS job_name
                FROM schedule_queue q
                LEFT JOIN schedule_jobs j ON j.id = q.job_id
                {where}
                ORDER BY q.id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = json.loads(item.get("payload_json") or "{}")
            item["result_json"] = json.loads(item.get("result_json") or "{}")
            items.append(item)
        return items
