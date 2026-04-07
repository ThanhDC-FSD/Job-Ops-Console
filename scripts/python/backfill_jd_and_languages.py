from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "backend"))

from app.services.programming_language_extractor import extract_programming_languages  # noqa: E402


INVALID_LANGUAGE_VALUES = {"", "-", "unknown", "n/a", "na", "none", "null"}
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: str) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _latest_crawl_run_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM crawl_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    now_iso = _now_iso()
    today = datetime.now(timezone.utc).date().isoformat()
    cur = conn.execute(
        """
        INSERT INTO crawl_runs (crawl_date, started_at, mode, source_url, input_jobs_json, max_jobs, output_json, output_csv, total_jobs)
        VALUES (?, ?, 'backfill', '', '', 0, '', '', 0)
        """,
        (today, now_iso),
    )
    return int(cur.lastrowid)


def _count_missing_jd(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM job_posts jp
            LEFT JOIN (
              SELECT job_post_id, MAX(id) AS max_id
              FROM job_jd_contents
              GROUP BY job_post_id
            ) latest ON latest.job_post_id = jp.id
            LEFT JOIN job_jd_contents jjc ON jjc.id = latest.max_id
            WHERE COALESCE(TRIM(jjc.jd_text), '') = ''
            """
        ).fetchone()["c"]
    )


def _count_missing_languages(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM job_posts jp
            LEFT JOIN job_programming_languages jpl
              ON jpl.job_post_id = jp.id
             AND LOWER(TRIM(COALESCE(jpl.language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            WHERE jpl.job_post_id IS NULL
            """
        ).fetchone()["c"]
    )


