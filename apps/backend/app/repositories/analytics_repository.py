from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.repositories.database import Database

try:
    APP_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
except ZoneInfoNotFoundError:
    APP_TIMEZONE = timezone.utc

STACK_GROUP_ORDER = {
    "Full Stack + AI": 1,
    "Full Stack + Data": 2,
    "Full Stack + DevOps": 3,
    "Full Stack": 4,
    "Data/AI": 5,
    "Frontend (FE)": 6,
    "Backend (BE)": 7,
    "AI/ML": 8,
    "Data": 9,
    "DevOps/Cloud": 10,
    "Mobile": 11,
    "Other": 99,
}

STACK_SIGNAL_LABELS = [
    ("frontend", "frontend"),
    ("backend", "backend"),
    ("ai", "ai"),
    ("data", "data"),
    ("devops", "devops"),
    ("mobile", "mobile"),
]

STACK_SIGNAL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "frontend": [
        re.compile(r"\bfront[- ]?end\b", re.IGNORECASE),
        re.compile(r"\bui engineer\b", re.IGNORECASE),
        re.compile(r"\bweb engineer\b", re.IGNORECASE),
        re.compile(r"\breact\b", re.IGNORECASE),
        re.compile(r"\bvue\b", re.IGNORECASE),
        re.compile(r"\bangular\b", re.IGNORECASE),
        re.compile(r"\bnext\.?js\b", re.IGNORECASE),
        re.compile(r"\bjavascript\b", re.IGNORECASE),
        re.compile(r"\btypescript\b", re.IGNORECASE),
        re.compile(r"\bhtml\b", re.IGNORECASE),
        re.compile(r"\bcss\b", re.IGNORECASE),
    ],
    "backend": [
        re.compile(r"\bback[- ]?end\b", re.IGNORECASE),
        re.compile(r"\bapi\b", re.IGNORECASE),
        re.compile(r"\bservice(s)?\b", re.IGNORECASE),
        re.compile(r"\bserver\b", re.IGNORECASE),
        re.compile(r"\bmicroservice(s)?\b", re.IGNORECASE),
        re.compile(r"\bpython\b", re.IGNORECASE),
        re.compile(r"\bjava\b", re.IGNORECASE),
        re.compile(r"\bgo(lang)?\b", re.IGNORECASE),
        re.compile(r"\bnode(?:\.js)?\b", re.IGNORECASE),
        re.compile(r"\bphp\b", re.IGNORECASE),
        re.compile(r"\bscala\b", re.IGNORECASE),
        re.compile(r"\bruby\b", re.IGNORECASE),
        re.compile(r"\brust\b", re.IGNORECASE),
        re.compile(r"\bkotlin\b", re.IGNORECASE),
        re.compile(r"\bc#\b|\b\.net\b|\basp\.net\b", re.IGNORECASE),
    ],
    "ai": [
        re.compile(r"\bai engineer\b", re.IGNORECASE),
        re.compile(r"\bartificial intelligence\b", re.IGNORECASE),
        re.compile(r"\bml\b", re.IGNORECASE),
        re.compile(r"\bmachine learning\b", re.IGNORECASE),
        re.compile(r"\bllm(s)?\b", re.IGNORECASE),
        re.compile(r"\bgenai\b", re.IGNORECASE),
        re.compile(r"\bnlp\b", re.IGNORECASE),
        re.compile(r"\bprompt(s)?\b", re.IGNORECASE),
        re.compile(r"\bagent(s|ic)?\b", re.IGNORECASE),
        re.compile(r"\bpytorch\b", re.IGNORECASE),
        re.compile(r"\btensorflow\b", re.IGNORECASE),
    ],
    "data": [
        re.compile(r"\bdata engineer\b", re.IGNORECASE),
        re.compile(r"\bdata platform\b", re.IGNORECASE),
        re.compile(r"\bdata science\b", re.IGNORECASE),
        re.compile(r"\banalytics\b", re.IGNORECASE),
        re.compile(r"\betl\b", re.IGNORECASE),
        re.compile(r"\bwarehouse\b", re.IGNORECASE),
        re.compile(r"\bdbt\b", re.IGNORECASE),
        re.compile(r"\bspark\b", re.IGNORECASE),
        re.compile(r"\bairflow\b", re.IGNORECASE),
        re.compile(r"\bbi\b", re.IGNORECASE),
    ],
    "devops": [
        re.compile(r"\bdevops\b", re.IGNORECASE),
        re.compile(r"\bsre\b", re.IGNORECASE),
        re.compile(r"\bplatform\b", re.IGNORECASE),
        re.compile(r"\binfra(structure)?\b", re.IGNORECASE),
        re.compile(r"\bdocker\b", re.IGNORECASE),
        re.compile(r"\bkubernetes\b", re.IGNORECASE),
        re.compile(r"\bterraform\b", re.IGNORECASE),
        re.compile(r"\baws\b", re.IGNORECASE),
        re.compile(r"\bazure\b", re.IGNORECASE),
        re.compile(r"\bgcp\b", re.IGNORECASE),
        re.compile(r"\bjenkins\b", re.IGNORECASE),
    ],
    "mobile": [
        re.compile(r"\bmobile\b", re.IGNORECASE),
        re.compile(r"\bios\b", re.IGNORECASE),
        re.compile(r"\bandroid\b", re.IGNORECASE),
        re.compile(r"\bswift\b", re.IGNORECASE),
        re.compile(r"\bkotlin\b", re.IGNORECASE),
        re.compile(r"\bflutter\b", re.IGNORECASE),
        re.compile(r"\breact native\b", re.IGNORECASE),
    ],
}

