from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter, sleep
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import PROJECT_ROOT
from app.repositories.database import Database
from app.services.location_normalizer import canonicalize_region

CONTINENT_ORDER = {
    "North America": 1,
    "South America": 2,
    "Europe": 3,
    "Middle East": 4,
    "Africa": 5,
    "Asia": 6,
    "Oceania": 7,
    "Other": 99,
}

REGION_TO_CONTINENT = {
    "North America": "North America",
    "South America": "South America",
    "Western Europe": "Europe",
    "European Union": "Europe",
    "Eastern Europe": "Europe",
    "Middle East": "Middle East",
    "Africa": "Africa",
    "Northeast Asia": "Asia",
    "Southeast Asia": "Asia",
    "South Asia": "Asia",
    "Central Asia": "Asia",
    "East Asia": "Asia",
    "Oceania": "Oceania",
}

REGION_WITHIN_CONTINENT_ORDER = {
    "North America": 1,
    "South America": 1,
    "Western Europe": 1,
    "European Union": 2,
    "Eastern Europe": 3,
    "Middle East": 1,
    "Africa": 1,
    "Northeast Asia": 1,
    "East Asia": 2,
    "Southeast Asia": 3,
    "South Asia": 4,
    "Central Asia": 5,
    "Oceania": 1,
    "Other": 99,
}

TITLE_STOP_TOKENS = {
    "senior",
    "junior",
    "lead",
    "principal",
    "software",
    "engineer",
    "developer",
    "remote",
    "fully",
    "part",
    "time",
}

PROGRAMMING_GROUP_ORDER = {
    "Frontend (FE)": 1,
    "Backend (BE)": 2,
    "Mobile": 3,
    "Data/AI": 4,
    "DevOps/Cloud": 5,
    "Database": 6,
    "Other": 99,
}

PROGRAMMING_GROUP_RULES = [
    ("Frontend (FE)", {"javascript", "typescript", "react", "vue", "angular", "next.js", "nextjs", "html", "css", "sass", "scss"}),
    ("Backend (BE)", {"python", "java", "c#", "csharp", "node.js", "nodejs", "php", "go", "golang", "ruby", "rust", "scala", "kotlin", "asp.net", ".net"}),
    ("Mobile", {"swift", "objective-c", "objective c", "android", "ios", "flutter", "react native", "xamarin"}),
    ("Data/AI", {"r", "matlab", "pytorch", "tensorflow", "spark", "hadoop", "numpy", "pandas"}),
    ("DevOps/Cloud", {"docker", "kubernetes", "terraform", "ansible", "bash", "shell", "aws", "azure", "gcp", "jenkins"}),
    ("Database", {"sql", "postgresql", "mysql", "mongodb", "redis", "oracle", "sqlite", "elasticsearch"}),
]


def _region_sort_key(region: str) -> tuple[int, int, str]:
    canonical = canonicalize_region(region)
    continent = REGION_TO_CONTINENT.get(canonical, "Other")
    return (
        CONTINENT_ORDER.get(continent, 99),
        REGION_WITHIN_CONTINENT_ORDER.get(canonical, 99),
        canonical.lower(),
    )


def _programming_group(language: str) -> str:
    token = str(language or "").strip().lower()
    for group_name, keywords in PROGRAMMING_GROUP_RULES:
        if token in keywords:
            return group_name
    return "Other"


def _programming_language_sort_key(language: str) -> tuple[int, str]:
    group_name = _programming_group(language)
    return (PROGRAMMING_GROUP_ORDER.get(group_name, 99), str(language or "").lower())


def _clean_unknown_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "-", "unknown", "n/a", "na", "none", "null"} else text


def _parse_payload_job_type_tags(payload_json: str) -> list[str]:
    raw = str(payload_json or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    tags = payload.get("job_type_tags")
    if not isinstance(tags, list):
        return []
    return [str(tag or "").strip() for tag in tags if str(tag or "").strip()]


def _infer_work_model_from_tags(tags: list[str]) -> str:
    normalized = {str(tag or "").strip().lower() for tag in tags}
    if "remote" in normalized:
        return "remote"
    if "hybrid" in normalized:
        return "hybrid"
    if "on-site" in normalized or "onsite" in normalized or "on site" in normalized:
        return "on-site"
    return ""


def _infer_employment_type_from_tags(tags: list[str]) -> str:
    normalized = {str(tag or "").strip().lower() for tag in tags}
    for token in ("full-time", "part-time", "contract", "temporary", "internship", "volunteer"):
        if token in normalized:
            return token
    return ""


def _title_tokens(title: str) -> set[str]:
    normalized = re.sub(r"\([^)]*\)", " ", title or "")
    tokens = set(re.findall(r"[a-z0-9+#.-]{2,}", normalized.lower()))
    return {t for t in tokens if t not in TITLE_STOP_TOKENS}


def _title_overlap(a: str, b: str) -> int:
    ta = _title_tokens(a)
    tb = _title_tokens(b)
    if not ta or not tb:
        return 0
    return len(ta.intersection(tb))


def _extract_linkedin_job_id(raw_url: str) -> int | None:
    url = str(raw_url or "").strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if "linkedin.com" not in host:
        return None
    query = parse_qs(parsed.query or "")
    current_job_values = query.get("currentJobId") or []
    if current_job_values:
        try:
            job_id = int(str(current_job_values[0]).strip())
            if job_id > 0:
                return job_id
        except (TypeError, ValueError):
            pass
    match = re.search(r"/jobs/view/(?:[^/?#]*-)?(\d+)(?:/)?", parsed.path or "")
    if not match:
        return None
    try:
        job_id = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return job_id if job_id > 0 else None


def _canonical_linkedin_job_url(raw_url: str, raw_url_final: str = "", linkedin_job_id: Any = None) -> str:
    for candidate in (
        _extract_linkedin_job_id(raw_url_final),
        _extract_linkedin_job_id(raw_url),
        linkedin_job_id,
    ):
        try:
            job_id = int(candidate)
        except (TypeError, ValueError):
            continue
        if job_id > 0:
            return f"https://www.linkedin.com/jobs/view/{job_id}/"
    return str(raw_url_final or raw_url or "").strip()


def _parse_posted_age_days(posted_time: str) -> int | None:
    if not posted_time:
        return None
    text = str(posted_time).strip().lower().replace("reposted", "").strip()
    if text in {"just now", "today"}:
        return 0
    if text == "yesterday":
        return 1

    plus_match = re.search(r"(\d+)\+\s*days?\s*ago", text)
    if plus_match:
        return int(plus_match.group(1))

    match = re.search(r"(\d+)\s*(hour|day|week|month|year)s?\s*ago", text)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)
    if unit == "hour":
        return 0
    if unit == "day":
        return value
    if unit == "week":
        return value * 7
    if unit == "month":
        return value * 30
    if unit == "year":
        return value * 365
    return None


def _estimate_linkedin_posted_date(posted_time: str, last_seen_date: str, first_seen_date: str) -> str:
    days = _parse_posted_age_days(posted_time or "")
    base = (last_seen_date or first_seen_date or "").strip()
    if not base:
        return ""
    try:
        base_date = datetime.fromisoformat(base).date()
    except ValueError:
        return ""
    if days is None:
        return base_date.isoformat()
    return (base_date - timedelta(days=days)).isoformat()


def _estimate_posted_time_label(posted_date: str) -> str:
    raw = str(posted_date or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw).date()
    except ValueError:
        return ""
    days = max(0, (datetime.now().date() - dt).days)
    if days == 0:
        return "today (estimated)"
    if days == 1:
        return "1 day ago (estimated)"
    return f"{days} days ago (estimated)"


def _looks_like_fallback_jd(text: str) -> bool:
    sample = str(text or "").strip().lower()
    if not sample:
        return True
    return sample.startswith("job context (fallback jd):") or sample.startswith("fallback jd:")


def _source_uses_full_page_text(source: str) -> bool:
    return "full_page_text" in str(source or "").strip().lower()


def _stringify_payload_candidate(raw: Any) -> str:
    if raw in (None, ""):
        return ""
    if isinstance(raw, str):
        return str(raw).strip()
    if isinstance(raw, list):
        parts = [_stringify_payload_candidate(item) for item in raw]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(raw, dict):
        parts: list[str] = []
        for nested_key, nested_value in raw.items():
            rendered = _stringify_payload_candidate(nested_value)
            if not rendered:
                continue
            label = str(nested_key or "").strip()
            if label and rendered.lower() != label.lower():
                separator = ":\n" if "\n" in rendered else ": "
                parts.append(f"{label}{separator}{rendered}")
            else:
                parts.append(rendered)
        return "\n\n".join(part for part in parts if part).strip()
    return str(raw).strip()


def _best_payload_jd_text(payload_json: Any) -> tuple[str, str]:
    try:
        payload = json.loads(str(payload_json or "{}"))
    except Exception:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    candidates: list[tuple[int, int, str, str]] = []
    for key, priority in (
        ("jd", 0),
        ("about_job", 1),
        ("about_job_sections", 2),
        ("description", 3),
        ("jobDescription", 4),
        ("job_description", 5),
        ("descriptionText", 6),
        ("requirements", 7),
        ("details", 8),
        ("content", 9),
        ("summary", 10),
        ("skills", 11),
        ("technologies", 12),
        ("meta_description", 13),
        ("og_description", 14),
        ("twitter_description", 15),
        ("full_page_text", 99),
    ):
        value = _stringify_payload_candidate(payload.get(key))
        if not value:
            continue
        if key == "full_page_text":
            lowered = value.lower()
            stop_markers = (
                "people also viewed",
                "jobs you may be interested in",
                "similar jobs",
                "recommended for you",
            )
            cut_positions = [lowered.find(marker) for marker in stop_markers if lowered.find(marker) >= 0]
            if cut_positions:
                value = value[: min(cut_positions)].strip()
        if not value or _looks_like_fallback_jd(value):
            continue
        candidates.append((priority, -len(value), key, value))
    if not candidates:
        return "", ""
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, key, value = candidates[0]
    source = str(payload.get("jd_source", "") or "").strip() or f"payload_fallback:{key}"
    return value, source


def _date_key(value: str) -> tuple[int, str]:
    if not value:
        return (0, "")
    return (1, value)


