from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from app.repositories.database import Database


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


def _date_key(value: str) -> tuple[int, str]:
    if not value:
        return (0, "")
    return (1, value)


class FitRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_jobs_for_fit(
        self,
        stage: str,
        limit: int = 0,
        posted_within_days: int = 0,
        sort_by: str = "posted_date_desc",
        job_post_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        where = "1=1"
        if stage == "applied":
            where = "COALESCE(jat.is_applied, 0) = 1"
        elif stage == "filtered":
            where = "COALESCE(jat.is_applied, 0) = 0"
        params: list[Any] = []
        if job_post_ids:
            placeholders = ",".join("?" for _ in job_post_ids)
            where += f" AND jp.id IN ({placeholders})"
            params.extend(int(x) for x in job_post_ids)

        use_sql_limit = bool(limit and limit > 0 and posted_within_days <= 0 and sort_by == "last_seen_desc")

        with self.db.connect() as conn:
            if use_sql_limit:
                rows = conn.execute(
                    f"""
                    SELECT
                      jp.id,
                      jp.title,
                      jp.company,
                      jp.location,
                      jp.latest_payload_json,
                      jp.latest_posted_time,
                      jp.last_seen_date,
                      jp.first_seen_date,
                      (
                        SELECT jjc.jd_text
                        FROM job_jd_contents jjc
                        WHERE jjc.job_post_id = jp.id
                        ORDER BY jjc.updated_at DESC, jjc.id DESC
                        LIMIT 1
                      ) AS jd_text
                    FROM job_posts jp
                    LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
                    WHERE {where}
                    ORDER BY jp.last_seen_date DESC, jp.id DESC
                    LIMIT ?
                    """,
                    (*params, max(1, limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT
                      jp.id,
                      jp.title,
                      jp.company,
                      jp.location,
                      jp.latest_payload_json,
                      jp.latest_posted_time,
                      jp.last_seen_date,
                      jp.first_seen_date,
                      (
                        SELECT jjc.jd_text
                        FROM job_jd_contents jjc
                        WHERE jjc.job_post_id = jp.id
                        ORDER BY jjc.updated_at DESC, jjc.id DESC
                        LIMIT 1
                      ) AS jd_text
                    FROM job_posts jp
                    LEFT JOIN job_application_tracking jat ON jat.job_post_id = jp.id
                    WHERE {where}
                    ORDER BY jp.last_seen_date DESC, jp.id DESC
                    """,
                    tuple(params),
                ).fetchall()

        items = [dict(r) for r in rows]

        if posted_within_days > 0:
            cutoff = datetime.now().date() - timedelta(days=posted_within_days)
            filtered_items: list[dict[str, Any]] = []
            for item in items:
                posted = _estimate_linkedin_posted_date(
                    str(item.get("latest_posted_time", "")),
                    str(item.get("last_seen_date", "")),
                    str(item.get("first_seen_date", "")),
                )
                if not posted:
                    continue
                try:
                    posted_date = datetime.fromisoformat(posted).date()
                except ValueError:
                    continue
                if posted_date >= cutoff:
                    filtered_items.append(item)
            items = filtered_items

        for item in items:
            item["linkedin_posted_date"] = _estimate_linkedin_posted_date(
                str(item.get("latest_posted_time", "")),
                str(item.get("last_seen_date", "")),
                str(item.get("first_seen_date", "")),
            )

        if sort_by == "last_seen_desc":
            items.sort(key=lambda x: (_date_key(str(x.get("last_seen_date", ""))), int(x.get("id", 0))), reverse=True)
        elif sort_by == "last_seen_asc":
            items.sort(key=lambda x: (_date_key(str(x.get("last_seen_date", ""))), int(x.get("id", 0))))
        elif sort_by == "posted_date_asc":
            items.sort(key=lambda x: (_date_key(str(x.get("linkedin_posted_date", ""))), int(x.get("id", 0))))
        else:
            items.sort(key=lambda x: (_date_key(str(x.get("linkedin_posted_date", ""))), int(x.get("id", 0))), reverse=True)

        if limit and limit > 0 and not use_sql_limit:
            items = items[: max(1, limit)]

        return items

    def upsert_fit_score(self, data: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_fit_scores (
                    job_post_id, cv_profile, cv_source_path,
                    total_score, fit_hard, fit_medium, fit_soft, domain_score, tech_score, evidence_score, constraint_score,
                    status, fit_reason, fit_reason_hard, fit_reason_medium, fit_reason_soft,
                    primary_issue_metric, primary_issue_score, primary_issue_text, main_issue,
                    matched_keywords_json, missing_keywords_json, evaluated_at, evaluator_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_post_id, cv_profile)
                DO UPDATE SET
                    cv_source_path = excluded.cv_source_path,
                    total_score = excluded.total_score,
                    fit_hard = excluded.fit_hard,
                    fit_medium = excluded.fit_medium,
                    fit_soft = excluded.fit_soft,
                    domain_score = excluded.domain_score,
                    tech_score = excluded.tech_score,
                    evidence_score = excluded.evidence_score,
                    constraint_score = excluded.constraint_score,
                    status = excluded.status,
                    fit_reason = excluded.fit_reason,
                    fit_reason_hard = excluded.fit_reason_hard,
                    fit_reason_medium = excluded.fit_reason_medium,
                    fit_reason_soft = excluded.fit_reason_soft,
                    primary_issue_metric = excluded.primary_issue_metric,
                    primary_issue_score = excluded.primary_issue_score,
                    primary_issue_text = excluded.primary_issue_text,
                    main_issue = excluded.main_issue,
                    matched_keywords_json = excluded.matched_keywords_json,
                    missing_keywords_json = excluded.missing_keywords_json,
                    evaluated_at = excluded.evaluated_at,
                    evaluator_version = excluded.evaluator_version
                """,
                (
                    data["job_post_id"],
                    data["cv_profile"],
                    data["cv_source_path"],
                    data["total_score"],
                    data.get("fit_hard"),
                    data.get("fit_medium"),
                    data.get("fit_soft"),
                    data["domain_score"],
                    data["tech_score"],
                    data["evidence_score"],
                    data["constraint_score"],
                    data["status"],
                    data.get("fit_reason", ""),
                    data.get("fit_reason_hard", data.get("fit_reason", "")),
                    data.get("fit_reason_medium", data.get("fit_reason", "")),
                    data.get("fit_reason_soft", data.get("fit_reason", "")),
                    data.get("primary_issue_metric", ""),
                    data.get("primary_issue_score"),
                    data.get("primary_issue_text", ""),
                    data.get("main_issue", data.get("primary_issue_text", "")),
                    data["matched_keywords_json"],
                    data["missing_keywords_json"],
                    data["evaluated_at"],
                    data["evaluator_version"],
                ),
            )