def _load_payload(payload_json: str) -> dict:
    try:
        payload = json.loads(str(payload_json or "{}"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _payload_richness_score(payload: dict) -> tuple[int, int, int]:
    jd_len = len(_clean_text(payload.get("jd", "")))
    about_len = len(_clean_text(payload.get("about_job", "")))
    full_len = len(_clean_text(payload.get("full_page_text", "")))
    return (max(jd_len, about_len), full_len, jd_len + about_len + full_len)


def _normalize_payload_candidate(key: str, value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if key == "full_page_text":
        lowered = text.lower()
        stop_markers = [
            "people also viewed",
            "jobs you may be interested in",
            "similar jobs",
            "recommended for you",
        ]
        cut_positions = [lowered.find(marker) for marker in stop_markers if lowered.find(marker) >= 0]
        if cut_positions:
            text = text[: min(cut_positions)].strip()
    return text


def _payload_jd_candidates(payload: dict) -> list[tuple[int, int, str, str]]:
    keys = [
        "jd",
        "about_job",
        "description",
        "jobDescription",
        "job_description",
        "descriptionText",
        "requirements",
        "skills",
        "technologies",
        "full_page_text",
    ]
    out: list[tuple[int, int, str, str]] = []
    for priority, key in enumerate(keys):
        value = _normalize_payload_candidate(key, payload.get(key, ""))
        if value and not _looks_like_fallback_jd(value):
            out.append((priority, -len(value), key, value))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _looks_like_fallback_jd(text: str) -> bool:
    sample = _clean_text(text).lower()
    if not sample:
        return True
    return sample.startswith("job context (fallback jd):") or sample.startswith("fallback jd:")


def _source_uses_full_page_text(source: str) -> bool:
    return "full_page_text" in str(source or "").strip().lower()


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


def _find_peer_jd(conn: sqlite3.Connection, job_id: int, role_signature: str, title: str, company: str) -> tuple[str, str]:
    if role_signature:
        row = conn.execute(
            """
            SELECT COALESCE(jjc.jd_text, '') AS jd_text, COALESCE(jjc.jd_source, '') AS jd_source
            FROM job_posts jp_cur
            JOIN job_posts jp_peer ON jp_peer.role_signature = jp_cur.role_signature AND jp_peer.id <> jp_cur.id
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
            (job_id,),
        ).fetchone()
        if row:
            return str(row["jd_text"]), f"peer_role_signature:{row['jd_source']}"
    if title and company:
        row = conn.execute(
            """
            SELECT COALESCE(jjc.jd_text, '') AS jd_text, COALESCE(jjc.jd_source, '') AS jd_source
            FROM job_posts jp_peer
            JOIN job_observations jo ON jo.job_post_id = jp_peer.id
            JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
            WHERE jp_peer.id <> ?
              AND COALESCE(LOWER(TRIM(jp_peer.title)), '') = COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(LOWER(TRIM(jp_peer.company)), '') = COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(TRIM(jjc.jd_text), '') <> ''
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
              AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
            ORDER BY jo.crawl_date DESC, jo.id DESC
            LIMIT 1
            """,
            (job_id, title, company),
        ).fetchone()
        if row:
            return str(row["jd_text"]), f"peer_title_company:{row['jd_source']}"
    if company:
        peers = conn.execute(
            """
            SELECT
              jp_peer.id,
              COALESCE(jp_peer.title, '') AS title,
              COALESCE(jjc.jd_text, '') AS jd_text,
              COALESCE(jjc.jd_source, '') AS jd_source
            FROM job_posts jp_peer
            JOIN job_observations jo ON jo.job_post_id = jp_peer.id
            JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
            WHERE jp_peer.id <> ?
              AND COALESCE(LOWER(TRIM(jp_peer.company)), '') = COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(TRIM(jjc.jd_text), '') <> ''
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
              AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
            ORDER BY jo.crawl_date DESC, jo.id DESC
            LIMIT 200
            """,
            (job_id, company),
        ).fetchall()
        best_peer = None
        best_score = 0
        for peer in peers:
            score = _title_overlap(title, str(peer["title"] or ""))
            if score > best_score:
                best_score = score
                best_peer = peer
        if best_peer is not None and best_score > 0:
            return str(best_peer["jd_text"]), f"peer_company_overlap:{best_peer['jd_source']}"
    return "", ""


def _ensure_observation_id(conn: sqlite3.Connection, job_id: int, latest_payload_json: str) -> int:
    row = conn.execute(
        """
        SELECT id
        FROM job_observations
        WHERE job_post_id = ?
        ORDER BY crawl_date DESC, id DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    if row:
        return int(row["id"])
    run_id = _latest_crawl_run_id(conn)
    now_iso = _now_iso()
    today = datetime.now(timezone.utc).date().isoformat()
    cur = conn.execute(
        """
        INSERT INTO job_observations (
          crawl_run_id, job_post_id, crawl_date, observed_at, posted_time, applicant_insight, row_json,
          is_duplicate_signature, duplicate_of_job_post_id
        ) VALUES (?, ?, ?, ?, '', '', ?, 0, NULL)
        """,
        (run_id, int(job_id), today, now_iso, str(latest_payload_json or "{}")),
    )
    return int(cur.lastrowid)


def _minimal_jd(title: str, company: str, location: str, job_url: str, posted: str) -> str:
    lines = [
        "Job context (fallback JD):",
        f"Title: {title or 'N/A'}",
        f"Company: {company or 'N/A'}",
        f"Location: {location or 'N/A'}",
        f"Posted: {posted or 'N/A'}",
        f"URL: {job_url or 'N/A'}",
    ]
    return "\n".join(lines)


def _title_heuristic_languages(title: str) -> list[str]:
    t = str(title or "").lower()
    if any(x in t for x in ["frontend", "front-end", "ui engineer"]):
        return ["JavaScript", "TypeScript", "HTML", "CSS"]
    if any(x in t for x in [".net", "asp.net", "dotnet"]):
        return ["C#"]
    if "node" in t:
        return ["JavaScript"]
    if "python" in t:
        return ["Python"]
    if "java" in t:
        return ["Java"]
    if "android" in t:
        return ["Kotlin", "Java"]
    if "ios" in t:
        return ["Swift"]
    if "devops" in t or "sre" in t:
        return ["Python"]
    return []


def _upsert_languages(conn: sqlite3.Connection, job_id: int, languages: list[str], source: str, now_iso: str) -> int:
    if not languages:
        return 0
    cleaned = sorted({x.strip() for x in languages if x and x.strip() and x.strip().lower() not in INVALID_LANGUAGE_VALUES})
    if not cleaned:
        return 0
    for lang in cleaned:
        conn.execute(
            """
            INSERT INTO job_programming_languages (job_post_id, language, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_post_id, language)
            DO UPDATE SET source = excluded.source, updated_at = excluded.updated_at
            """,
            (int(job_id), lang, source, now_iso, now_iso),
        )
    return len(cleaned)


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    now_iso = _now_iso()
    try:
        missing_jd_before = _count_missing_jd(conn)
        missing_lang_before = _count_missing_languages(conn)

        jobs = conn.execute(
            """
            SELECT
              jp.id,
              COALESCE(jp.role_signature, '') AS role_signature,
              COALESCE(jp.title, '') AS title,
              COALESCE(jp.company, '') AS company,
              COALESCE(jp.location, '') AS location,
              COALESCE(jp.latest_posted_time, '') AS latest_posted_time,
              COALESCE(jp.job_url_final, jp.job_url, '') AS job_url,
              COALESCE(jp.latest_payload_json, '') AS latest_payload_json,
              (
                SELECT jjc.id
                FROM job_jd_contents jjc
                WHERE jjc.job_post_id = jp.id
                ORDER BY jjc.updated_at DESC, jjc.id DESC
                LIMIT 1
              ) AS latest_jd_row_id
              ,
              (
                SELECT COALESCE(jjc.jd_text, '')
                FROM job_jd_contents jjc
                WHERE jjc.job_post_id = jp.id
                ORDER BY jjc.updated_at DESC, jjc.id DESC
                LIMIT 1
              ) AS latest_jd
              ,
              (
                SELECT COALESCE(jjc.jd_source, '')
                FROM job_jd_contents jjc
                WHERE jjc.job_post_id = jp.id
                ORDER BY jjc.updated_at DESC, jjc.id DESC
                LIMIT 1
              ) AS latest_jd_source
            FROM job_posts jp
            ORDER BY jp.id ASC
            """
        ).fetchall()

        jd_inserted = 0
        jd_repaired = 0
        jd_by_payload = 0
        jd_by_peer = 0
        jd_by_minimal = 0

        lang_rows_inserted = 0
        lang_jobs_updated = 0
        lang_by_extractor = 0
        lang_by_title = 0
        payload_repaired = 0

        for row in jobs:
            job_id = int(row["id"])
            title = str(row["title"] or "")
            company = str(row["company"] or "")
            location = str(row["location"] or "")
            job_url = str(row["job_url"] or "")
            posted = str(row["latest_posted_time"] or "")
            payload_json = str(row["latest_payload_json"] or "")
            payload = _load_payload(payload_json)

            latest_jd_row_id = int(row["latest_jd_row_id"]) if row["latest_jd_row_id"] is not None else 0
            latest_jd = str(row["latest_jd"] or "").strip()
            latest_jd_source = str(row["latest_jd_source"] or "").strip()
            current_source_uses_full_page = _source_uses_full_page_text(latest_jd_source)
            needs_jd_repair = not latest_jd or _looks_like_fallback_jd(latest_jd) or current_source_uses_full_page
            if needs_jd_repair:
                jd_text = ""
                jd_source = ""
                candidates = _payload_jd_candidates(payload)
                if candidates:
                    _, _, key, value = candidates[0]
                    if len(value) >= 120:
                        jd_text = value
                        jd_source = f"payload_fallback:{key}"
                        jd_by_payload += 1
                if not jd_text:
                    peer_jd, peer_source = _find_peer_jd(
                        conn,
                        job_id=job_id,
                        role_signature=str(row["role_signature"] or ""),
                        title=title,
                        company=company,
                    )
                    if peer_jd:
                        jd_text = peer_jd
                        jd_source = peer_source or "peer_fallback"
                        jd_by_peer += 1
                if not jd_text:
                    jd_text = _minimal_jd(title=title, company=company, location=location, job_url=job_url, posted=posted)
                    jd_source = "minimal_context_fallback"
                    jd_by_minimal += 1

                if latest_jd_row_id > 0 and latest_jd and (_looks_like_fallback_jd(latest_jd) or current_source_uses_full_page) and jd_source != "minimal_context_fallback":
                    conn.execute(
                        """
                        UPDATE job_jd_contents
                        SET jd_text = ?, jd_source = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (jd_text, jd_source, now_iso, latest_jd_row_id),
                    )
                    jd_repaired += 1
                    latest_jd = jd_text
                    latest_jd_source = jd_source
                elif not latest_jd:
                    obs_id = _ensure_observation_id(conn, job_id=job_id, latest_payload_json=payload_json)
                    conn.execute(
                        """
                        INSERT INTO job_jd_contents (observation_id, job_post_id, jd_text, jd_source, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (int(obs_id), int(job_id), jd_text, jd_source, now_iso, now_iso),
                    )
                    jd_inserted += 1
                    latest_jd = jd_text
                    latest_jd_source = jd_source

            payload_score = _payload_richness_score(payload)
            if latest_jd and payload_score[2] < 300:
                repaired_payload = dict(payload)
                repaired_payload["jd"] = latest_jd
                if latest_jd_source:
                    repaired_payload["jd_source"] = latest_jd_source
                if not _clean_text(str(repaired_payload.get("about_job", "") or "")):
                    repaired_payload["about_job"] = latest_jd
                conn.execute(
                    "UPDATE job_posts SET latest_payload_json = ? WHERE id = ?",
                    (json.dumps(repaired_payload, ensure_ascii=False), job_id),
                )
                payload = repaired_payload
                payload_repaired += 1

            has_language = conn.execute(
                """
                SELECT 1
                FROM job_programming_languages
                WHERE job_post_id = ?
                  AND LOWER(TRIM(COALESCE(language, ''))) NOT IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if has_language:
                continue

            payload_text = _clean_text(
                "\n".join(
                    [
                        str(payload.get("about_job", "") or ""),
                        str(payload.get("description", "") or ""),
                        str(payload.get("jobDescription", "") or ""),
                        str(payload.get("job_description", "") or ""),
                        str(payload.get("descriptionText", "") or ""),
                        str(payload.get("requirements", "") or ""),
                        str(payload.get("skills", "") or ""),
                        str(payload.get("technologies", "") or ""),
                    ]
                )
            )
            if not payload_text and not str(latest_jd or "").strip():
                payload_text = _clean_text(str(payload.get("full_page_text", "") or ""))
            primary_source = str(latest_jd or "").strip()
            source_text = primary_source if len(primary_source) >= 120 else "\n".join([title, primary_source, payload_text]).strip()
            langs = extract_programming_languages(source_text, allow_unknown=False)
            source_tag = "backfill_extractor"
            if not langs:
                langs = _title_heuristic_languages(title)
                source_tag = "backfill_title_heuristic"
            inserted = _upsert_languages(conn, job_id=job_id, languages=langs, source=source_tag, now_iso=now_iso)
            if inserted > 0:
                lang_rows_inserted += inserted
                lang_jobs_updated += 1
                if source_tag == "backfill_extractor":
                    lang_by_extractor += 1
                else:
                    lang_by_title += 1

        conn.commit()
        missing_jd_after = _count_missing_jd(conn)
        missing_lang_after = _count_missing_languages(conn)

        print(f"DB: {DB_PATH}")
        print(f"missing_jd: {missing_jd_before} -> {missing_jd_after}")
        print(
            "jd_backfilled="
            f"{jd_inserted} (payload={jd_by_payload}, peer={jd_by_peer}, minimal={jd_by_minimal})"
        )
        print(f"jd_repaired_from_fallback={jd_repaired}")
        print(f"missing_languages: {missing_lang_before} -> {missing_lang_after}")
        print(
            "languages_backfilled_jobs="
            f"{lang_jobs_updated} rows={lang_rows_inserted} "
            f"(extractor={lang_by_extractor}, title_heuristic={lang_by_title})"
        )
        print(f"payload_repaired={payload_repaired}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