def _detect_language(text: str) -> str:
    sample = (text or "").strip()
    if not sample:
        return "other"
    # Vietnamese diacritics
    if re.search(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", sample.lower()):
        return "vi"
    if re.search(r"[a-zA-Z]", sample):
        return "en"
    return "other"


class JobRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._maintenance_last_run_at = 0.0
        self._maintenance_interval_seconds = 90.0

    @staticmethod
    def _sanitize_jd_text(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        for marker in (
            "Note: Original JD text was unavailable from source at crawl time.",
            "Note: Original JD text was unavailable at crawl time.",
            "- Note: Original JD text is missing in database for this job.",
        ):
            text = text.replace(marker, "")
        lines = [line.rstrip() for line in text.split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines).strip()

    def _run_request_maintenance_if_due(self, conn) -> None:
        now = perf_counter()
        if now - self._maintenance_last_run_at < self._maintenance_interval_seconds:
            return
        from app.repositories.meta_repository import MetaRepository

        try:
            MetaRepository._ensure_job_application_tracking_columns(conn)
            self._remove_closed_jobs_from_payload_text(conn)
            self._remove_closed_jobs_from_failed_apply_runs(conn)
            self._remove_closed_jobs_from_apply_debug_artifacts(conn)
            self._sync_manual_review_from_failed_apply_runs(conn)
            self._sync_manual_review_from_sync_log_file(conn)
            self._maintenance_last_run_at = now
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise

    @staticmethod
    def _company_under_review_exists_sql(job_alias: str = "jp", tracking_alias: str = "jat") -> str:
        return f"""
            EXISTS (
              SELECT 1
              FROM job_posts jp_review
              JOIN job_application_tracking jat_review ON jat_review.job_post_id = jp_review.id
              WHERE LOWER(TRIM(COALESCE(jp_review.company, ''))) = LOWER(TRIM(COALESCE({job_alias}.company, '')))
                AND jp_review.id <> {job_alias}.id
                AND COALESCE(jat_review.is_applied, 0) = 1
                AND LOWER(TRIM(COALESCE(jat_review.response_status, ''))) NOT IN ('rejected', 'declined', 'not_selected', 'withdrawn', 'closed')
            )
        """

    @classmethod
    def _effective_priority_flag_sql(cls, job_alias: str = "jp", tracking_alias: str = "jat", company_alias: str = "cp") -> str:
        inferred_company_review = cls._company_under_review_exists_sql(job_alias=job_alias, tracking_alias=tracking_alias)
        return f"""
            CASE
              WHEN TRIM(COALESCE({tracking_alias}.priority_flag, '')) <> '' THEN COALESCE({tracking_alias}.priority_flag, '')
              WHEN TRIM(COALESCE({company_alias}.priority_flag, '')) <> '' THEN COALESCE({company_alias}.priority_flag, '')
              WHEN COALESCE({tracking_alias}.is_applied, 0) = 0 AND {inferred_company_review} THEN 'company_under_review'
              ELSE ''
            END
        """

    @classmethod
    def _effective_priority_note_sql(cls, job_alias: str = "jp", tracking_alias: str = "jat", company_alias: str = "cp") -> str:
        inferred_company_review = cls._company_under_review_exists_sql(job_alias=job_alias, tracking_alias=tracking_alias)
        return f"""
            CASE
              WHEN TRIM(COALESCE({tracking_alias}.priority_flag, '')) <> '' THEN COALESCE({tracking_alias}.priority_note, '')
              WHEN TRIM(COALESCE({company_alias}.priority_flag, '')) <> '' THEN COALESCE({company_alias}.priority_note, '')
              WHEN COALESCE({tracking_alias}.is_applied, 0) = 0 AND {inferred_company_review}
                THEN COALESCE(NULLIF(TRIM(COALESCE({company_alias}.priority_note, '')), ''), 'Another application at this company is already under review.')
              ELSE ''
            END
        """

    @classmethod
    def _list_jobs_sort_sql(cls, sort_by: str, *, effective_priority_sql: str | None = None) -> str:
        key = str(sort_by or "").strip().lower()
        effective_priority_sql = effective_priority_sql or cls._effective_priority_flag_sql(
            job_alias="jp",
            tracking_alias="jat",
            company_alias="cp",
        )
        priority_manual_sql = f"""
            CASE
              WHEN LOWER(TRIM(COALESCE(({effective_priority_sql}), ''))) IN
                ('manual_only', 'company_under_review', 'onsite_only', 'full_time_only', 'part_time_only', 'contract_only', 'internship_only')
              THEN 1 ELSE 0
            END
        """
        priority_low_or_closed_sql = f"""
            CASE
              WHEN LOWER(TRIM(COALESCE(({effective_priority_sql}), ''))) IN ('low_priority', 'closed_no_longer_accepting')
              THEN 1 ELSE 0
            END
        """
        if key == "last_seen_desc":
            date_sql = "COALESCE(jp.last_seen_date, '') DESC, jp.id DESC"
        elif key == "last_seen_asc":
            date_sql = "COALESCE(jp.last_seen_date, '') ASC, jp.id ASC"
        elif key == "posted_date_asc":
            date_sql = "COALESCE(jp.latest_posted_time, '') ASC, jp.id ASC"
        else:
            date_sql = "COALESCE(jp.latest_posted_time, '') DESC, jp.id DESC"
        return f"{priority_manual_sql} ASC, {priority_low_or_closed_sql} ASC, {date_sql}"

    @staticmethod
    def _normalize_priority_flag(value: str) -> str:
        flag = str(value or "").strip().lower()
        if flag in {
            "low_priority",
            "manual_only",
            "company_under_review",
            "closed_no_longer_accepting",
            "onsite_only",
            "full_time_only",
            "part_time_only",
            "contract_only",
            "internship_only",
        }:
            return flag
        return ""

    @staticmethod
    def _priority_sort_bucket(item: dict[str, Any]) -> tuple[int, int]:
        flag = str(item.get("effective_priority_flag", "") or "").strip().lower()
        is_manual_only = 1 if flag in {
            "manual_only",
            "company_under_review",
            "onsite_only",
            "full_time_only",
            "part_time_only",
            "contract_only",
            "internship_only",
        } else 0
        is_low = 1 if flag == "low_priority" else 0
        is_closed = 1 if flag == "closed_no_longer_accepting" else 0
        return (is_manual_only, is_low + is_closed)

    @staticmethod
    def _delete_job_rows(conn, job_ids: set[int] | list[int]) -> int:
        ids = sorted({int(x) for x in job_ids if int(x) > 0})
        if not ids:
            return 0
        placeholders = ",".join(["?"] * len(ids))
        conn.execute(
            f"""
            UPDATE job_observations
            SET duplicate_of_job_post_id = NULL
            WHERE duplicate_of_job_post_id IN ({placeholders})
            """,
            ids,
        )
        cur = conn.execute(
            f"""
            DELETE FROM job_posts
            WHERE id IN ({placeholders})
            """,
            ids,
        )
        return int(cur.rowcount or 0)

    @staticmethod
    def _coerce_iso_date(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if "T" in raw:
            raw = raw.split("T", 1)[0]
        elif " " in raw:
            raw = raw.split(" ", 1)[0]
        try:
            return datetime.fromisoformat(raw).date().isoformat()
        except ValueError:
            return ""

    @classmethod
    def _build_daily_series(cls, rows: list[Any]) -> list[dict[str, Any]]:
        cumulative = 0
        daily_map: dict[str, int] = {}
        for row in rows:
            day_key = cls._coerce_iso_date(row["apply_date"])
            if not day_key:
                continue
            daily_map[day_key] = daily_map.get(day_key, 0) + int(row["applied_count"] or 0)
        if not daily_map:
            return []
        applied_series: list[dict[str, Any]] = []
        start_date = datetime.fromisoformat(min(daily_map)).date()
        end_date = datetime.fromisoformat(max(daily_map)).date()
        cursor = start_date
        while cursor <= end_date:
            day_key = cursor.isoformat()
            daily_count = int(daily_map.get(day_key, 0))
            cumulative += daily_count
            applied_series.append(
                {
                    "apply_date": day_key,
                    "applied_count": daily_count,
                    "cumulative_count": cumulative,
                }
            )
            cursor += timedelta(days=1)
        return applied_series

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
        all_dates = sorted(
            {
                *[cls._coerce_iso_date(point.get("apply_date")) for point in explicit_series],
                *[cls._coerce_iso_date(point.get("apply_date")) for point in snapshot_series],
            }
            - {""}
        )
        if not all_dates:
            return []
        explicit_map = {
            cls._coerce_iso_date(point.get("apply_date")): int(point.get("cumulative_count") or 0)
            for point in explicit_series
            if cls._coerce_iso_date(point.get("apply_date"))
        }
        snapshot_map = {
            cls._coerce_iso_date(point.get("apply_date")): int(point.get("cumulative_count") or 0)
            for point in snapshot_series
            if cls._coerce_iso_date(point.get("apply_date"))
        }
        cursor = datetime.fromisoformat(all_dates[0]).date()
        end_date = datetime.fromisoformat(all_dates[-1]).date()
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

    def fetch_dashboard(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            totals = conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM job_posts) AS total_jobs,
                  (SELECT COUNT(*) FROM job_application_tracking WHERE is_applied = 1) AS applied_jobs,
                  (SELECT COUNT(*) FROM job_application_tracking WHERE has_response = 1) AS responded_jobs,
                  (SELECT COUNT(*) FROM job_application_tracking WHERE has_cv = 1) AS cv_ready_jobs,
                  (SELECT COUNT(*) FROM crawl_runs) AS crawl_runs
                """
            ).fetchone()

            recent = conn.execute(
                """
                SELECT id, crawl_date, mode, total_jobs, started_at
                FROM crawl_runs
                ORDER BY id DESC
                LIMIT 10
                """
            ).fetchall()

            applied_daily = conn.execute(
                """
                WITH event_dates AS (
                  SELECT
                    job_post_id,
                    MIN(apply_date) AS apply_date
                  FROM job_apply_events
                  WHERE TRIM(COALESCE(apply_date, '')) <> ''
                  GROUP BY job_post_id
                )
                SELECT
                  COALESCE(ed.apply_date, jat.applied_last_seen_date) AS apply_date,
                  COUNT(*) AS applied_count
                FROM job_application_tracking jat
                LEFT JOIN event_dates ed ON ed.job_post_id = jat.job_post_id
                WHERE COALESCE(jat.is_applied, 0) = 1
                  AND TRIM(COALESCE(ed.apply_date, jat.applied_last_seen_date, '')) <> ''
                GROUP BY COALESCE(ed.apply_date, jat.applied_last_seen_date)
                ORDER BY COALESCE(ed.apply_date, jat.applied_last_seen_date) ASC
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

            applied_series = self._merge_cumulative_series(
                self._build_daily_series(applied_daily),
                self._build_tracker_snapshot_series(tracker_run_rows),
            )

            return {
                "total_jobs": int(totals["total_jobs"]),
                "applied_jobs": int(totals["applied_jobs"]),
                "responded_jobs": int(totals["responded_jobs"]),
                "cv_ready_jobs": int(totals["cv_ready_jobs"]),
                "crawl_runs": int(totals["crawl_runs"]),
                "applied_jobs_daily": applied_series,
                "recent_runs": [dict(r) for r in recent],
            }

    @staticmethod
    def _record_apply_event(conn, job_post_id: int, *, apply_date: str, source: str, note: str = "") -> None:
        event_date = str(apply_date or "").strip()
        event_source = str(source or "").strip()
        if not event_date or not event_source:
            return
        now = datetime.now().replace(microsecond=0).isoformat()
        conn.execute(
            """
            INSERT INTO job_apply_events (
              job_post_id,
              apply_date,
              source,
              note,
              created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_post_id, apply_date, source) DO UPDATE SET
              note = excluded.note
            """,
            (
                int(job_post_id),
                event_date,
                event_source,
                str(note or "").strip()[:1000],
                now,
            ),
        )

    def update_generated_cv_path(
        self,
        job_post_id: int,
        cv_source_path: str,
        *,
        portfolio_path: str = "",
        cover_letter_path: str = "",
        cover_letter_docx_path: str = "",
        cover_letter_pdf_path: str = "",
        generated_headline: str = "",
        generated_summary: str = "",
        generated_experience_summary: str = "",
        generated_llm_model: str = "",
        generated_llm_backend: str = "",
        generated_llm_usage_json: str = "",
    ) -> None:
        now = datetime.now().replace(microsecond=0).isoformat()
        folder_name = ""
        created_date = ""
        try:
            p = str(cv_source_path or "").strip()
            if p:
                folder_name = re.sub(r"[\\/]+", "/", p).split("/")[-2] if "/" in re.sub(r"[\\/]+", "/", p) else ""
                created_date = now[:10]
        except Exception:
            folder_name = ""
            created_date = now[:10]
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_application_tracking (
                  job_post_id,
                  has_cv,
                  cv_source_path,
                  portfolio_path,
                  cover_letter_path,
                  cover_letter_docx_path,
                  cover_letter_pdf_path,
                  generated_headline,
                  generated_summary,
                  generated_experience_summary,
                  generated_llm_model,
                  generated_llm_backend,
                  generated_llm_usage_json,
                  cv_folder_name,
                  cv_created_date,
                  cv_match_method,
                  cv_last_synced_at,
                  is_applied,
                  has_response,
                  created_at,
                  updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated', ?, 0, 0, ?, ?)
                ON CONFLICT(job_post_id) DO UPDATE SET
                  has_cv = 1,
                  cv_source_path = excluded.cv_source_path,
                  portfolio_path = excluded.portfolio_path,
                  cover_letter_path = excluded.cover_letter_path,
                  cover_letter_docx_path = excluded.cover_letter_docx_path,
                  cover_letter_pdf_path = excluded.cover_letter_pdf_path,
                  generated_headline = excluded.generated_headline,
                  generated_summary = excluded.generated_summary,
                  generated_experience_summary = excluded.generated_experience_summary,
                  generated_llm_model = excluded.generated_llm_model,
                  generated_llm_backend = excluded.generated_llm_backend,
                  generated_llm_usage_json = excluded.generated_llm_usage_json,
                  cv_folder_name = excluded.cv_folder_name,
                  cv_created_date = excluded.cv_created_date,
                  cv_match_method = 'generated',
                  cv_last_synced_at = excluded.cv_last_synced_at,
                  updated_at = excluded.updated_at
                """,
                (
                    int(job_post_id),
                    str(cv_source_path or ""),
                    str(portfolio_path or ""),
                    str(cover_letter_path or ""),
                    str(cover_letter_docx_path or ""),
                    str(cover_letter_pdf_path or ""),
                    str(generated_headline or "").strip()[:500],
                    str(generated_summary or "").strip()[:4000],
                    str(generated_experience_summary or "").strip()[:6000],
                    str(generated_llm_model or "").strip()[:200],
                    str(generated_llm_backend or "").strip()[:200],
                    str(generated_llm_usage_json or "").strip()[:12000],
                    folder_name,
                    created_date,
                    now,
                    now,
                      now,
                  ),
              )

    def next_generated_artifact_version(self, *, documents_date_folder: str, company_folder_name: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(version_number) AS max_version
                FROM job_generated_artifact_sets
                WHERE documents_date_folder = ? AND company_folder_name = ?
                """,
                (str(documents_date_folder or "").strip(), str(company_folder_name or "").strip()),
            ).fetchone()
        return int((row["max_version"] if row else 0) or 0) + 1

    def save_generated_artifact_set(
        self,
        *,
        job_post_id: int,
        documents_date_folder: str,
        company_folder_name: str,
        version_number: int,
        run_folder_name: str,
        output_slug: str,
        output_basename: str,
        cv_text: str,
        portfolio_text: str,
        cover_letter_text: str,
        fit_report_text: str,
        headline: str,
        summary: str,
        experience_summary: str,
        llm_model: str,
        llm_backend: str,
        llm_usage_json: str,
        source_kind: str = "rewrite",
    ) -> dict[str, Any]:
        now = datetime.now().replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_generated_artifact_sets (
                    job_post_id,
                    documents_date_folder,
                    company_folder_name,
                    version_number,
                    run_folder_name,
                    output_slug,
                    output_basename,
                    cv_text,
                    portfolio_text,
                    cover_letter_text,
                    fit_report_text,
                    headline,
                    summary,
                    experience_summary,
                    llm_model,
                    llm_backend,
                    llm_usage_json,
                    source_kind,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_post_id, documents_date_folder, company_folder_name, version_number) DO UPDATE SET
                    run_folder_name = excluded.run_folder_name,
                    output_slug = excluded.output_slug,
                    output_basename = excluded.output_basename,
                    cv_text = excluded.cv_text,
                    portfolio_text = excluded.portfolio_text,
                    cover_letter_text = excluded.cover_letter_text,
                    fit_report_text = excluded.fit_report_text,
                    headline = excluded.headline,
                    summary = excluded.summary,
                    experience_summary = excluded.experience_summary,
                    llm_model = excluded.llm_model,
                    llm_backend = excluded.llm_backend,
                    llm_usage_json = excluded.llm_usage_json,
                    source_kind = excluded.source_kind,
                    updated_at = excluded.updated_at
                """,
                (
                    int(job_post_id),
                    str(documents_date_folder or "").strip(),
                    str(company_folder_name or "").strip(),
                    int(version_number),
                    str(run_folder_name or "").strip(),
                    str(output_slug or "").strip(),
                    str(output_basename or "").strip(),
                    str(cv_text or ""),
                    str(portfolio_text or ""),
                    str(cover_letter_text or ""),
                    str(fit_report_text or ""),
                    str(headline or "").strip()[:500],
                    str(summary or "").strip()[:4000],
                    str(experience_summary or "").strip()[:6000],
                    str(llm_model or "").strip()[:200],
                    str(llm_backend or "").strip()[:200],
                    str(llm_usage_json or "").strip()[:12000],
                    str(source_kind or "rewrite").strip()[:100],
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM job_generated_artifact_sets
                WHERE job_post_id = ? AND documents_date_folder = ? AND company_folder_name = ? AND version_number = ?
                """,
                (
                    int(job_post_id),
                    str(documents_date_folder or "").strip(),
                    str(company_folder_name or "").strip(),
                    int(version_number),
                ),
            ).fetchone()
        return dict(row) if row is not None else {}

    def latest_generated_artifact_set(self, job_post_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM job_generated_artifact_sets
                WHERE job_post_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (int(job_post_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_generated_artifact_job_ids(
        self,
        *,
        limit: int = 100,
        only_missing: bool = True,
        recent_days: int = 0,
    ) -> list[int]:
        missing_clause = ""
        if only_missing:
            missing_clause = """
              AND (
                COALESCE(TRIM(jat.cv_source_path), '') = ''
                OR COALESCE(TRIM(jat.generated_headline), '') = ''
                OR COALESCE(TRIM(jat.generated_summary), '') = ''
                OR (
                  COALESCE(TRIM(latest.portfolio_text), '') <> ''
                  AND COALESCE(TRIM(jat.portfolio_path), '') = ''
                )
                OR (
                  COALESCE(TRIM(latest.cover_letter_text), '') <> ''
                  AND COALESCE(TRIM(jat.cover_letter_path), '') = ''
                  AND COALESCE(TRIM(jat.cover_letter_docx_path), '') = ''
                  AND COALESCE(TRIM(jat.cover_letter_pdf_path), '') = ''
                )
              )
            """
        recent_clause = ""
        params: list[Any] = []
        if int(recent_days or 0) > 0:
            recent_clause = """
              AND COALESCE(NULLIF(TRIM(jp.last_seen_date), ''), jp.first_seen_date) >= date('now', ?)
            """
            params.append(f"-{int(recent_days)} day")
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""
                WITH latest AS (
                  SELECT gas.*
                  FROM job_generated_artifact_sets gas
                  WHERE gas.id IN (
                    SELECT gas2.id
                    FROM job_generated_artifact_sets gas2
                    WHERE gas2.job_post_id = gas.job_post_id
                    ORDER BY gas2.updated_at DESC, gas2.id DESC
                    LIMIT 1
                  )
                )
                SELECT latest.job_post_id
                FROM latest
                JOIN job_posts jp ON jp.id = latest.job_post_id
                LEFT JOIN job_application_tracking jat ON jat.job_post_id = latest.job_post_id
                WHERE 1=1
                {missing_clause}
                {recent_clause}
                ORDER BY latest.updated_at DESC, latest.id DESC
                LIMIT ?
                """,
                (*params, int(limit)),
            ).fetchall()
        return [int(row["job_post_id"]) for row in rows]

    def mark_generated_artifact_materialized(self, artifact_id: int) -> None:
        now = datetime.now().replace(microsecond=0).isoformat()
        retry_delays = (0.0, 0.2, 0.6, 1.2)
        last_exc: sqlite3.OperationalError | None = None
        for delay in retry_delays:
            if delay:
                sleep(delay)
            try:
                with self.db.connect(timeout=2.0, busy_timeout_ms=2000) as conn:
                    conn.execute(
                        """
                        UPDATE job_generated_artifact_sets
                        SET materialized_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, now, int(artifact_id)),
                    )
                return
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if "locked" not in str(exc).lower():
                    raise
        if last_exc is not None:
            raise last_exc

    def update_manual_review_status(self, job_post_id: int, *, required: bool, note: str) -> None:
        now = datetime.now().replace(microsecond=0).isoformat()
        retry_delays = (0.0, 0.25, 0.75)
        last_exc: sqlite3.OperationalError | None = None
        for attempt, delay in enumerate(retry_delays, start=1):
            if delay > 0:
                sleep(delay)
            try:
                with self.db.connect(timeout=2.0, busy_timeout_ms=2000) as conn:
                    from app.repositories.meta_repository import MetaRepository

                    MetaRepository._ensure_job_application_tracking_columns(conn)
                    resolved_job_post_id = self._resolve_job_post_id(conn, job_post_id)
                    if resolved_job_post_id is None:
                        return
                    conn.execute(
                        """
                        INSERT INTO job_application_tracking (
                          job_post_id,
                          manual_review_required,
                          manual_review_note,
                          manual_review_updated_at,
                          created_at,
                          updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(job_post_id) DO UPDATE SET
                          manual_review_required = excluded.manual_review_required,
                          manual_review_note = excluded.manual_review_note,
                          manual_review_updated_at = excluded.manual_review_updated_at,
                          updated_at = excluded.updated_at
                        """,
                        (
                            resolved_job_post_id,
                            1 if required else 0,
                            str(note or "").strip(),
                            now,
                            now,
                            now,
                        ),
                    )
                    return
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if "locked" in str(exc).lower() and attempt < len(retry_delays):
                    continue
                raise
        if last_exc is not None:
            raise last_exc

    @staticmethod
    def _resolve_job_post_id(conn, raw_job_id: int) -> int | None:
        try:
            job_id = int(raw_job_id)
        except Exception:
            return None
        if job_id <= 0:
            return None

        row = conn.execute(
            """
            SELECT id
            FROM job_posts
            WHERE id = ?
               OR CAST(linkedin_job_id AS TEXT) = ?
            ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (job_id, str(job_id), job_id),
        ).fetchone()
        if row is None:
            return None
        return int(row["id"])

    def update_job_priority_status(self, job_post_id: int, *, priority_flag: str, note: str) -> None:
        flag = self._normalize_priority_flag(priority_flag)
        now = datetime.now().replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_application_tracking (
                  job_post_id,
                  priority_flag,
                  priority_note,
                  priority_updated_at,
                  created_at,
                  updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_post_id) DO UPDATE SET
                  priority_flag = excluded.priority_flag,
                  priority_note = excluded.priority_note,
                  priority_updated_at = excluded.priority_updated_at,
                  updated_at = excluded.updated_at
                """,
                (
                    int(job_post_id),
                    flag,
                    str(note or "").strip()[:1000] or None,
                    now if flag else None,
                    now,
                    now,
                ),
            )

    def update_company_priority_status(self, company_name: str, *, priority_flag: str, note: str) -> None:
        company = str(company_name or "").strip()
        if not company:
            return
        flag = self._normalize_priority_flag(priority_flag)
        now = datetime.now().replace(microsecond=0).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO company_preferences (
                  company_name,
                  priority_flag,
                  priority_note,
                  updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(company_name) DO UPDATE SET
                  priority_flag = excluded.priority_flag,
                  priority_note = excluded.priority_note,
                  updated_at = excluded.updated_at
                """,
                (
                    company,
                    flag,
                    str(note or "").strip()[:1000] or None,
                    now,
                ),
            )

    def mark_job_applied_manual(self, job_post_id: int, *, note: str = "") -> None:
        now = datetime.now().replace(microsecond=0)
        now_iso = now.isoformat()
        applied_date = now.date().isoformat()
        note_text = str(note or "").strip()[:1000]
        tracker_payload = {
            "source": "manual",
            "marked_at": now_iso,
        }
        if note_text:
            tracker_payload["note"] = note_text
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_application_tracking (
                  job_post_id,
                  is_applied,
                  applied_first_seen_at,
                  applied_source,
                  applied_last_seen_date,
                  tracker_payload_json,
                  manual_review_required,
                  manual_review_note,
                  manual_review_updated_at,
                  created_at,
                  updated_at
                ) VALUES (?, 1, ?, 'manual', ?, ?, 0, '', ?, ?, ?)
                ON CONFLICT(job_post_id) DO UPDATE SET
                  is_applied = 1,
                  applied_first_seen_at = COALESCE(job_application_tracking.applied_first_seen_at, excluded.applied_first_seen_at),
                  applied_source = 'manual',
                  applied_last_seen_date = excluded.applied_last_seen_date,
                  tracker_payload_json = excluded.tracker_payload_json,
                  manual_review_required = 0,
                  manual_review_note = '',
                  manual_review_updated_at = excluded.manual_review_updated_at,
                  updated_at = excluded.updated_at
                """,
                (
                    int(job_post_id),
                    now_iso,
                    applied_date,
                    json.dumps(tracker_payload, ensure_ascii=True),
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            self._record_apply_event(
                conn,
                int(job_post_id),
                apply_date=applied_date,
                source="manual",
                note=note_text,
            )

    @staticmethod
    def _extract_job_ids_from_apply_cmd(detail: dict[str, Any]) -> list[int]:
        cmd = detail.get("cmd")
        if not isinstance(cmd, list):
            return []
        for idx, token in enumerate(cmd):
            if str(token) != "--job-ids":
                continue
            if idx + 1 >= len(cmd):
                break
            raw = str(cmd[idx + 1] or "").strip()
            job_ids: list[int] = []
            for part in raw.split(","):
                try:
                    value = int(str(part).strip())
                except Exception:
                    continue
                if value > 0:
                    job_ids.append(value)
            return job_ids
        return []

    @staticmethod
    def _build_manual_review_notes_from_failed_apply(detail: dict[str, Any]) -> dict[int, str]:
        stdout_text = str(detail.get("stdout") or "").strip()
        stderr_text = str(detail.get("stderr") or "").strip()
        notes: dict[int, str] = {}
        generic_note = "Manual apply review needed: linkedin_easy_apply failed."
        lowered_stderr = stderr_text.lower()
        if "targetclosederror" in lowered_stderr or "target page, context or browser has been closed" in lowered_stderr:
            generic_note = "Manual apply review needed: browser closed during Playwright launch."
        elif "linkedin login required" in lowered_stderr:
            generic_note = "Manual apply review needed: LinkedIn login required in automation profile."
        elif "playwright install" in lowered_stderr:
            generic_note = "Manual apply review needed: Playwright browser runtime missing."

        if stdout_text:
            try:
                payload = json.loads(stdout_text.replace("'", '"'))
            except Exception:
                try:
                    import ast
                    payload = ast.literal_eval(stdout_text)
                except Exception:
                    payload = None
            if isinstance(payload, dict):
                for item in payload.get("results") or []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        job_id = int(item.get("job_id"))
                    except Exception:
                        continue
                    if job_id <= 0:
                        continue
                    status = str(item.get("status") or "").strip()
                    if status:
                        notes[job_id] = f"Manual apply review needed: linkedin_easy_apply failed with status {status}."
                    else:
                        notes[job_id] = generic_note

        if notes:
            return notes

        for job_id in JobRepository._extract_job_ids_from_apply_cmd(detail):
            notes[job_id] = generic_note
        return notes

    def _sync_manual_review_from_failed_apply_runs(self, conn) -> None:
        rows = conn.execute(
            """
            SELECT id, detail_json
            FROM automation_runs
            WHERE action_type = 'linkedin_easy_apply'
              AND status = 'failed'
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()
        if not rows:
            return

        now = datetime.now().replace(microsecond=0).isoformat()
        updates: dict[int, str] = {}
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except Exception:
                continue
            if not isinstance(detail, dict):
                continue
            for job_id, note in self._build_manual_review_notes_from_failed_apply(detail).items():
                if job_id > 0 and note and job_id not in updates:
                    updates[job_id] = note[:1000]

        if not updates:
            return

        for job_id, note in updates.items():
            exists = conn.execute("SELECT 1 FROM job_posts WHERE id = ? LIMIT 1", (job_id,)).fetchone()
            if exists is None:
                continue
            current = conn.execute(
                """
                SELECT
                  COALESCE(is_applied, 0) AS is_applied,
                  COALESCE(manual_review_required, 0) AS manual_review_required,
                  COALESCE(manual_review_note, '') AS manual_review_note
                FROM job_application_tracking
                WHERE job_post_id = ?
                """,
                (job_id,),
            ).fetchone()
            if current is not None and int(current["is_applied"] or 0) == 1:
                continue
            if (
                current is not None
                and int(current["manual_review_required"] or 0) == 1
                and str(current["manual_review_note"] or "").strip() == note
            ):
                continue
            conn.execute(
                """
                INSERT INTO job_application_tracking (
                  job_post_id,
                  manual_review_required,
                  manual_review_note,
                  manual_review_updated_at,
                  created_at,
                  updated_at
                ) VALUES (?, 1, ?, ?, ?, ?)
                ON CONFLICT(job_post_id) DO UPDATE SET
                  manual_review_required = 1,
                  manual_review_note = excluded.manual_review_note,
                  manual_review_updated_at = excluded.manual_review_updated_at,
                  updated_at = excluded.updated_at
                """,
                (job_id, note, now, now, now),
            )

    @staticmethod
    def _extract_closed_job_ids_from_failed_apply_detail(detail: dict[str, Any]) -> set[int]:
        stdout_text = str(detail.get("stdout") or "").strip()
        if not stdout_text:
            return set()
        try:
            import ast
            payload = ast.literal_eval(stdout_text)
        except Exception:
            return set()
        if not isinstance(payload, dict):
            return set()

        closed_ids: set[int] = set()
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            try:
                job_id = int(item.get("job_id"))
            except Exception:
                continue
            if job_id <= 0:
                continue
            artifacts = item.get("debug_artifacts")
            if not isinstance(artifacts, dict):
                continue
            html_path = str(artifacts.get("html_path") or "").strip()
            if not html_path:
                continue
            html_file = Path(html_path)
            if not html_file.is_absolute():
                html_file = (PROJECT_ROOT / html_file).resolve()
            if not html_file.exists() or not html_file.is_file():
                continue
            try:
                html_text = html_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "no longer accepting applications" in html_text.lower():
                closed_ids.add(job_id)
        return closed_ids

    def _remove_closed_jobs_from_failed_apply_runs(self, conn) -> None:
        rows = conn.execute(
            """
            SELECT id, detail_json
            FROM automation_runs
            WHERE action_type = 'linkedin_easy_apply'
              AND status = 'failed'
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
        if not rows:
            return

        closed_job_ids: set[int] = set()
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except Exception:
                continue
            if not isinstance(detail, dict):
                continue
            closed_job_ids.update(self._extract_closed_job_ids_from_failed_apply_detail(detail))

        if not closed_job_ids:
            return
        self._delete_job_rows(conn, closed_job_ids)

    def _remove_closed_jobs_from_apply_debug_artifacts(self, conn) -> None:
        debug_dir = (PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "apply_debug").resolve()
        if not debug_dir.exists() or not debug_dir.is_dir():
            return
        closed_job_ids: set[int] = set()
        candidates = sorted(debug_dir.glob("job_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
        for html_file in candidates:
            match = re.search(r"job_(\d+)_", html_file.name)
            if not match:
                continue
            try:
                job_id = int(match.group(1))
            except Exception:
                continue
            if job_id <= 0:
                continue
            try:
                html_text = html_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "no longer accepting applications" in html_text.lower():
                closed_job_ids.add(job_id)
        if not closed_job_ids:
            return
        self._delete_job_rows(conn, closed_job_ids)

    def _remove_closed_jobs_from_payload_text(self, conn) -> None:
        rows = conn.execute(
            """
            SELECT id, latest_payload_json
            FROM job_posts
            WHERE latest_payload_json IS NOT NULL
              AND TRIM(latest_payload_json) <> ''
            ORDER BY id DESC
            LIMIT 2000
            """
        ).fetchall()
        if not rows:
            return

        closed_job_ids: set[int] = set()
        for row in rows:
            try:
                job_id = int(row["id"])
            except Exception:
                continue
            if job_id <= 0:
                continue
            payload_text = str(row["latest_payload_json"] or "")
            if "no longer accepting applications" in payload_text.lower():
                closed_job_ids.add(job_id)

        if not closed_job_ids:
            return
        self._delete_job_rows(conn, closed_job_ids)

    @staticmethod
    def _build_manual_review_note_from_sync_record(record: dict[str, Any]) -> tuple[int, str] | None:
        log = record.get("log")
        if not isinstance(log, dict):
            return None
        payload = log.get("payload") if isinstance(log.get("payload"), dict) else {}
        try:
            job_id = int(payload.get("job_id"))
        except Exception:
            return None
        if job_id <= 0:
            return None

        event = str(log.get("event") or "").strip().lower()
        if event == "page.console":
            level = str(payload.get("level") or "").strip().lower()
            if level not in {"error", "assert"}:
                return None
            text = str(payload.get("text") or "").strip() or "unknown console error"
            location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
            location_url = str(location.get("url") or "").strip()
            note = f"Apply error from browser console: {text}"
            if location_url:
                note += f" | source={location_url}"
            return (job_id, note[:1000])

        if event == "page.request_failed":
            failure_text = str(payload.get("failure_text") or payload.get("error_text") or payload.get("text") or "").strip()
            request_url = str(payload.get("url") or payload.get("request_url") or "").strip()
            note = f"Apply error from network request failure: {failure_text or 'request failed'}"
            if request_url:
                note += f" | url={request_url}"
            return (job_id, note[:1000])

        if event == "page.error":
            text = str(payload.get("text") or payload.get("message") or "").strip()
            return (job_id, f"Apply error from page exception: {text or 'unhandled page error'}"[:1000])

        return None

    def _sync_manual_review_from_sync_log_file(self, conn) -> None:
        sync_log = (PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "linkedin_extension.sync.log").resolve()
        if not sync_log.exists() or not sync_log.is_file():
            return
        try:
            lines = sync_log.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return
        if not lines:
            return

        updates: dict[int, str] = {}
        for line in reversed(lines[-5000:]):
            raw = str(line or "").strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except Exception:
                continue
            sync_issue = self._build_manual_review_note_from_sync_record(record)
            if sync_issue is None:
                continue
            job_id, note = sync_issue
            if job_id > 0 and note and job_id not in updates:
                updates[job_id] = note

        if not updates:
            return

        now = datetime.now().replace(microsecond=0).isoformat()
        for job_id, note in updates.items():
            exists = conn.execute("SELECT 1 FROM job_posts WHERE id = ? LIMIT 1", (job_id,)).fetchone()
            if exists is None:
                continue
            current = conn.execute(
                """
                SELECT
                  COALESCE(is_applied, 0) AS is_applied,
                  COALESCE(manual_review_required, 0) AS manual_review_required,
                  COALESCE(manual_review_note, '') AS manual_review_note
                FROM job_application_tracking
                WHERE job_post_id = ?
                """,
                (job_id,),
            ).fetchone()
            if current is not None and int(current["is_applied"] or 0) == 1:
                continue
            if (
                current is not None
                and int(current["manual_review_required"] or 0) == 1
                and str(current["manual_review_note"] or "").strip() == note
            ):
                continue
            conn.execute(
                """
                INSERT INTO job_application_tracking (
                  job_post_id,
                  manual_review_required,
                  manual_review_note,
                  manual_review_updated_at,
                  created_at,
                  updated_at
                ) VALUES (?, 1, ?, ?, ?, ?)
                ON CONFLICT(job_post_id) DO UPDATE SET
                  manual_review_required = 1,
                  manual_review_note = excluded.manual_review_note,
                  manual_review_updated_at = excluded.manual_review_updated_at,
                  updated_at = excluded.updated_at
                """,
                (job_id, note, now, now, now),
            )

    def delete_jobs(self, job_post_ids: list[int]) -> int:
        ids = sorted({int(x) for x in job_post_ids if int(x) > 0})
        if not ids:
            return 0
        delays = (0.25, 0.5, 1.0, 1.5, 2.0)
        last_exc: Exception | None = None
        for index, delay in enumerate((0.0, *delays)):
            if delay > 0:
                time.sleep(delay)
            try:
                with self.db.connect(timeout=45.0, busy_timeout_ms=45000) as conn:
                    return self._delete_job_rows(conn, ids)
            except sqlite3.OperationalError as exc:
                last_exc = exc
                if "database is locked" not in str(exc).lower() or index == len(delays):
                    raise
        if last_exc is not None:
            raise last_exc
        return 0

    def list_jobs(
        self,
        *,
        stage: str,
        country: str,
        countries: list[str],
        regions: list[str],
        exclude_countries: list[str],
        languages: list[str],
        programming_languages: list[str],
        work_models: list[str],
        employment_types: list[str],
        easy_apply: int,
        constraint_mode: str,
        has_cv: int,
        apply_error: int,
        priority_flag: int,
        sort_by: str,
        posted_within_days: int,
        company: str,
        search: str,
        summary_only: bool,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        where = ["1=1"]
        params: list[Any] = []

        if has_cv in (0, 1):
            where.append("COALESCE(jat.has_cv, 0) = ?")
            params.append(int(has_cv))
        if apply_error in (0, 1):
            where.append("COALESCE(jat.manual_review_required, 0) = ?")
            params.append(int(apply_error))
        selected_countries = [str(c or "").strip() for c in countries if str(c or "").strip()]
        single_country = str(country or "").strip()
        if regions:
            region_parts = []
            for r in regions:
                normalized_region = canonicalize_region(r).lower()
                region_parts.append(
                    """
                    (
                      LOWER(COALESCE(jle.normalized_region, '')) = ?
                      OR LOWER(COALESCE(jle.normalized_country, '')) IN (
                        SELECT LOWER(normalized_country)
                        FROM geo_region_country_map
                        WHERE LOWER(normalized_region) = ?
                      )
                    )
                    """
                )
                params.append(normalized_region)
                params.append(normalized_region)
            where.append("(" + " OR ".join(region_parts) + ")")
        if exclude_countries:
            exc_parts = []
            for c in exclude_countries:
                exc_parts.append("LOWER(COALESCE(jle.normalized_country, '')) <> ?")
                params.append(c.lower())
            where.extend(exc_parts)

        if company:
            where.append("LOWER(COALESCE(jp.company, '')) LIKE ?")
            params.append(f"%{company.lower()}%")

        if search:
            where.append("(LOWER(COALESCE(jp.title, '')) LIKE ? OR LOWER(COALESCE(jp.company, '')) LIKE ?)")
            params.extend([f"%{search.lower()}%", f"%{search.lower()}%"])
        if work_models:
            parts = []
            for value in work_models:
                parts.append("LOWER(COALESCE(jp.normalized_work_model, '')) = ?")
                params.append(str(value or "").strip().lower())
            where.append("(" + " OR ".join(parts) + ")")
        if employment_types:
            parts = []
            for value in employment_types:
                parts.append("LOWER(COALESCE(jp.normalized_employment_type, '')) = ?")
                params.append(str(value or "").strip().lower())
            where.append("(" + " OR ".join(parts) + ")")
        if easy_apply in (0, 1):
            where.append("COALESCE(jp.normalized_easy_apply, 0) = ?")
            params.append(int(easy_apply))

        with self.db.connect() as conn:
            self._run_request_maintenance_if_due(conn)
            if selected_countries:
                region_rows = conn.execute(
                    """
                    SELECT DISTINCT LOWER(COALESCE(normalized_region, '')) AS region
                    FROM geo_region_country_map
                    WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                    UNION
                    SELECT DISTINCT LOWER(COALESCE(normalized_region, '')) AS region
                    FROM job_location_enrichment
                    WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                    """
                ).fetchall()
                known_regions = {str(r["region"]) for r in region_rows if str(r["region"]).strip()}
                country_parts = []
                for raw in selected_countries:
                    candidate_region = canonicalize_region(raw).lower()
                    if candidate_region in known_regions:
                        country_parts.append(
                            """
                            (
                              LOWER(COALESCE(jle.normalized_region, '')) = ?
                              OR LOWER(COALESCE(jle.normalized_country, '')) IN (
                                SELECT LOWER(normalized_country)
                                FROM geo_region_country_map
                                WHERE LOWER(normalized_region) = ?
                              )
                            )
                            """
                        )
                        params.append(candidate_region)
                        params.append(candidate_region)
                    else:
                        country_parts.append("LOWER(COALESCE(jle.normalized_country, '')) = ?")
                        params.append(raw.lower())
                if country_parts:
                    where.append("(" + " OR ".join(country_parts) + ")")
            elif single_country:
                country_as_region = canonicalize_region(single_country).lower()
                probe = conn.execute(
                    """
                    SELECT 1
                    FROM (
                      SELECT LOWER(COALESCE(normalized_region, '')) AS region
                      FROM geo_region_country_map
                      UNION
                      SELECT LOWER(COALESCE(normalized_region, '')) AS region
                      FROM job_location_enrichment
                    ) t
                    WHERE t.region = ?
                    LIMIT 1
                    """,
                    (country_as_region,),
                ).fetchone()
                if probe is not None:
                    where.append(
                        """
                        (
                          LOWER(COALESCE(jle.normalized_region, '')) = ?
                          OR LOWER(COALESCE(jle.normalized_country, '')) IN (
                            SELECT LOWER(normalized_country)
                            FROM geo_region_country_map
                            WHERE LOWER(normalized_region) = ?
                          )
                        )
                        """
                    )
                    params.append(country_as_region)
                    params.append(country_as_region)
                else:
                    where.append("LOWER(COALESCE(jle.normalized_country, '')) LIKE ?")
                    params.append(f"%{single_country.lower()}%")

            companies_under_review_cte = """
                WITH companies_under_review AS (
                  SELECT LOWER(TRIM(COALESCE(jp_review.company, ''))) AS company_key
                  FROM job_posts jp_review
                  JOIN job_application_tracking jat_review ON jat_review.job_post_id = jp_review.id
                  WHERE COALESCE(jat_review.is_applied, 0) = 1
                    AND LOWER(TRIM(COALESCE(jat_review.response_status, ''))) NOT IN ('rejected', 'declined', 'not_selected', 'withdrawn', 'closed')
                    AND TRIM(COALESCE(jp_review.company, '')) <> ''
                  GROUP BY LOWER(TRIM(COALESCE(jp_review.company, '')))
                ),
                apply_event_rollup AS (
                  SELECT
                    e.job_post_id,
                    MAX(COALESCE(e.apply_date, '')) AS latest_apply_date,
                    COUNT(*) AS event_count,
                    MAX(CASE WHEN LOWER(TRIM(COALESCE(e.source, ''))) = 'manual' THEN 1 ELSE 0 END) AS has_manual_event
                  FROM job_apply_events e
                  GROUP BY e.job_post_id
                )
            """
            effective_priority_flag_sql = """
                CASE
                  WHEN TRIM(COALESCE(jat.priority_flag, '')) <> '' THEN COALESCE(jat.priority_flag, '')
                  WHEN TRIM(COALESCE(cp.priority_flag, '')) <> '' THEN COALESCE(cp.priority_flag, '')
                  WHEN COALESCE(jat.is_applied, 0) = 0 AND cur.company_key IS NOT NULL THEN 'company_under_review'
                  ELSE ''
                END
            """
            effective_priority_note_sql = """
                CASE
                  WHEN TRIM(COALESCE(jat.priority_flag, '')) <> '' THEN COALESCE(jat.priority_note, '')
                  WHEN TRIM(COALESCE(cp.priority_flag, '')) <> '' THEN COALESCE(cp.priority_note, '')
                  WHEN COALESCE(jat.is_applied, 0) = 0 AND cur.company_key IS NOT NULL
                    THEN COALESCE(NULLIF(TRIM(COALESCE(cp.priority_note, '')), ''), 'Another application at this company is already under review.')
                  ELSE ''
                END
            """
            applied_evidence_sql = """
                (
                  TRIM(COALESCE(jat.applied_last_seen_date, '')) <> ''
                  OR TRIM(COALESCE(jat.applied_source, '')) <> ''
                  OR COALESCE(aer.event_count, 0) > 0
                )
            """
            if stage == "applied":
                where.append(applied_evidence_sql)
            elif stage == "filtered":
                where.append(f"NOT {applied_evidence_sql}")
            if stage == "filtered":
                where.append(
                    f"""
                    LOWER(TRIM(COALESCE(({effective_priority_flag_sql}), ''))) NOT IN (
                      'company_under_review',
                      'manual_only',
                      'closed_no_longer_accepting'
                    )
                    """
                )
            if priority_flag in (0, 1):
                where.append(
                    f"""(
                      CASE
                        WHEN TRIM(COALESCE(({effective_priority_flag_sql}), '')) <> '' THEN 1
                        ELSE 0
                      END
                    ) = ?"""
                )
                params.append(int(priority_flag))
            where_clause = " AND ".join(where)
            payload_sql = "'' AS latest_payload_json" if summary_only else "jp.latest_payload_json"
            select_sql = f"""
                {companies_under_review_cte}
                SELECT
                  jp.id,
                  jp.linkedin_job_id,
                  jp.title,
                  jp.company,
                  jp.location,
                  COALESCE(jp.normalized_work_model, '') AS normalized_work_model,
                  COALESCE(jp.normalized_employment_type, '') AS normalized_employment_type,
                  COALESCE(jp.normalized_easy_apply, 0) AS normalized_easy_apply,
                  COALESCE(jle.normalized_country, '') AS normalized_country,
                  COALESCE(jle.normalized_region, '') AS normalized_region,
                  jp.job_url,
                  COALESCE(jp.job_url_final, '') AS job_url_final,
                  {payload_sql},
                  jp.latest_posted_time,
                  jp.first_seen_date,
                  jp.last_seen_date,
                  jp.seen_count,
                  CASE WHEN {applied_evidence_sql} THEN 1 ELSE 0 END AS is_applied,
                  CASE
                    WHEN TRIM(COALESCE(jat.applied_source, '')) <> '' THEN COALESCE(jat.applied_source, '')
                    WHEN COALESCE(aer.has_manual_event, 0) = 1 THEN 'manual'
                    ELSE ''
                  END AS applied_source,
                  COALESCE(jat.has_response, 0) AS has_response,
                  COALESCE(jat.response_status, '') AS response_status,
                  COALESCE(jat.has_cv, 0) AS has_cv,
                  COALESCE(jat.cv_source_path, '') AS cv_source_path,
                  COALESCE(jat.portfolio_path, '') AS portfolio_path,
                  COALESCE(jat.cv_folder_name, '') AS cv_folder_name,
                  COALESCE(jat.cv_created_date, '') AS cv_created_date,
                  COALESCE(jat.cover_letter_path, '') AS cover_letter_path,
                  COALESCE(jat.cover_letter_docx_path, '') AS cover_letter_docx_path,
                  COALESCE(jat.cover_letter_pdf_path, '') AS cover_letter_pdf_path,
                  COALESCE(jat.generated_headline, '') AS generated_headline,
                  COALESCE(jat.generated_summary, '') AS generated_summary,
                  COALESCE(jat.generated_experience_summary, '') AS generated_experience_summary,
                  COALESCE(jat.generated_llm_model, '') AS generated_llm_model,
                  COALESCE(jat.generated_llm_backend, '') AS generated_llm_backend,
                  COALESCE(jat.generated_llm_usage_json, '') AS generated_llm_usage_json,
                  COALESCE(NULLIF(TRIM(COALESCE(jat.applied_last_seen_date, '')), ''), COALESCE(aer.latest_apply_date, ''), '') AS applied_last_seen_date,
                  COALESCE(jat.manual_review_required, 0) AS manual_review_required,
                  COALESCE(jat.manual_review_note, '') AS manual_review_note,
                  COALESCE(jat.priority_flag, '') AS job_priority_flag,
                  COALESCE(jat.priority_note, '') AS job_priority_note,
                  COALESCE(cp.priority_flag, '') AS company_priority_flag,
                  COALESCE(cp.priority_note, '') AS company_priority_note,
                  {effective_priority_flag_sql} AS effective_priority_flag,
                  {effective_priority_note_sql} AS effective_priority_note,
                  COALESCE(fs.total_score, 0) AS fit_score,
                  COALESCE(fs.status, '') AS fit_status,
                  COALESCE(fs.fit_reason, '') AS fit_reason,
                  COALESCE(fs.fit_reason_hard, fs.fit_reason, '') AS fit_reason_hard,
                  COALESCE(fs.fit_reason_medium, fs.fit_reason, '') AS fit_reason_medium,
                  COALESCE(fs.fit_reason_soft, fs.fit_reason, '') AS fit_reason_soft,
                  COALESCE(fs.primary_issue_metric, '') AS primary_issue_metric,
                  COALESCE(fs.primary_issue_score, 0) AS primary_issue_score,
                  COALESCE(fs.primary_issue_text, '') AS primary_issue_text,
                  COALESCE(fs.main_issue, fs.primary_issue_text, '') AS main_issue,
                  COALESCE(fs.fit_hard, fs.total_score, 0) AS fit_hard,
                  COALESCE(fs.fit_medium, fs.total_score, 0) AS fit_medium,
                  COALESCE(fs.fit_soft, fs.total_score, 0) AS fit_soft
                FROM job_posts jp
                LEFT JOIN job_location_enrichment jle ON jle.job_post_id = jp.id
                LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
                LEFT JOIN company_preferences cp
                  ON LOWER(TRIM(COALESCE(cp.company_name, ''))) = LOWER(TRIM(COALESCE(jp.company, '')))
                LEFT JOIN companies_under_review cur
                  ON cur.company_key = LOWER(TRIM(COALESCE(jp.company, '')))
                LEFT JOIN apply_event_rollup aer
                  ON aer.job_post_id = jp.id
                LEFT JOIN job_fit_scores fs ON fs.job_post_id = jp.id AND fs.cv_profile = 'full_doc_stlye'
                WHERE {where_clause}
            """
            can_use_sql_paging = not languages and not programming_languages and posted_within_days <= 0
            total_count = 0
            if can_use_sql_paging:
                total_row = conn.execute(
                    f"""
                    {companies_under_review_cte}
                    SELECT COUNT(*) AS total
                    FROM job_posts jp
                    LEFT JOIN job_location_enrichment jle ON jle.job_post_id = jp.id
                    LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
                    LEFT JOIN company_preferences cp
                      ON LOWER(TRIM(COALESCE(cp.company_name, ''))) = LOWER(TRIM(COALESCE(jp.company, '')))
                    LEFT JOIN companies_under_review cur
                      ON cur.company_key = LOWER(TRIM(COALESCE(jp.company, '')))
                    LEFT JOIN apply_event_rollup aer
                      ON aer.job_post_id = jp.id
                    WHERE {where_clause}
                    """,
                    params,
                ).fetchone()
                total_count = int((total_row["total"] if total_row else 0) or 0)
                rows = conn.execute(
                    f"""
                    {select_sql}
                    ORDER BY {self._list_jobs_sort_sql(sort_by, effective_priority_sql=effective_priority_flag_sql)}
                    LIMIT ? OFFSET ?
                    """,
                    [*params, int(limit), int(offset)],
                ).fetchall()
            else:
                rows = conn.execute(select_sql, params).fetchall()

            items = [dict(r) for r in rows]
            mode = str(constraint_mode or "medium").strip().lower()
            if mode not in {"hard", "medium", "soft"}:
                mode = "medium"
            job_ids = [int(x["id"]) for x in items]
            language_map = self._load_programming_languages_map(conn, job_ids)
            for item in items:
                if mode == "hard":
                    item["fit_score"] = float(item.get("fit_hard") or 0)
                    item["fit_reason"] = str(item.get("fit_reason_hard") or item.get("fit_reason") or "")
                elif mode == "soft":
                    item["fit_score"] = float(item.get("fit_soft") or 0)
                    item["fit_reason"] = str(item.get("fit_reason_soft") or item.get("fit_reason") or "")
                else:
                    item["fit_score"] = float(item.get("fit_medium") or 0)
                    item["fit_reason"] = str(item.get("fit_reason_medium") or item.get("fit_reason") or "")
                payload = str(item.get("latest_payload_json", ""))
                if summary_only:
                    lang_source = f"{item.get('title','')} {item.get('company','')} {item.get('location','')}"
                else:
                    lang_source = f"{item.get('title','')} {payload[:2000]}"
                item["job_language"] = _detect_language(lang_source)
                if item.get("normalized_country"):
                    item["country"] = item["normalized_country"]
                else:
                    item["country"] = str(item.get("location", ""))
                item["region"] = str(item.get("normalized_region", ""))
                item["work_model"] = str(item.get("normalized_work_model", ""))
                item["employment_type"] = str(item.get("normalized_employment_type", ""))
                item["easy_apply"] = int(item.get("normalized_easy_apply") or 0)
                item["linkedin_posted_date"] = _estimate_linkedin_posted_date(
                    str(item.get("latest_posted_time", "")),
                    str(item.get("last_seen_date", "")),
                    str(item.get("first_seen_date", "")),
                )
                item["job_url_final"] = _canonical_linkedin_job_url(
                    str(item.get("job_url", "")),
                    str(item.get("job_url_final", "")),
                    item.get("linkedin_job_id"),
                )
                item_languages = sorted(language_map.get(int(item["id"]), set()))
                item["programming_languages"] = item_languages
                item["programming_language"] = ", ".join(item_languages)
                item.pop("latest_payload_json", None)
                item.pop("fit_hard", None)
                item.pop("fit_medium", None)
                item.pop("fit_soft", None)
                item.pop("fit_reason_hard", None)
                item.pop("fit_reason_medium", None)
                item.pop("fit_reason_soft", None)

            if languages:
                selected = set(languages)
                items = [x for x in items if str(x.get("job_language", "other")) in selected]
            if programming_languages:
                selected_programming = {s.strip().lower() for s in programming_languages if s.strip()}
                items = [
                    x
                    for x in items
                    if any(str(lang).strip().lower() in selected_programming for lang in x.get("programming_languages", []))
                ]
            if posted_within_days > 0:
                cutoff = datetime.now().date() - timedelta(days=posted_within_days)
                filtered_items = []
                for x in items:
                    posted = str(x.get("linkedin_posted_date", "")).strip()
                    if not posted:
                        continue
                    try:
                        posted_date = datetime.fromisoformat(posted).date()
                    except ValueError:
                        continue
                    if posted_date >= cutoff:
                        filtered_items.append(x)
                items = filtered_items

            if can_use_sql_paging:
                return {"total": total_count, "items": items}

            if sort_by == "last_seen_desc":
                items.sort(key=lambda x: (_date_key(str(x.get("last_seen_date", ""))), int(x.get("id", 0))), reverse=True)
                items.sort(key=lambda x: self._priority_sort_bucket(x))
            elif sort_by == "last_seen_asc":
                items.sort(key=lambda x: (_date_key(str(x.get("last_seen_date", ""))), int(x.get("id", 0))))
                items.sort(key=lambda x: self._priority_sort_bucket(x))
            elif sort_by == "posted_date_asc":
                items.sort(key=lambda x: (_date_key(str(x.get("linkedin_posted_date", ""))), int(x.get("id", 0))))
                items.sort(key=lambda x: self._priority_sort_bucket(x))
            else:
                items.sort(key=lambda x: (_date_key(str(x.get("linkedin_posted_date", ""))), int(x.get("id", 0))), reverse=True)
                items.sort(key=lambda x: self._priority_sort_bucket(x))

            paged = items[offset : offset + limit]
            return {"total": len(items), "items": paged}

    def get_job_detail(self, job_post_id: int, constraint_mode: str = "medium") -> dict[str, Any] | None:
        with self.db.connect() as conn:
            self._run_request_maintenance_if_due(conn)
            row = conn.execute(
                f"""
                SELECT
                  jp.*,
                  COALESCE(jp.normalized_work_model, '') AS normalized_work_model,
                  COALESCE(jp.normalized_employment_type, '') AS normalized_employment_type,
                  COALESCE(jp.normalized_easy_apply, 0) AS normalized_easy_apply,
                  COALESCE(jle.normalized_country, '') AS normalized_country,
                  COALESCE(jle.normalized_region, '') AS normalized_region,
                  COALESCE(jdv.posted_time, '') AS validated_posted_time,
                  COALESCE(jdv.linkedin_posted_date, '') AS validated_linkedin_posted_date,
                  COALESCE(jdv.applicant_insight, '') AS validated_applicant_insight,
                  COALESCE(jdv.compensation_text, '') AS validated_compensation_text,
                  COALESCE(jdv.work_model, '') AS validated_work_model,
                  COALESCE(jdv.employment_type, '') AS validated_employment_type,
                  COALESCE(jdv.easy_apply, 0) AS validated_easy_apply,
                  COALESCE(jdv.application_status, '') AS validated_application_status,
                  COALESCE(jdv.response_note, '') AS validated_response_note,
                  COALESCE(jdv.programming_language, '') AS validated_programming_language,
                  COALESCE(jdv.validation_backend, '') AS validated_detail_backend,
                  COALESCE(jdv.validation_model, '') AS validated_detail_model,
                  COALESCE(jat.is_applied, 0) AS is_applied,
                  COALESCE(jat.applied_source, '') AS applied_source,
                  COALESCE(jat.has_response, 0) AS has_response,
                  COALESCE(jat.response_status, '') AS response_status,
                  COALESCE(jat.has_cv, 0) AS has_cv,
                  COALESCE(jat.cv_source_path, '') AS cv_source_path,
                  COALESCE(jat.portfolio_path, '') AS portfolio_path,
                  COALESCE(jat.cv_folder_name, '') AS cv_folder_name,
                  COALESCE(jat.cv_created_date, '') AS cv_created_date,
                  COALESCE(jat.cover_letter_path, '') AS cover_letter_path,
                  COALESCE(jat.cover_letter_docx_path, '') AS cover_letter_docx_path,
                  COALESCE(jat.cover_letter_pdf_path, '') AS cover_letter_pdf_path,
                  COALESCE(jat.generated_headline, '') AS generated_headline,
                  COALESCE(jat.generated_summary, '') AS generated_summary,
                  COALESCE(jat.generated_experience_summary, '') AS generated_experience_summary,
                  COALESCE(jat.generated_llm_model, '') AS generated_llm_model,
                  COALESCE(jat.generated_llm_backend, '') AS generated_llm_backend,
                  COALESCE(jat.generated_llm_usage_json, '') AS generated_llm_usage_json,
                  COALESCE(jat.manual_review_required, 0) AS manual_review_required,
                  COALESCE(jat.manual_review_note, '') AS manual_review_note,
                  COALESCE(jat.priority_flag, '') AS job_priority_flag,
                  COALESCE(jat.priority_note, '') AS job_priority_note,
                  COALESCE(cp.priority_flag, '') AS company_priority_flag,
                  COALESCE(cp.priority_note, '') AS company_priority_note,
                  {self._effective_priority_flag_sql(job_alias='jp', tracking_alias='jat', company_alias='cp')} AS effective_priority_flag,
                  {self._effective_priority_note_sql(job_alias='jp', tracking_alias='jat', company_alias='cp')} AS effective_priority_note,
                  COALESCE(jat.applied_last_seen_date, '') AS applied_last_seen_date,
                  COALESCE(jat.tracker_payload_json, '') AS tracker_payload_json,
                  COALESCE(fs.total_score, 0) AS fit_score,
                  COALESCE(fs.status, '') AS fit_status,
                  COALESCE(fs.fit_reason, '') AS fit_reason,
                  COALESCE(fs.fit_reason_hard, fs.fit_reason, '') AS fit_reason_hard,
                  COALESCE(fs.fit_reason_medium, fs.fit_reason, '') AS fit_reason_medium,
                  COALESCE(fs.fit_reason_soft, fs.fit_reason, '') AS fit_reason_soft,
                  COALESCE(fs.primary_issue_metric, '') AS primary_issue_metric,
                  COALESCE(fs.primary_issue_score, 0) AS primary_issue_score,
                  COALESCE(fs.primary_issue_text, '') AS primary_issue_text,
                  COALESCE(fs.main_issue, fs.primary_issue_text, '') AS main_issue,
                  COALESCE(fs.fit_hard, fs.total_score, 0) AS fit_hard,
                  COALESCE(fs.fit_medium, fs.total_score, 0) AS fit_medium,
                  COALESCE(fs.fit_soft, fs.total_score, 0) AS fit_soft,
                  COALESCE(fs.matched_keywords_json, '[]') AS matched_keywords_json,
                  COALESCE(fs.missing_keywords_json, '[]') AS missing_keywords_json,
                  COALESCE(fs.evaluated_at, '') AS evaluated_at
                FROM job_posts jp
                LEFT JOIN job_location_enrichment jle ON jle.job_post_id = jp.id
                LEFT JOIN job_detail_validations jdv ON jdv.job_post_id = jp.id
                LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
                LEFT JOIN company_preferences cp
                  ON LOWER(TRIM(COALESCE(cp.company_name, ''))) = LOWER(TRIM(COALESCE(jp.company, '')))
                LEFT JOIN job_fit_scores fs ON fs.job_post_id = jp.id AND fs.cv_profile = 'full_doc_stlye'
                WHERE jp.id = ?
                """,
                (job_post_id,),
            ).fetchone()
            if row is None:
                return None

            obs = conn.execute(
                """
                SELECT crawl_date, posted_time, is_duplicate_signature
                FROM job_observations
                WHERE job_post_id = ?
                ORDER BY crawl_date
                """,
                (job_post_id,),
            ).fetchall()
            jd_row = conn.execute(
                """
                SELECT
                  jjc.jd_text,
                  COALESCE(jjc.jd_source, '') AS jd_source,
                  jjc.updated_at
                FROM job_jd_contents jjc
                JOIN job_observations jo ON jo.id = jjc.observation_id
                WHERE jo.job_post_id = ?
                ORDER BY
                  CASE
                    WHEN COALESCE(TRIM(jjc.jd_text), '') = '' THEN 3
                    WHEN LOWER(TRIM(COALESCE(jjc.jd_text, ''))) LIKE 'job context (fallback jd):%' THEN 2
                    WHEN LOWER(TRIM(COALESCE(jjc.jd_text, ''))) LIKE 'fallback jd:%' THEN 2
                    WHEN LOWER(COALESCE(jjc.jd_source, '')) LIKE '%full_page_text%' THEN 1
                    ELSE 0
                  END ASC,
                  jo.crawl_date DESC,
                  jo.id DESC
                LIMIT 1
                """,
                (job_post_id,),
            ).fetchone()
            payload_jd_text, payload_jd_source = _best_payload_jd_text(row["latest_payload_json"])
            if payload_jd_text and (
                jd_row is None
                or not str(jd_row["jd_text"] or "").strip()
                or _looks_like_fallback_jd(str(jd_row["jd_text"] or ""))
                or _source_uses_full_page_text(str(jd_row["jd_source"] or ""))
            ):
                jd_row = {
                "jd_text": payload_jd_text,
                "jd_source": payload_jd_source,
                "updated_at": str(row["updated_at"] or "") if row["updated_at"] is not None else "",
            }
            if jd_row is None or not str(jd_row["jd_text"] or "").strip():
                jd_row = conn.execute(
                    """
                    SELECT
                      jjc.jd_text,
                      COALESCE(jjc.jd_source, '') AS jd_source,
                      jjc.updated_at
                    FROM job_posts jp_cur
                    JOIN job_posts jp_peer ON jp_peer.role_signature = jp_cur.role_signature
                    JOIN job_observations jo ON jo.job_post_id = jp_peer.id
                    JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
                    WHERE jp_cur.id = ?
                      AND COALESCE(TRIM(jjc.jd_text), '') <> ''
                      AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
                      AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
                      AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
                    ORDER BY jo.crawl_date DESC, jo.id DESC
                    LIMIT 1
                    """,
                    (job_post_id,),
                ).fetchone()
            if jd_row is None or not str(jd_row["jd_text"] or "").strip():
                jd_row = conn.execute(
                    """
                    SELECT
                      jjc.jd_text,
                      COALESCE(jjc.jd_source, '') AS jd_source,
                      jjc.updated_at
                    FROM job_posts jp_cur
                    JOIN job_posts jp_peer
                      ON COALESCE(LOWER(TRIM(jp_peer.title)), '') = COALESCE(LOWER(TRIM(jp_cur.title)), '')
                     AND COALESCE(LOWER(TRIM(jp_peer.company)), '') = COALESCE(LOWER(TRIM(jp_cur.company)), '')
                    JOIN job_observations jo ON jo.job_post_id = jp_peer.id
                    JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
                    WHERE jp_cur.id = ?
                      AND COALESCE(TRIM(jjc.jd_text), '') <> ''
                      AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
                      AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
                      AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
                    ORDER BY jo.crawl_date DESC, jo.id DESC
                    LIMIT 1
                    """,
                    (job_post_id,),
                ).fetchone()
            if jd_row is None or not str(jd_row["jd_text"] or "").strip():
                current_title = str(row["title"] or "")
                current_company = str(row["company"] or "")
                peers = conn.execute(
                    """
                    SELECT
                      jp.id,
                      jp.title,
                      jjc.jd_text,
                      COALESCE(jjc.jd_source, '') AS jd_source,
                      jjc.updated_at
                    FROM job_posts jp
                    JOIN job_observations jo ON jo.job_post_id = jp.id
                    JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
                    WHERE COALESCE(LOWER(TRIM(jp.company)), '') = COALESCE(LOWER(TRIM(?)), '')
                      AND jp.id <> ?
                      AND COALESCE(TRIM(jjc.jd_text), '') <> ''
                      AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
                      AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
                      AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
                    ORDER BY jo.crawl_date DESC, jo.id DESC
                    LIMIT 200
                    """,
                    (current_company, job_post_id),
                ).fetchall()
                best_peer = None
                best_score = 0
                for peer in peers:
                    score = _title_overlap(current_title, str(peer["title"] or ""))
                    if score > best_score:
                        best_score = score
                        best_peer = peer
                if best_peer is not None and best_score > 0:
                    jd_row = {
                        "jd_text": str(best_peer["jd_text"] or ""),
                        "jd_source": str(best_peer["jd_source"] or ""),
                        "updated_at": str(best_peer["updated_at"] or ""),
                    }
            result = dict(row)
            mode = str(constraint_mode or "medium").strip().lower()
            if mode not in {"hard", "medium", "soft"}:
                mode = "medium"
            if mode == "hard":
                result["fit_score"] = float(result.get("fit_hard") or 0)
                result["fit_reason"] = str(result.get("fit_reason_hard") or result.get("fit_reason") or "")
            elif mode == "soft":
                result["fit_score"] = float(result.get("fit_soft") or 0)
                result["fit_reason"] = str(result.get("fit_reason_soft") or result.get("fit_reason") or "")
            else:
                result["fit_score"] = float(result.get("fit_medium") or 0)
                result["fit_reason"] = str(result.get("fit_reason_medium") or result.get("fit_reason") or "")
            validated_posted_time = str(result.get("validated_posted_time") or "").strip()
            validated_posted_date = str(result.get("validated_linkedin_posted_date") or "").strip()
            result["posted_time"] = validated_posted_time or str(result.get("latest_posted_time", "")).strip()
            result["linkedin_posted_date"] = validated_posted_date or _estimate_linkedin_posted_date(
                result["posted_time"],
                str(result.get("last_seen_date", "")),
                str(result.get("first_seen_date", "")),
            )
            if not result["posted_time"]:
                result["posted_time"] = _estimate_posted_time_label(result["linkedin_posted_date"])
            result["job_url_final"] = _canonical_linkedin_job_url(
                str(result.get("job_url", "")),
                str(result.get("job_url_final", "")),
                result.get("linkedin_job_id"),
            )
            payload_job_type_tags = _parse_payload_job_type_tags(str(result.get("latest_payload_json") or ""))
            result["payload_job_type_tags"] = payload_job_type_tags
            result["country"] = str(result.get("normalized_country") or result.get("location") or "")
            result["region"] = str(result.get("normalized_region") or "")
            result["work_model"] = (
                _clean_unknown_value(result.get("validated_work_model"))
                or _clean_unknown_value(result.get("normalized_work_model"))
                or _infer_work_model_from_tags(payload_job_type_tags)
            )
            result["employment_type"] = (
                _clean_unknown_value(result.get("validated_employment_type"))
                or _clean_unknown_value(result.get("normalized_employment_type"))
                or _infer_employment_type_from_tags(payload_job_type_tags)
            )
            result["easy_apply"] = int(result.get("validated_easy_apply") or result.get("normalized_easy_apply") or 0)
            langs = conn.execute(
                """
                SELECT language
                FROM job_programming_languages
                WHERE job_post_id = ?
                  AND LOWER(TRIM(COALESCE(language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
                ORDER BY language COLLATE NOCASE ASC
                """,
                (job_post_id,),
            ).fetchall()
            result["programming_languages"] = [str(x["language"]) for x in langs]
            result["programming_language"] = str(result.get("validated_programming_language") or "").strip() or ", ".join(result["programming_languages"])
            result["applicant_insight"] = str(result.get("validated_applicant_insight") or "").strip()
            result["compensation_text"] = str(result.get("validated_compensation_text") or "").strip()
            result["response_note"] = str(result.get("validated_response_note") or "").strip()
            result["application_status"] = str(result.get("validated_application_status") or "").strip()
            result.pop("fit_hard", None)
            result.pop("fit_medium", None)
            result.pop("fit_soft", None)
            result.pop("fit_reason_hard", None)
            result.pop("fit_reason_medium", None)
            result.pop("fit_reason_soft", None)
            result["jd_text"] = self._sanitize_jd_text(str(jd_row["jd_text"])) if jd_row else ""
            result["jd_source"] = str(jd_row["jd_source"]) if jd_row else ""
            result["jd_updated_at"] = str(jd_row["updated_at"]) if jd_row else ""
            result["observations"] = [dict(r) for r in obs]
            return result

    def list_countries(self) -> list[str]:
        with self.db.connect() as conn:
            country_rows = conn.execute(
                """
                SELECT DISTINCT TRIM(normalized_country) AS country
                FROM geo_region_country_map
                WHERE TRIM(COALESCE(normalized_country, '')) <> ''
                UNION
                SELECT DISTINCT TRIM(normalized_country) AS country
                FROM job_location_enrichment
                WHERE TRIM(COALESCE(normalized_country, '')) <> ''
                ORDER BY country COLLATE NOCASE ASC
                """
            ).fetchall()
            region_rows = conn.execute(
                """
                SELECT DISTINCT TRIM(normalized_region) AS region
                FROM geo_region_country_map
                WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                UNION
                SELECT DISTINCT TRIM(normalized_region) AS region
                FROM job_location_enrichment
                WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                ORDER BY region COLLATE NOCASE ASC
                """
            ).fetchall()
        countries = [str(r["country"]) for r in country_rows]
        regions = [str(r["region"]) for r in region_rows]
        ordered_regions = sorted({canonicalize_region(r) for r in regions if str(r).strip()}, key=_region_sort_key)
        ordered_countries = sorted({c for c in countries if str(c).strip()}, key=lambda x: x.lower())
        return [*ordered_regions, *ordered_countries]

    def list_programming_languages(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT language
                FROM job_programming_languages
                WHERE TRIM(COALESCE(language, '')) <> ''
                  AND LOWER(TRIM(COALESCE(language, ''))) NOT IN ('unknown', '-', 'n/a', 'na', 'none', 'null')
                ORDER BY language COLLATE NOCASE ASC
                """
            ).fetchall()
        languages = [str(r["language"]) for r in rows]
        return sorted(languages, key=_programming_language_sort_key)

    def list_programming_languages_grouped(self) -> list[dict[str, Any]]:
        languages = self.list_programming_languages()
        grouped: dict[str, list[str]] = {}
        for language in languages:
            group_name = _programming_group(language)
            grouped.setdefault(group_name, []).append(language)
        items: list[dict[str, Any]] = []
        for group_name in sorted(grouped.keys(), key=lambda x: PROGRAMMING_GROUP_ORDER.get(x, 99)):
            langs = sorted(set(grouped[group_name]), key=lambda x: x.lower())
            items.append({"group": group_name, "languages": langs})
        return items

    def list_regions(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT TRIM(normalized_region) AS region
                FROM geo_region_country_map
                WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                UNION
                SELECT DISTINCT TRIM(normalized_region) AS region
                FROM job_location_enrichment
                WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                ORDER BY region COLLATE NOCASE ASC
                """
            ).fetchall()
        regions = [canonicalize_region(str(r["region"])) for r in rows if str(r["region"]).strip()]
        unique_regions = sorted(set(regions), key=_region_sort_key)
        return unique_regions

    def list_region_countries(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  TRIM(COALESCE(normalized_region, '')) AS region,
                  TRIM(COALESCE(normalized_country, '')) AS country,
                  SUM(jobs) AS jobs
                FROM (
                  SELECT
                    normalized_region,
                    normalized_country,
                    0 AS jobs
                  FROM geo_region_country_map
                  UNION ALL
                  SELECT
                    normalized_region,
                    normalized_country,
                    COUNT(*) AS jobs
                  FROM job_location_enrichment
                  GROUP BY normalized_region, normalized_country
                ) src
                WHERE TRIM(COALESCE(normalized_region, '')) <> ''
                  AND TRIM(COALESCE(normalized_country, '')) <> ''
                GROUP BY region, country
                ORDER BY region COLLATE NOCASE ASC, country COLLATE NOCASE ASC
                """
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            region = canonicalize_region(str(row["region"]))
            grouped.setdefault(region, []).append({"country": str(row["country"]), "jobs": int(row["jobs"])})
        items = []
        for region in sorted(grouped.keys(), key=_region_sort_key):
            countries = sorted(grouped[region], key=lambda x: str(x.get("country", "")).lower())
            items.append({"region": region, "countries": countries})
        return items

    @staticmethod
    def _load_programming_languages_map(conn, job_ids: list[int]) -> dict[int, set[str]]:
        if not job_ids:
            return {}
        placeholders = ",".join(["?"] * len(job_ids))
        rows = conn.execute(
            f"""
            SELECT job_post_id, language
            FROM job_programming_languages
            WHERE job_post_id IN ({placeholders})
              AND LOWER(TRIM(COALESCE(language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            """,
            job_ids,
        ).fetchall()
        mapping: dict[int, set[str]] = {}
        for row in rows:
            job_post_id = int(row["job_post_id"])
            mapping.setdefault(job_post_id, set()).add(str(row["language"]))
        return mapping
