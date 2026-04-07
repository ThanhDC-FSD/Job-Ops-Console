from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.repositories.database import Database

APP_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


class AnalyticsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def company_repost_stats(
        self,
        *,
        country: str,
        countries: list[str],
        company: str,
        min_reposts: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []

        if countries:
            country_parts = []
            for c in countries:
                country_parts.append("LOWER(COALESCE(jp.location, '')) LIKE ?")
                params.append(f"%{c.lower()}%")
            where.append("(" + " OR ".join(country_parts) + ")")
        elif country:
            where.append("LOWER(COALESCE(jp.location, '')) LIKE ?")
            params.append(f"%{country.lower()}%")
        if company:
            where.append("LOWER(COALESCE(jp.company, '')) LIKE ?")
            params.append(f"%{company.lower()}%")

        where_clause = " AND ".join(where)

        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    COALESCE(jp.company, 'Unknown') AS company,
                    COALESCE(jp.location, '') AS location,
                    jp.role_signature,
                    COUNT(DISTINCT jo.crawl_date) AS repost_count,
                    MIN(jo.crawl_date) AS first_repost_date,
                    MAX(jo.crawl_date) AS last_repost_date,
                    CAST(julianday(MAX(jo.crawl_date)) - julianday(MIN(jo.crawl_date)) + 1 AS INT) AS duration_days,
                    COUNT(DISTINCT jp.id) AS distinct_job_posts
                FROM job_posts jp
                JOIN job_observations jo ON jo.job_post_id = jp.id
                WHERE {where_clause}
                GROUP BY COALESCE(jp.company, 'Unknown'), COALESCE(jp.location, ''), jp.role_signature
                HAVING COUNT(DISTINCT jo.crawl_date) >= ?
                ORDER BY repost_count DESC, duration_days DESC
                LIMIT ?
                """,
                [*params, max(1, min_reposts), max(1, limit)],
            ).fetchall()
            return [dict(r) for r in rows]

    def country_overview(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  CASE
                    WHEN TRIM(COALESCE(jle.normalized_country, '')) <> '' THEN TRIM(jle.normalized_country)
                    WHEN INSTR(COALESCE(job_posts.location, ''), ',') > 0 THEN TRIM(SUBSTR(job_posts.location, INSTR(job_posts.location, ',') + 1))
                    ELSE TRIM(COALESCE(job_posts.location, ''))
                  END AS country,
                  COUNT(*) AS jobs,
                  SUM(CASE WHEN EXISTS (
                    SELECT 1 FROM job_application_tracking jat
                    WHERE jat.job_post_id = job_posts.id AND jat.is_applied = 1
                  ) THEN 1 ELSE 0 END) AS applied_jobs
                FROM job_posts
                LEFT JOIN job_location_enrichment jle ON jle.job_post_id = job_posts.id
                WHERE TRIM(
                  CASE
                    WHEN TRIM(COALESCE(jle.normalized_country, '')) <> '' THEN TRIM(jle.normalized_country)
                    WHEN INSTR(COALESCE(job_posts.location, ''), ',') > 0 THEN TRIM(SUBSTR(job_posts.location, INSTR(job_posts.location, ',') + 1))
                    ELSE TRIM(COALESCE(job_posts.location, ''))
                  END
                ) <> ''
                GROUP BY country
                ORDER BY jobs DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _coerce_iso_date(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            if "T" in raw:
                raw = raw.split("T", 1)[0]
            elif " " in raw:
                raw = raw.split(" ", 1)[0]
            try:
                return datetime.fromisoformat(raw).date().isoformat()
            except ValueError:
                return ""
        if parsed.tzinfo is not None:
            return parsed.astimezone(APP_TIMEZONE).date().isoformat()
        return parsed.date().isoformat()

    @classmethod
    def _build_daily_series(cls, rows: list[Any]) -> list[dict[str, Any]]:
        daily_map: dict[str, int] = {}
        for row in rows:
            day_key = cls._coerce_iso_date(row["apply_date"])
            if not day_key:
                continue
            daily_map[day_key] = daily_map.get(day_key, 0) + int(row["applied_count"] or 0)
        if not daily_map:
            return []
        cumulative = 0
        series: list[dict[str, Any]] = []
        start_date = datetime.fromisoformat(min(daily_map)).date()
        end_date = datetime.fromisoformat(max(daily_map)).date()
        cursor = start_date
        while cursor <= end_date:
            day_key = cursor.isoformat()
            daily_count = int(daily_map.get(day_key, 0))
            cumulative += daily_count
            series.append(
                {
                    "apply_date": day_key,
                    "applied_count": daily_count,
                    "cumulative_count": cumulative,
                }
            )
            cursor += timedelta(days=1)
        return series

    @classmethod
    def _build_job_earliest_apply_series(cls, rows: list[Any]) -> list[dict[str, Any]]:
        earliest_by_job: dict[int, str] = {}
        for row in rows:
            try:
                job_post_id = int(row["job_post_id"])
            except Exception:
                continue
            day_key = cls._coerce_iso_date(row["apply_date"])
            if not day_key:
                continue
            current = earliest_by_job.get(job_post_id, "")
            if not current or day_key < current:
                earliest_by_job[job_post_id] = day_key
        daily_rows = [
            {"apply_date": apply_date, "applied_count": 1}
            for apply_date in earliest_by_job.values()
        ]
        return cls._build_daily_series(daily_rows)

    @classmethod
    def _build_tracker_snapshot_series(cls, rows: list[Any]) -> list[dict[str, Any]]:
        snapshot_map: dict[str, int] = {}
        for row in rows:
            day_key = cls._coerce_iso_date(row["apply_date"])
            if not day_key:
                continue
            snapshot_count = int(row["applied_count"] or 0)
            if snapshot_count <= 0:
                continue
            snapshot_map[day_key] = max(snapshot_map.get(day_key, 0), snapshot_count)
        if not snapshot_map:
            return []
        series: list[dict[str, Any]] = []
        prev_snapshot = 0
        for day_key in sorted(snapshot_map):
            snapshot_count = int(snapshot_map[day_key])
            daily_count = snapshot_count if not series else max(0, snapshot_count - prev_snapshot)
            series.append(
                {
                    "apply_date": day_key,
                    "applied_count": daily_count,
                    "cumulative_count": snapshot_count,
                }
            )
            prev_snapshot = snapshot_count
        return series

    @classmethod
    def _merge_cumulative_series(
        cls,
        explicit_series: list[dict[str, Any]],
        snapshot_series: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not explicit_series and not snapshot_series:
            return []

        explicit_map = {
            str(point["apply_date"]): int(point["cumulative_count"] or 0)
            for point in explicit_series
            if cls._coerce_iso_date(point.get("apply_date"))
        }
        snapshot_map = {
            str(point["apply_date"]): int(point["cumulative_count"] or 0)
            for point in snapshot_series
            if cls._coerce_iso_date(point.get("apply_date"))
        }
        all_dates = sorted(
            {
                *[cls._coerce_iso_date(point.get("apply_date")) for point in explicit_series],
                *[cls._coerce_iso_date(point.get("apply_date")) for point in snapshot_series],
            }
            - {""}
        )
        if not all_dates:
            return []

        start_date = datetime.fromisoformat(all_dates[0]).date()
        end_date = datetime.fromisoformat(all_dates[-1]).date()
        cursor = start_date
        explicit_cumulative = 0
        snapshot_cumulative = 0
        merged_cumulative = 0
        merged: list[dict[str, Any]] = []
        while cursor <= end_date:
            day_key = cursor.isoformat()
            explicit_cumulative = max(explicit_cumulative, int(explicit_map.get(day_key, explicit_cumulative)))
            snapshot_cumulative = max(snapshot_cumulative, int(snapshot_map.get(day_key, snapshot_cumulative)))
            next_cumulative = max(explicit_cumulative, snapshot_cumulative)
            merged.append(
                {
                    "apply_date": day_key,
                    "applied_count": max(0, next_cumulative - merged_cumulative),
                    "cumulative_count": next_cumulative,
                }
            )
            merged_cumulative = next_cumulative
            cursor += timedelta(days=1)
        return merged

    def applied_jobs_trend(self, source: str = "auto") -> dict[str, Any]:
        selected_source = str(source or "auto").strip().lower()
        if selected_source not in {"auto", "hybrid", "events", "tracking", "tracker_runs"}:
            selected_source = "auto"

        with self.db.connect() as conn:
            hybrid_rows = conn.execute(
                """
                WITH explicit_applies AS (
                  SELECT
                    job_post_id,
                    COALESCE(applied_first_seen_at, created_at) AS apply_date
                  FROM job_application_tracking
                  WHERE COALESCE(is_applied, 0) = 1
                    AND TRIM(COALESCE(applied_first_seen_at, created_at, '')) <> ''
                  UNION
                  SELECT
                    job_post_id,
                    apply_date
                  FROM job_apply_events
                  WHERE TRIM(COALESCE(apply_date, '')) <> ''
                )
                SELECT
                  job_post_id,
                  apply_date
                FROM explicit_applies
                """
            ).fetchall()
            event_rows = conn.execute(
                """
                SELECT apply_date, COUNT(*) AS applied_count
                FROM job_apply_events
                WHERE TRIM(COALESCE(apply_date, '')) <> ''
                GROUP BY apply_date
                ORDER BY apply_date ASC
                """
            ).fetchall()
            tracking_rows = conn.execute(
                """
                SELECT COALESCE(applied_first_seen_at, created_at) AS apply_date, COUNT(*) AS applied_count
                FROM job_application_tracking
                WHERE COALESCE(is_applied, 0) = 1
                  AND TRIM(COALESCE(applied_first_seen_at, created_at, '')) <> ''
                GROUP BY COALESCE(applied_first_seen_at, created_at)
                ORDER BY COALESCE(applied_first_seen_at, created_at) ASC
                """
            ).fetchall()
            tracker_run_rows = conn.execute(
                """
                SELECT crawl_date AS apply_date, MAX(total_jobs) AS applied_count
                FROM crawl_runs
                WHERE LOWER(COALESCE(mode, '')) IN ('tracker_applied_http', 'tracker_applied')
                GROUP BY crawl_date
                ORDER BY crawl_date ASC
                """
            ).fetchall()
            tracker_run_latest = conn.execute(
                """
                SELECT crawl_date AS apply_date, total_jobs AS applied_count
                FROM crawl_runs
                WHERE LOWER(COALESCE(mode, '')) IN ('tracker_applied_http', 'tracker_applied')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            payload_keyword_jobs = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM job_posts
                WHERE LOWER(COALESCE(latest_payload_json, '')) LIKE '%apply%'
                """
            ).fetchone()
            tracking_total = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM job_application_tracking
                WHERE COALESCE(is_applied, 0) = 1
                """
            ).fetchone()
            tracking_manual_total = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM job_application_tracking
                WHERE COALESCE(is_applied, 0) = 1
                  AND LOWER(COALESCE(applied_source, '')) = 'manual'
                """
            ).fetchone()
            apply_event_total = conn.execute("SELECT COUNT(*) AS c FROM job_apply_events").fetchone()
            apply_event_manual_total = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM job_apply_events
                WHERE LOWER(COALESCE(source, '')) = 'manual'
                """
            ).fetchone()

        explicit_hybrid_series = self._build_job_earliest_apply_series(hybrid_rows)
        event_series = self._build_daily_series(event_rows)
        tracking_series = self._build_daily_series(tracking_rows)
        tracker_runs_series = self._build_tracker_snapshot_series(tracker_run_rows)
        hybrid_series = explicit_hybrid_series
        source_map = {
            "hybrid": hybrid_series,
            "events": event_series,
            "tracking": tracking_series,
            "tracker_runs": tracker_runs_series,
        }

        if selected_source == "auto":
            hybrid_latest = hybrid_series[-1]["cumulative_count"] if hybrid_series else 0
            tracking_latest = tracking_series[-1]["cumulative_count"] if tracking_series else 0
            event_latest = event_series[-1]["cumulative_count"] if event_series else 0
            tracker_latest = tracker_runs_series[-1]["cumulative_count"] if tracker_runs_series else 0
            if hybrid_latest > 0:
                selected_source = "hybrid"
            elif tracker_latest > max(tracking_latest, event_latest):
                selected_source = "tracker_runs"
            elif tracking_latest >= event_latest and tracking_latest > 0:
                selected_source = "tracking"
            elif event_latest > 0:
                selected_source = "events"
            else:
                selected_source = "tracker_runs"

        series = source_map.get(selected_source, [])
        return {
            "source_used": selected_source,
            "series": series,
            "latest_point": series[-1] if series else None,
            "source_totals": {
                "hybrid_tracking_union": hybrid_series[-1]["cumulative_count"] if hybrid_series else 0,
                "hybrid_explicit_only": explicit_hybrid_series[-1]["cumulative_count"] if explicit_hybrid_series else 0,
                "job_apply_events": int(apply_event_total["c"] or 0) if apply_event_total else 0,
                "job_apply_events_manual": int(apply_event_manual_total["c"] or 0) if apply_event_manual_total else 0,
                "tracking_is_applied": int(tracking_total["c"] or 0) if tracking_total else 0,
                "tracking_manual": int(tracking_manual_total["c"] or 0) if tracking_manual_total else 0,
                "tracker_runs_latest_total_jobs": int(tracker_run_latest["applied_count"] or 0) if tracker_run_latest else 0,
                "payload_keyword_jobs": int(payload_keyword_jobs["c"] or 0) if payload_keyword_jobs else 0,
            },
        }

    def applied_jobs_trend_debug(self) -> dict[str, Any]:
        trend = self.applied_jobs_trend(source="auto")
        with self.db.connect() as conn:
            tracker_runs = conn.execute(
                """
                SELECT id, crawl_date, mode, total_jobs, started_at
                FROM crawl_runs
                WHERE LOWER(COALESCE(mode, '')) IN ('tracker_applied_http', 'tracker_applied')
                ORDER BY id DESC
                LIMIT 20
                """
            ).fetchall()
            tracking_rows = conn.execute(
                """
                SELECT job_post_id, is_applied, applied_source, applied_last_seen_date, has_cv, response_status
                FROM job_application_tracking
                WHERE COALESCE(is_applied, 0) = 1
                ORDER BY job_post_id DESC
                LIMIT 50
                """
            ).fetchall()
        return {
            **trend,
            "tracker_runs_recent": [dict(row) for row in tracker_runs],
            "tracking_rows": [dict(row) for row in tracking_rows],
        }