STACK_LANGUAGE_HINTS: dict[str, set[str]] = {
    "frontend": {"javascript", "typescript", "html", "css"},
    "backend": {"python", "java", "go", "golang", "node.js", "nodejs", "php", "ruby", "rust", "scala", "kotlin", "c#", ".net", "asp.net"},
    "ai": {"r", "pytorch", "tensorflow"},
    "data": {"sql", "postgresql", "mysql", "sqlite", "spark", "pandas", "numpy"},
    "devops": {"docker", "kubernetes", "terraform", "ansible", "aws", "azure", "gcp"},
    "mobile": {"swift", "kotlin", "flutter", "android", "ios", "react native"},
}

STACK_GROUP_HUMAN_LABELS = {
    "frontend": "Frontend (FE)",
    "backend": "Backend (BE)",
    "ai": "AI/ML",
    "data": "Data",
    "devops": "DevOps/Cloud",
    "mobile": "Mobile",
}

STACK_SIGNAL_ORDER = ["frontend", "backend", "ai", "data", "devops", "mobile"]


def _stack_text_blob(*, title: str, payload_json: str, languages: list[str]) -> str:
    return "\n".join(
        part
        for part in [
            str(title or "").strip(),
            str(payload_json or "")[:4000].strip(),
            " ".join(str(language or "").strip() for language in languages if str(language or "").strip()),
        ]
        if part
    ).lower()


def _stack_signal_scores(text_blob: str, languages: list[str]) -> dict[str, int]:
    scores = {key: 0 for key in STACK_SIGNAL_PATTERNS}
    for key, patterns in STACK_SIGNAL_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text_blob):
                scores[key] += 2
                break
    normalized_languages = {str(language or "").strip().lower() for language in languages if str(language or "").strip()}
    for key, hints in STACK_LANGUAGE_HINTS.items():
        for hint in hints:
            if hint in normalized_languages:
                scores[key] += 1
    return scores


def _stack_signal_mix(scores: dict[str, int]) -> str:
    active = [label for key, label in STACK_SIGNAL_LABELS if scores.get(key, 0) > 0]
    return " + ".join(active)


def _stack_group_label(scores: dict[str, int]) -> str:
    frontend = scores.get("frontend", 0) > 0
    backend = scores.get("backend", 0) > 0
    ai = scores.get("ai", 0) > 0
    data = scores.get("data", 0) > 0
    devops = scores.get("devops", 0) > 0
    mobile = scores.get("mobile", 0) > 0
    if frontend and backend:
        if ai:
            return "Full Stack + AI"
        if data:
            return "Full Stack + Data"
        if devops:
            return "Full Stack + DevOps"
        return "Full Stack"
    if ai and data:
        return "Data/AI"
    if ai:
        return STACK_GROUP_HUMAN_LABELS["ai"]
    if frontend:
        return STACK_GROUP_HUMAN_LABELS["frontend"]
    if backend:
        return STACK_GROUP_HUMAN_LABELS["backend"]
    if data:
        return STACK_GROUP_HUMAN_LABELS["data"]
    if devops:
        return STACK_GROUP_HUMAN_LABELS["devops"]
    if mobile:
        return STACK_GROUP_HUMAN_LABELS["mobile"]
    return "Other"


def _stack_region_story(group: str) -> str:
    normalized = str(group or "").strip().lower()
    if "full stack" in normalized:
        return "Full-stack roles usually cluster where product teams need one person to move across UI, API, and delivery work without hand-offs."
    if "frontend" in normalized:
        return "Frontend roles tend to cluster around product teams shipping UI-heavy work quickly and iterating on user experience."
    if "backend" in normalized:
        return "Backend roles usually sit around API, services, and platform work, so they concentrate where scale and reliability matter."
    if "ai" in normalized:
        return "AI roles usually cluster where teams are productizing model work, prompt flows, or automation features."
    if "data" in normalized:
        return "Data roles usually follow analytics, pipeline, and warehouse-heavy teams."
    if "devops" in normalized:
        return "DevOps roles concentrate where infrastructure, deployment, and reliability work are active."
    if "mobile" in normalized:
        return "Mobile roles cluster around product teams shipping iOS and Android work at a steady cadence."
    return "The regional split is still a directional view of where this stack appears in the local job mix."


