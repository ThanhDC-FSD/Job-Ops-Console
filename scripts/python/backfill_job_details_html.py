from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


DB_PATH = Path("apps/backend/app/job_ops_schema.sqlite")
HEADERS = {"User-Agent": "Mozilla/5.0"}
LANG_TOKENS = ["C++", "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C#"]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def node_text(node) -> str:
    return clean_text(node.get_text(" ", strip=True)) if node else ""


def parse_job(url: str, title: str, company: str, location: str) -> dict[str, Any]:
    r = requests.get(url, timeout=30, allow_redirects=True, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()

    parsed = {
        "status_code": r.status_code,
        "job_url_final": r.url,
        "title": title,
        "company": company,
        "location": location,
        "posted_time": "",
        "applicant_insight": "",
        "job_type_tags": [],
        "employment_type": "",
        "work_model": "",
        "jd": "",
        "full_page_text": node_text(soup.body),
        "languages": [],
        "error": "" if r.status_code == 200 else f"HTTP {r.status_code}",
    }

    meta_line = ""
    for p in soup.find_all("p"):
        line = node_text(p)
        if re.search(r"\s*[\u00b7\u2022]\s*", line) and (
            "ago" in line.lower() or "clicked apply" in line.lower() or "applicants" in line.lower()
        ):
            meta_line = line
            break
    if meta_line:
        parts = [clean_text(part) for part in re.split(r"\s*[\u00b7\u2022]\s*", meta_line) if clean_text(part)]
        if parts:
            parsed["location"] = parts[0]
        if len(parts) > 1:
            parsed["posted_time"] = parts[1]
        if len(parts) > 2:
            parsed["applicant_insight"] = " | ".join(parts[2:])

    criteria_items = [node_text(node) for node in soup.select("li.description__job-criteria-item")]
    for item in criteria_items:
        lower = item.lower()
        if lower.startswith("employment type "):
            parsed["employment_type"] = clean_text(item[len("Employment type ") :])
            if parsed["employment_type"]:
                parsed["job_type_tags"].append(parsed["employment_type"])
        elif lower.startswith("seniority level "):
            seniority = clean_text(item[len("Seniority level ") :])
            if seniority:
                parsed["job_type_tags"].append(seniority)
        elif any(tag in lower for tag in ["remote", "hybrid", "on-site", "onsite", "on site"]):
            parsed["work_model"] = item
            parsed["job_type_tags"].append(item)

    desc = (
        soup.select_one("div.show-more-less-html__markup")
        or soup.select_one(".show-more-less-html__markup")
        or soup.select_one(".jobs-description__content")
        or soup.select_one("#job-details")
    )
    parsed["jd"] = node_text(desc)
    lowered_jd = parsed["jd"].lower()
    for token in LANG_TOKENS:
        if token.lower() in lowered_jd:
            parsed["languages"].append(token)

    return parsed


def select_missing_jobs(conn: sqlite3.Connection, *, limit: int = 400, days: int | None = None) -> list[dict[str, Any]]:
    date_clause = ""
    params: list[Any] = []
    if days is not None and days > 0:
        date_clause = "AND (j.first_seen_date >= date('now', ?))"
        params.append(f"-{int(days)} days")
    params.append(int(limit))
    rows = conn.execute(
        f"""
        SELECT j.id, j.title, j.company, j.location, j.job_url, j.job_url_final, j.latest_payload_json
        FROM job_posts j
        WHERE
          (COALESCE(TRIM(j.latest_payload_json), '') = ''
           OR TRIM(j.latest_payload_json) LIKE '%HTTP 429%'
           OR TRIM(j.latest_payload_json) LIKE '%"jd": ""%')
          {date_clause}
        ORDER BY j.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def update_job(conn: sqlite3.Connection, job: dict[str, Any], parsed: dict[str, Any]) -> None:
    existing_payload_raw = job.get("latest_payload_json") or "{}"
    try:
        payload = json.loads(existing_payload_raw)
    except Exception:
        payload = {}

    payload.update(
        {
            "title": parsed["title"] or job.get("title") or "",
            "company": parsed["company"] or job.get("company") or "",
            "location": parsed["location"] or job.get("location") or "",
            "job_url_final": parsed["job_url_final"] or job.get("job_url_final") or job.get("job_url") or "",
            "posted_time": parsed["posted_time"],
            "applicant_insight": parsed["applicant_insight"],
            "job_type_tags": parsed["job_type_tags"],
            "jd": parsed["jd"],
            "jd_source": "manual_refetch_html",
            "full_page_text": parsed["full_page_text"],
            "error": parsed["error"],
        }
    )

    conn.execute(
        """
        UPDATE job_posts
        SET latest_payload_json = ?,
            latest_posted_time = ?,
            job_url_final = ?,
            normalized_work_model = ?,
            normalized_employment_type = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(payload, ensure_ascii=False),
            parsed["posted_time"],
            parsed["job_url_final"] or job.get("job_url_final") or job.get("job_url") or "",
            parsed["work_model"],
            parsed["employment_type"],
            datetime.now().replace(microsecond=0).isoformat(),
            int(job["id"]),
        ),
    )

    conn.execute(
        """
        INSERT INTO job_detail_validations (
          job_post_id, posted_time, linkedin_posted_date,
          applicant_insight, work_model, employment_type, programming_language,
          validation_backend, validation_model, created_at, updated_at
        ) VALUES (?, ?, '', ?, ?, ?, ?, 'manual_refetch_html', 'requests_bs4', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(job_post_id) DO UPDATE SET
          posted_time=excluded.posted_time,
          applicant_insight=excluded.applicant_insight,
          work_model=excluded.work_model,
          employment_type=excluded.employment_type,
          programming_language=excluded.programming_language,
          validation_backend=excluded.validation_backend,
          validation_model=excluded.validation_model,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            int(job["id"]),
            parsed["posted_time"],
            parsed["applicant_insight"],
            parsed["work_model"],
            parsed["employment_type"],
            ", ".join(parsed["languages"]),
        ),
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Backfill missing job details via LinkedIn guest HTML.")
    parser.add_argument("--limit", type=int, default=400, help="Max jobs to refetch")
    parser.add_argument("--days", type=int, default=None, help="Only jobs first_seen within N recent days")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    jobs = select_missing_jobs(conn, limit=args.limit, days=args.days)
    print(f"[INFO] Found {len(jobs)} jobs needing refetch")
    for idx, job in enumerate(jobs, start=1):
        url = job.get("job_url_final") or job.get("job_url") or ""
        if not url:
            continue
        try:
            parsed = parse_job(url, job.get("title", ""), job.get("company", ""), job.get("location", ""))
            update_job(conn, job, parsed)
            print(
                f"[{idx}/{len(jobs)}] job_id={job['id']} status={parsed['status_code']} "
                f"emp_type={parsed['employment_type']} work_model={parsed['work_model']} jd_len={len(parsed['jd'])}"
            )
            # be gentle with LinkedIn guest endpoints
            time.sleep(0.4)
        except Exception as exc:  # pragma: no cover - runtime safeguard
            print(f"[WARN] job_id={job['id']} failed: {exc}")
            time.sleep(0.2)
    conn.commit()
    conn.close()
    print("[INFO] Backfill complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
