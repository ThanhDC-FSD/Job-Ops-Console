import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "backend"))

from app.services.programming_language_extractor import extract_programming_languages  # noqa: E402


INVALID_VALUES = {"", "-", "unknown", "n/a", "na", "none", "null"}


def _looks_like_fallback_jd(text: str) -> bool:
    sample = str(text or "").strip().lower()
    if not sample:
        return True
    return sample.startswith("job context (fallback jd):") or sample.startswith("fallback jd:")


def _compose_text(title: str, jd_text: str, payload_json: str) -> str:
    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        payload = {}

    payload_jd = "\n".join(
        [
            str(payload.get("jd", "") or "").strip(),
            str(payload.get("about_job", "") or "").strip(),
            str(payload.get("description", "") or "").strip(),
            str(payload.get("jobDescription", "") or "").strip(),
            str(payload.get("job_description", "") or "").strip(),
        ]
    ).strip()
    payload_text = "\n".join(
        [
            str(payload.get("descriptionText", "") or "").strip(),
            str(payload.get("requirements", "") or "").strip(),
            str(payload.get("skills", "") or "").strip(),
            str(payload.get("technologies", "") or "").strip(),
            str(payload.get("summary", "") or "").strip(),
            str(payload.get("details", "") or "").strip(),
            str(payload.get("content", "") or "").strip(),
            str(payload.get("about_company", "") or "").strip(),
        ]
    ).strip()
    if not payload_jd and not payload_text:
        payload_text = str(payload.get("full_page_text", "") or "").strip()
        lowered = payload_text.lower()
        stop_markers = ["people also viewed", "jobs you may be interested in", "similar jobs", "recommended for you"]
        cut_positions = [lowered.find(marker) for marker in stop_markers if lowered.find(marker) >= 0]
        if cut_positions:
            payload_text = payload_text[: min(cut_positions)].strip()

    primary_jd = str(jd_text or "").strip()
    if _looks_like_fallback_jd(primary_jd) and payload_jd:
        primary_jd = payload_jd
    text = primary_jd if len(primary_jd) >= 120 else "\n".join([primary_jd, payload_text]).strip()
    return text or "\n".join([title or "", primary_jd, payload_text]).strip()


def main() -> None:
    db_path = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    try:
        before_invalid = conn.execute(
            "SELECT COUNT(*) AS c FROM job_programming_languages WHERE LOWER(TRIM(COALESCE(language, ''))) IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')"
        ).fetchone()["c"]
        before_missing = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM job_posts jp
            LEFT JOIN job_programming_languages jpl
              ON jpl.job_post_id = jp.id
             AND LOWER(TRIM(COALESCE(jpl.language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            WHERE jpl.job_post_id IS NULL
            """
        ).fetchone()["c"]

        conn.execute(
            "DELETE FROM job_programming_languages WHERE LOWER(TRIM(COALESCE(language, ''))) IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')"
        )

        rows = conn.execute(
            """
            SELECT
              jp.id AS job_post_id,
              COALESCE(jp.title, '') AS title,
              COALESCE(jp.latest_payload_json, '') AS latest_payload_json,
              COALESCE(jjc.jd_text, '') AS jd_text,
              COALESCE(jp.updated_at, jp.created_at, ?) AS fallback_ts
            FROM job_posts jp
            LEFT JOIN (
              SELECT t.job_post_id, t.jd_text
              FROM job_jd_contents t
              JOIN (
                SELECT job_post_id, MAX(updated_at) AS max_updated_at
                FROM job_jd_contents
                GROUP BY job_post_id
              ) latest
                ON latest.job_post_id = t.job_post_id
               AND latest.max_updated_at = t.updated_at
            ) jjc ON jjc.job_post_id = jp.id
            ORDER BY jp.id
            """,
            (now_iso,),
        ).fetchall()

        updated_jobs = 0
        for row in rows:
            job_post_id = int(row["job_post_id"])
            source_text = _compose_text(
                str(row["title"] or ""),
                str(row["jd_text"] or ""),
                str(row["latest_payload_json"] or ""),
            )
            languages = extract_programming_languages(source_text, allow_unknown=False)
            languages = sorted({x.strip() for x in languages if x and x.strip() and x.strip().lower() not in INVALID_VALUES})

            existing = conn.execute(
                """
                SELECT language
                FROM job_programming_languages
                WHERE job_post_id = ?
                  AND LOWER(TRIM(COALESCE(language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
                """,
                (job_post_id,),
            ).fetchall()
            existing_langs = sorted({str(x["language"]).strip() for x in existing if str(x["language"]).strip()})
            final_langs = languages or existing_langs

            conn.execute("DELETE FROM job_programming_languages WHERE job_post_id = ?", (job_post_id,))
            for language in final_langs:
                conn.execute(
                    """
                    INSERT INTO job_programming_languages (
                      job_post_id, language, source, created_at, updated_at
                    ) VALUES (?, ?, 'rebuild_sqlite', ?, ?)
                    ON CONFLICT(job_post_id, language)
                    DO UPDATE SET
                      source = excluded.source,
                      updated_at = excluded.updated_at
                    """,
                    (job_post_id, language, str(row["fallback_ts"] or now_iso), now_iso),
                )
            if final_langs:
                updated_jobs += 1

        conn.commit()

        after_invalid = conn.execute(
            "SELECT COUNT(*) AS c FROM job_programming_languages WHERE LOWER(TRIM(COALESCE(language, ''))) IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')"
        ).fetchone()["c"]
        after_missing = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM job_posts jp
            LEFT JOIN job_programming_languages jpl
              ON jpl.job_post_id = jp.id
             AND LOWER(TRIM(COALESCE(jpl.language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            WHERE jpl.job_post_id IS NULL
            """
        ).fetchone()["c"]

        print(f"DB: {db_path}")
        print(f"jobs_updated_with_languages={updated_jobs}")
        print(f"invalid_rows: {before_invalid} -> {after_invalid}")
        print(f"jobs_without_languages: {before_missing} -> {after_missing}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