def _stack_context_reasons(
    *,
    group: str,
    mix_label: str,
    jobs: int,
    active_days: int,
    dominant_region: str,
    dominant_share: float,
    momentum_pct: float,
) -> list[str]:
    reasons = [
        f"{group} appears in {jobs} recent job mentions across {active_days} active days.",
        f"The dominant region is {dominant_region or 'Other'} at {dominant_share:.1f}% of this group's recent mentions.",
        f"Momentum versus the prior 30-day block is {momentum_pct:+.1f}%, which is why the trend line is tagged that way.",
    ]
    if mix_label:
        reasons.append(f"The most common signal mix is {mix_label}.")
    return reasons


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
    def _normalize_window_days(days: int) -> int:
        try:
            value = int(days)
        except Exception:
            value = 90
        return max(14, min(value, 180))

    @staticmethod
    def _normalize_top_n(top_n: int) -> int:
        try:
            value = int(top_n)
        except Exception:
            value = 6
        return max(3, min(value, 8))

    @staticmethod
    def _country_sql_filter(countries: list[str]) -> tuple[str, list[Any]]:
        selected = [str(country or "").strip() for country in countries if str(country or "").strip()]
        if not selected:
            return "", []
        parts = []
        params: list[Any] = []
        for country in selected:
            parts.append("LOWER(base_jobs.country) = ?")
            params.append(country.lower())
        return " AND (" + " OR ".join(parts) + ")", params

    @staticmethod
    def _dense_daily_language_series(
        *,
        date_start: str,
        date_end: str,
        top_languages: list[str],
        daily_rows: list[Any],
        daily_job_rows: list[Any],
    ) -> list[dict[str, Any]]:
        if not date_start or not date_end:
            return []
        language_map: dict[tuple[str, str], int] = {}
        for row in daily_rows:
            day_key = str(row["observed_date"] or "").strip()
            language = str(row["language"] or "").strip()
            if not day_key or not language:
                continue
            language_map[(day_key, language)] = int(row["jobs"] or 0)
        total_jobs_map = {
            str(row["observed_date"] or "").strip(): int(row["jobs"] or 0)
            for row in daily_job_rows
            if str(row["observed_date"] or "").strip()
        }
        cursor = datetime.fromisoformat(date_start).date()
        end = datetime.fromisoformat(date_end).date()
        series: list[dict[str, Any]] = []
        while cursor <= end:
            day_key = cursor.isoformat()
            languages = {
                language: int(language_map.get((day_key, language), 0))
                for language in top_languages
            }
            series.append(
                {
                    "date": day_key,
                    "job_total": int(total_jobs_map.get(day_key, 0)),
                    "languages": languages,
                }
            )
            cursor += timedelta(days=1)
        return series

    @staticmethod
    def _region_breakdown_by_language(
        *,
        top_languages: list[str],
        region_rows: list[Any],
        country_rows: list[Any],
    ) -> list[dict[str, Any]]:
        countries_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in country_rows:
            language = str(row["language"] or "").strip()
            region = str(row["region"] or "").strip() or "Other"
            country = str(row["country"] or "").strip() or "Unknown"
            countries_map.setdefault((language, region), []).append(
                {
                    "country": country,
                    "jobs": int(row["jobs"] or 0),
                }
            )

        regions_by_language: dict[str, list[dict[str, Any]]] = {language: [] for language in top_languages}
        for row in region_rows:
            language = str(row["language"] or "").strip()
            region = str(row["region"] or "").strip() or "Other"
            jobs = int(row["jobs"] or 0)
            countries = sorted(
                countries_map.get((language, region), []),
                key=lambda item: (-int(item["jobs"]), str(item["country"])),
            )[:4]
            regions_by_language.setdefault(language, []).append(
                {
                    "region": region,
                    "jobs": jobs,
                    "countries": countries,
                }
            )

        breakdown: list[dict[str, Any]] = []
        for language in top_languages:
            regions = sorted(
                regions_by_language.get(language, []),
                key=lambda item: (-int(item["jobs"]), str(item["region"])),
            )
            total_jobs = sum(int(item["jobs"]) for item in regions)
            shaped_regions = []
            for item in regions:
                jobs = int(item["jobs"])
                shaped_regions.append(
                    {
                        **item,
                        "share_pct": round((jobs / total_jobs) * 100, 2) if total_jobs > 0 else 0.0,
                    }
                )
            breakdown.append(
                {
                    "language": language,
                    "regions": shaped_regions,
                }
            )
        return breakdown

    def programming_language_hiring_trends(
        self,
        *,
        days: int = 90,
        top_n: int = 6,
        countries: list[str] | None = None,
    ) -> dict[str, Any]:
        window_days = self._normalize_window_days(days)
        top_limit = self._normalize_top_n(top_n)
        selected_countries = [str(country or "").strip() for country in (countries or []) if str(country or "").strip()]
        window_expr = f"-{max(0, window_days - 1)} day"
        country_filter_sql, country_params = self._country_sql_filter(selected_countries)

        observed_date_expr = "COALESCE(NULLIF(TRIM(jp.first_seen_date), ''), NULLIF(TRIM(jp.last_seen_date), ''))"
        parsed_country_expr = """
            COALESCE(
              NULLIF(TRIM(jle.normalized_country), ''),
              CASE
                WHEN INSTR(COALESCE(jp.location, ''), ',') > 0 THEN TRIM(SUBSTR(jp.location, INSTR(jp.location, ',') + 1))
                ELSE TRIM(COALESCE(jp.location, ''))
              END,
              'Unknown'
            )
        """
        region_expr = f"""
            COALESCE(
              NULLIF(TRIM(jle.normalized_region), ''),
              NULLIF(TRIM(grcm.normalized_region), ''),
              'Other'
            )
        """
        with self.db.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS temp.analytics_base_jobs")
            conn.execute("DROP TABLE IF EXISTS temp.analytics_language_jobs")
            conn.execute(
                f"""
                CREATE TEMP TABLE analytics_base_jobs AS
                SELECT DISTINCT
                  jp.id AS job_post_id,
                  {observed_date_expr} AS observed_date,
                  {parsed_country_expr} AS country,
                  {region_expr} AS region
                FROM job_posts jp
                LEFT JOIN job_location_enrichment jle ON jle.job_post_id = jp.id
                LEFT JOIN geo_region_country_map grcm
                  ON LOWER(TRIM(grcm.normalized_country)) = LOWER(TRIM({parsed_country_expr}))
                WHERE TRIM(COALESCE({observed_date_expr}, '')) <> ''
                  AND {observed_date_expr} >= date('now', ?)
                """,
                [window_expr],
            )
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_base_jobs_date ON analytics_base_jobs(observed_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_base_jobs_country ON analytics_base_jobs(country)")
            conn.execute(
                f"""
                CREATE TEMP TABLE analytics_language_jobs AS
                SELECT DISTINCT
                  analytics_base_jobs.job_post_id,
                  analytics_base_jobs.observed_date,
                  analytics_base_jobs.country,
                  analytics_base_jobs.region,
                  TRIM(jpl.language) AS language
                FROM analytics_base_jobs
                JOIN job_programming_languages jpl ON jpl.job_post_id = analytics_base_jobs.job_post_id
                WHERE TRIM(COALESCE(jpl.language, '')) <> ''
                {country_filter_sql.replace('base_jobs.', 'analytics_base_jobs.')}
                """,
                country_params,
            )
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_language_jobs_language ON analytics_language_jobs(language)")
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_language_jobs_date ON analytics_language_jobs(observed_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_language_jobs_region ON analytics_language_jobs(region)")

            top_rows = conn.execute(
                """
                SELECT
                  language,
                  COUNT(DISTINCT job_post_id) AS jobs,
                  COUNT(DISTINCT observed_date) AS active_days
                FROM analytics_language_jobs
                GROUP BY language
                ORDER BY jobs DESC, language ASC
                LIMIT ?
                """,
                [top_limit],
            ).fetchall()

            totals_row = conn.execute(
                """
                SELECT
                  COUNT(DISTINCT job_post_id) AS jobs_considered,
                  COUNT(DISTINCT language) AS unique_language_count,
                  MIN(observed_date) AS date_start,
                  MAX(observed_date) AS date_end
                FROM analytics_language_jobs
                """,
            ).fetchone()
            top_languages = [str(row["language"]) for row in top_rows]
            date_start = str(totals_row["date_start"] or "").strip() if totals_row else ""
            date_end = str(totals_row["date_end"] or "").strip() if totals_row else ""
            jobs_considered = int(totals_row["jobs_considered"] or 0) if totals_row else 0
            unique_language_count = int(totals_row["unique_language_count"] or 0) if totals_row else 0

            if not top_languages or not date_start or not date_end:
                return {
                    "window_days": window_days,
                    "selected_countries": selected_countries,
                    "generated_at": datetime.now(APP_TIMEZONE).isoformat(),
                    "date_start": date_start,
                    "date_end": date_end,
                    "jobs_considered": jobs_considered,
                    "language_mentions": 0,
                    "unique_language_count": unique_language_count,
                    "top_languages": [],
                    "daily_series": [],
                    "region_breakdown": [],
                    "regional_totals": [],
                    "geo_coverage": {"other_region_mentions": 0, "other_region_share_pct": 0.0},
                }

            placeholder = ",".join("?" for _ in top_languages)
            daily_rows = conn.execute(
                f"""
                SELECT
                  observed_date,
                  language,
                  COUNT(DISTINCT job_post_id) AS jobs
                FROM analytics_language_jobs
                WHERE language IN ({placeholder})
                GROUP BY observed_date, language
                ORDER BY observed_date ASC, language ASC
                """,
                top_languages,
            ).fetchall()
            daily_job_rows = conn.execute(
                """
                SELECT
                  observed_date,
                  COUNT(DISTINCT job_post_id) AS jobs
                FROM analytics_language_jobs
                GROUP BY observed_date
                ORDER BY observed_date ASC
                """,
            ).fetchall()
            region_rows = conn.execute(
                f"""
                SELECT
                  language,
                  region,
                  COUNT(DISTINCT job_post_id) AS jobs
                FROM analytics_language_jobs
                WHERE language IN ({placeholder})
                GROUP BY language, region
                ORDER BY language ASC, jobs DESC, region ASC
                """,
                top_languages,
            ).fetchall()
            country_rows = conn.execute(
                f"""
                SELECT
                  language,
                  region,
                  country,
                  COUNT(DISTINCT job_post_id) AS jobs
                FROM analytics_language_jobs
                WHERE language IN ({placeholder})
                GROUP BY language, region, country
                ORDER BY language ASC, jobs DESC, country ASC
                """,
                top_languages,
            ).fetchall()

        daily_series = self._dense_daily_language_series(
            date_start=date_start,
            date_end=date_end,
            top_languages=top_languages,
            daily_rows=daily_rows,
            daily_job_rows=daily_job_rows,
        )
        region_breakdown = self._region_breakdown_by_language(
            top_languages=top_languages,
            region_rows=region_rows,
            country_rows=country_rows,
        )
        region_lookup = {item["language"]: item["regions"] for item in region_breakdown}
        language_mentions = sum(int(row["jobs"] or 0) for row in top_rows)

        top_language_items: list[dict[str, Any]] = []
        regional_totals_map: dict[str, int] = {}
        other_region_mentions = 0
        end_date_obj = datetime.fromisoformat(date_end).date()
        recent_cutoff = (end_date_obj - timedelta(days=29)).isoformat()
        previous_cutoff = (end_date_obj - timedelta(days=59)).isoformat()
        for row in top_rows:
            language = str(row["language"])
            jobs = int(row["jobs"] or 0)
            regions = list(region_lookup.get(language, []))
            recent_30d_jobs = 0
            previous_30d_jobs = 0
            for point in daily_series:
                date_key = str(point["date"])
                current_jobs = int(point["languages"].get(language, 0))
                if date_key >= recent_cutoff:
                    recent_30d_jobs += current_jobs
                elif date_key >= previous_cutoff:
                    previous_30d_jobs += current_jobs
            momentum_delta = recent_30d_jobs - previous_30d_jobs
            momentum_pct = round((momentum_delta / previous_30d_jobs) * 100, 2) if previous_30d_jobs > 0 else (100.0 if recent_30d_jobs > 0 else 0.0)
            trend_direction = "up" if momentum_delta > 0 else ("down" if momentum_delta < 0 else "flat")
            dominant_region = regions[0] if regions else {"region": "Other", "jobs": 0, "share_pct": 0.0, "countries": []}
            for region in regions:
                regional_totals_map[region["region"]] = regional_totals_map.get(region["region"], 0) + int(region["jobs"])
            other_region_mentions += sum(int(region["jobs"]) for region in regions if str(region["region"]) == "Other")
            top_language_items.append(
                {
                    "language": language,
                    "jobs": jobs,
                    "share_pct": round((jobs / language_mentions) * 100, 2) if language_mentions > 0 else 0.0,
                    "active_days": int(row["active_days"] or 0),
                    "recent_30d_jobs": recent_30d_jobs,
                    "previous_30d_jobs": previous_30d_jobs,
                    "momentum_delta": momentum_delta,
                    "momentum_pct": momentum_pct,
                    "trend_direction": trend_direction,
                    "dominant_region": dominant_region["region"],
                    "dominant_region_jobs": int(dominant_region["jobs"]),
                    "dominant_region_share_pct": float(dominant_region["share_pct"]),
                    "region_spread": len(regions),
                }
            )

        regional_totals = [
            {
                "region": region,
                "jobs": jobs,
                "share_pct": round((jobs / language_mentions) * 100, 2) if language_mentions > 0 else 0.0,
            }
            for region, jobs in sorted(regional_totals_map.items(), key=lambda item: (-int(item[1]), str(item[0])))
        ]
        geo_coverage = {
            "other_region_mentions": other_region_mentions,
            "other_region_share_pct": round((other_region_mentions / language_mentions) * 100, 2) if language_mentions > 0 else 0.0,
        }
        return {
            "window_days": window_days,
            "selected_countries": selected_countries,
            "generated_at": datetime.now(APP_TIMEZONE).isoformat(),
            "date_start": date_start,
            "date_end": date_end,
            "jobs_considered": jobs_considered,
            "language_mentions": language_mentions,
            "unique_language_count": unique_language_count,
            "top_languages": top_language_items,
            "daily_series": daily_series,
            "region_breakdown": region_breakdown,
            "regional_totals": regional_totals,
            "geo_coverage": geo_coverage,
        }

    def programming_stack_hiring_trends(
        self,
        *,
        days: int = 90,
        top_n: int = 6,
        countries: list[str] | None = None,
    ) -> dict[str, Any]:
        window_days = self._normalize_window_days(days)
        top_limit = self._normalize_top_n(top_n)
        selected_countries = [str(country or "").strip() for country in (countries or []) if str(country or "").strip()]
        window_expr = f"-{max(0, window_days - 1)} day"
        country_filter_sql, country_params = self._country_sql_filter(selected_countries)

        observed_date_expr = "COALESCE(NULLIF(TRIM(jp.first_seen_date), ''), NULLIF(TRIM(jp.last_seen_date), ''))"
        parsed_country_expr = """
            COALESCE(
              NULLIF(TRIM(jle.normalized_country), ''),
              CASE
                WHEN INSTR(COALESCE(jp.location, ''), ',') > 0 THEN TRIM(SUBSTR(jp.location, INSTR(jp.location, ',') + 1))
                ELSE TRIM(COALESCE(jp.location, ''))
              END,
              'Unknown'
            )
        """
        region_expr = f"""
            COALESCE(
              NULLIF(TRIM(jle.normalized_region), ''),
              NULLIF(TRIM(grcm.normalized_region), ''),
              'Other'
            )
        """
        with self.db.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS temp.analytics_base_jobs")
            conn.execute("DROP TABLE IF EXISTS temp.analytics_stack_jobs")
            conn.execute(
                f"""
                CREATE TEMP TABLE analytics_base_jobs AS
                SELECT DISTINCT
                  jp.id AS job_post_id,
                  {observed_date_expr} AS observed_date,
                  {parsed_country_expr} AS country,
                  {region_expr} AS region
                FROM job_posts jp
                LEFT JOIN job_location_enrichment jle ON jle.job_post_id = jp.id
                LEFT JOIN geo_region_country_map grcm
                  ON LOWER(TRIM(grcm.normalized_country)) = LOWER(TRIM({parsed_country_expr}))
                WHERE TRIM(COALESCE({observed_date_expr}, '')) <> ''
                  AND {observed_date_expr} >= date('now', ?)
                """,
                [window_expr],
            )
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_base_jobs_date ON analytics_base_jobs(observed_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_base_jobs_country ON analytics_base_jobs(country)")
            conn.execute(
                f"""
                CREATE TEMP TABLE analytics_stack_jobs AS
                SELECT
                  analytics_base_jobs.job_post_id,
                  analytics_base_jobs.observed_date,
                  analytics_base_jobs.country,
                  analytics_base_jobs.region,
                  COALESCE(jp.title, '') AS title,
                  COALESCE(jp.company, '') AS company,
                  SUBSTR(COALESCE(jp.latest_payload_json, ''), 1, 4000) AS payload_json,
                  COALESCE(GROUP_CONCAT(DISTINCT TRIM(jpl.language)), '') AS languages_csv
                FROM analytics_base_jobs
                JOIN job_posts jp ON jp.id = analytics_base_jobs.job_post_id
                LEFT JOIN job_programming_languages jpl ON jpl.job_post_id = analytics_base_jobs.job_post_id
                WHERE (
                  TRIM(COALESCE(jp.title, '')) <> ''
                  OR TRIM(COALESCE(jp.latest_payload_json, '')) <> ''
                  OR TRIM(COALESCE(jpl.language, '')) <> ''
                )
                  {country_filter_sql.replace('base_jobs.', 'analytics_base_jobs.')}
                GROUP BY
                  analytics_base_jobs.job_post_id,
                  analytics_base_jobs.observed_date,
                  analytics_base_jobs.country,
                  analytics_base_jobs.region,
                  jp.title,
                  jp.company,
                  SUBSTR(COALESCE(jp.latest_payload_json, ''), 1, 4000)
                """,
                country_params,
            )
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_stack_jobs_date ON analytics_stack_jobs(observed_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS temp.ix_analytics_stack_jobs_region ON analytics_stack_jobs(region)")

            stack_rows = conn.execute(
                """
                SELECT
                  job_post_id,
                  observed_date,
                  country,
                  region,
                  title,
                  company,
                  payload_json,
                  languages_csv
                FROM analytics_stack_jobs
                ORDER BY observed_date ASC, job_post_id ASC
                """
            ).fetchall()

        classified_rows: list[dict[str, Any]] = []
        group_counts: Counter[str] = Counter()
        group_active_days: dict[str, set[str]] = {}
        group_mix_counts: dict[str, Counter[str]] = {}
        group_region_counts: dict[tuple[str, str], int] = {}
        group_country_counts: dict[tuple[str, str, str], int] = {}
        daily_group_counts: dict[tuple[str, str], int] = {}
        daily_job_counts: dict[str, int] = {}
        classified_jobs = 0
        other_jobs = 0

        for row in stack_rows:
            observed_date = str(row["observed_date"] or "").strip()
            if not observed_date:
                continue
            title = str(row["title"] or "").strip()
            payload_json = str(row["payload_json"] or "").strip()
            languages = [item.strip() for item in str(row["languages_csv"] or "").split(",") if item.strip()]
            text_blob = _stack_text_blob(title=title, payload_json=payload_json, languages=languages)
            scores = _stack_signal_scores(text_blob, languages)
            group = _stack_group_label(scores)
            mix_label = _stack_signal_mix(scores)
            if group != "Other":
                classified_jobs += 1
            else:
                other_jobs += 1
            group_counts[group] += 1
            group_active_days.setdefault(group, set()).add(observed_date)
            if mix_label:
                group_mix_counts.setdefault(group, Counter())[mix_label] += 1
            region = str(row["region"] or "").strip() or "Other"
            country = str(row["country"] or "").strip() or "Unknown"
            group_region_counts[(group, region)] = group_region_counts.get((group, region), 0) + 1
            group_country_counts[(group, region, country)] = group_country_counts.get((group, region, country), 0) + 1
            daily_group_counts[(observed_date, group)] = daily_group_counts.get((observed_date, group), 0) + 1
            daily_job_counts[observed_date] = daily_job_counts.get(observed_date, 0) + 1
            classified_rows.append(
                {
                    "job_post_id": int(row["job_post_id"] or 0),
                    "observed_date": observed_date,
                    "group": group,
                    "mix_label": mix_label,
                    "region": region,
                    "country": country,
                }
            )

        top_rows = [
            {"group": group, "jobs": jobs, "active_days": len(group_active_days.get(group, set()))}
            for group, jobs in sorted(
                group_counts.items(),
                key=lambda item: (-int(item[1]), STACK_GROUP_ORDER.get(str(item[0]), 99), str(item[0]).lower()),
            )[:top_limit]
        ]
        if not top_rows:
            return {
                "window_days": window_days,
                "selected_countries": selected_countries,
                "generated_at": datetime.now(APP_TIMEZONE).isoformat(),
                "date_start": "",
                "date_end": "",
                "jobs_considered": 0,
                "group_mentions": 0,
                "unique_group_count": 0,
                "classified_jobs": 0,
                "top_groups": [],
                "daily_series": [],
                "region_breakdown": [],
                "regional_totals": [],
                "geo_coverage": {"other_group_jobs": 0, "other_group_share_pct": 0.0},
                "crawl_recommendations": [],
            }

        date_start = min(daily_job_counts)
        date_end = max(daily_job_counts)
        jobs_considered = len(classified_rows)
        group_mentions = sum(group_counts.values())
        unique_group_count = len(group_counts)
        recent_cutoff = (datetime.fromisoformat(date_end).date() - timedelta(days=29)).isoformat()
        previous_cutoff = (datetime.fromisoformat(date_end).date() - timedelta(days=59)).isoformat()

        top_groups = [item["group"] for item in top_rows]
        daily_series: list[dict[str, Any]] = []
        cursor = datetime.fromisoformat(date_start).date()
        end = datetime.fromisoformat(date_end).date()
        while cursor <= end:
            day_key = cursor.isoformat()
            daily_series.append(
                {
                    "date": day_key,
                    "job_total": int(daily_job_counts.get(day_key, 0)),
                    "groups": {group: int(daily_group_counts.get((day_key, group), 0)) for group in top_groups},
                }
            )
            cursor += timedelta(days=1)

        region_breakdown: list[dict[str, Any]] = []
        regional_totals_map: dict[str, int] = {}
        for group in top_groups:
            region_rows = [
                (region, jobs)
                for (group_key, region), jobs in group_region_counts.items()
                if group_key == group
            ]
            region_rows.sort(key=lambda item: (-int(item[1]), str(item[0])))
            region_items: list[dict[str, Any]] = []
            total_jobs = sum(int(jobs) for _, jobs in region_rows)
            for region, jobs in region_rows:
                country_rows = [
                    {"country": country, "jobs": int(count)}
                    for (group_key, region_key, country), count in group_country_counts.items()
                    if group_key == group and region_key == region
                ]
                country_rows.sort(key=lambda item: (-int(item["jobs"]), str(item["country"])))
                region_items.append(
                    {
                        "region": region,
                        "jobs": int(jobs),
                        "countries": country_rows[:4],
                        "share_pct": round((int(jobs) / total_jobs) * 100, 2) if total_jobs > 0 else 0.0,
                    }
                )
                regional_totals_map[region] = regional_totals_map.get(region, 0) + int(jobs)
            region_breakdown.append({"group": group, "regions": region_items})

        top_group_items: list[dict[str, Any]] = []
        for row in top_rows:
            group = str(row["group"])
            jobs = int(row["jobs"] or 0)
            active_days = int(row["active_days"] or 0)
            regions = next((item["regions"] for item in region_breakdown if item["group"] == group), [])
            dominant_region = regions[0] if regions else {"region": "Other", "jobs": 0, "share_pct": 0.0, "countries": []}
            recent_30d_jobs = 0
            previous_30d_jobs = 0
            for point in daily_series:
                day_key = str(point["date"])
                current_jobs = int(point["groups"].get(group, 0))
                if day_key >= recent_cutoff:
                    recent_30d_jobs += current_jobs
                elif day_key >= previous_cutoff:
                    previous_30d_jobs += current_jobs
            momentum_delta = recent_30d_jobs - previous_30d_jobs
            momentum_pct = round((momentum_delta / previous_30d_jobs) * 100, 2) if previous_30d_jobs > 0 else (100.0 if recent_30d_jobs > 0 else 0.0)
            trend_direction = "up" if momentum_delta > 0 else ("down" if momentum_delta < 0 else "flat")
            top_mix_samples = [
                mix
                for mix, _count in group_mix_counts.get(group, Counter()).most_common(3)
            ]
            top_group_items.append(
                {
                    "group": group,
                    "jobs": jobs,
                    "share_pct": round((jobs / group_mentions) * 100, 2) if group_mentions > 0 else 0.0,
                    "active_days": active_days,
                    "recent_30d_jobs": recent_30d_jobs,
                    "previous_30d_jobs": previous_30d_jobs,
                    "momentum_delta": momentum_delta,
                    "momentum_pct": momentum_pct,
                    "trend_direction": trend_direction,
                    "dominant_region": dominant_region["region"],
                    "dominant_region_jobs": int(dominant_region["jobs"]),
                    "dominant_region_share_pct": float(dominant_region["share_pct"]),
                    "region_spread": len(regions),
                    "signal_mix_samples": top_mix_samples,
                }
            )

        regional_totals = [
            {
                "region": region,
                "jobs": jobs,
                "share_pct": round((jobs / group_mentions) * 100, 2) if group_mentions > 0 else 0.0,
            }
            for region, jobs in sorted(regional_totals_map.items(), key=lambda item: (-int(item[1]), str(item[0])))
        ]
        geo_coverage = {
            "other_group_jobs": other_jobs,
            "other_group_share_pct": round((other_jobs / jobs_considered) * 100, 2) if jobs_considered > 0 else 0.0,
        }
        sample_floor = max(8, top_limit * 2)
        crawl_recommendations = [
            {
                "group": item["group"],
                "jobs": item["jobs"],
                "reason": "This bucket is still thin, so additional crawl/backfill will make the trend less noisy.",
            }
            for item in top_group_items
            if item["group"] != "Other" and int(item["jobs"]) < sample_floor
        ]
        return {
            "window_days": window_days,
            "selected_countries": selected_countries,
            "generated_at": datetime.now(APP_TIMEZONE).isoformat(),
            "date_start": date_start,
            "date_end": date_end,
            "jobs_considered": jobs_considered,
            "group_mentions": group_mentions,
            "unique_group_count": unique_group_count,
            "classified_jobs": classified_jobs,
            "top_groups": top_group_items,
            "daily_series": daily_series,
            "region_breakdown": region_breakdown,
            "regional_totals": regional_totals,
            "geo_coverage": geo_coverage,
            "crawl_recommendations": crawl_recommendations,
        }

    @staticmethod
    def _decode_trend_ai_snapshot_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["summary_json"] = json.loads(item.get("summary_json") or "{}")
        item["result_json"] = json.loads(item.get("result_json") or "{}")
        return item

    def upsert_trend_ai_snapshot(
        self,
        *,
        cache_key: str,
        trend_kind: str,
        summary: dict[str, Any],
        result: dict[str, Any],
        model: str,
        source: str,
        cache_state: str,
        expires_at: str,
    ) -> dict[str, Any]:
        now = datetime.now(APP_TIMEZONE).replace(microsecond=0).isoformat()
        generated_at = str(result.get("generated_at") or now).strip() or now
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO analytics_trend_ai_snapshots (
                  cache_key, trend_kind, summary_json, result_json, model, source, cache_state,
                  generated_at, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  trend_kind = excluded.trend_kind,
                  summary_json = excluded.summary_json,
                  result_json = excluded.result_json,
                  model = excluded.model,
                  source = excluded.source,
                  cache_state = excluded.cache_state,
                  generated_at = excluded.generated_at,
                  expires_at = excluded.expires_at,
                  updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    trend_kind,
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                    model,
                    source,
                    cache_state,
                    generated_at,
                    expires_at,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM analytics_trend_ai_snapshots WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return self._decode_trend_ai_snapshot_row(row)

    def get_trend_ai_snapshot(self, cache_key: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM analytics_trend_ai_snapshots WHERE cache_key = ?",
                (str(cache_key or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_trend_ai_snapshot_row(row)

    def get_latest_trend_ai_snapshot(self, trend_kind: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM analytics_trend_ai_snapshots
                WHERE trend_kind = ?
                ORDER BY generated_at DESC, id DESC
                LIMIT 1
                """,
                (str(trend_kind or "").strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        return self._decode_trend_ai_snapshot_row(row)

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
