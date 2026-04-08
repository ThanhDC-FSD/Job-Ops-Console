from __future__ import annotations

import base64
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .contracts import CandidateJob


def load_jobs(
    *,
    db_path: Path,
    cv_path: Path,
    limit: int,
    recent_days: int,
    job_ids: list[int],
    cv_text: str | None = None,
) -> list[CandidateJob]:
    """Load candidate jobs and JD text from SQLite."""
    if cv_text is None:
        cv_text = cv_path.read_text(encoding="utf-8", errors="ignore") if cv_path.exists() else ""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        params: list[Any] = []
        where_parts = ["COALESCE(TRIM(jjc.jd_text), '') <> ''"]
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            where_parts.append(f"jp.id IN ({placeholders})")
            params.extend(int(x) for x in job_ids)
        else:
            cutoff = (datetime.now().date() - timedelta(days=max(0, recent_days))).isoformat()
            where_parts.append("COALESCE(NULLIF(TRIM(jp.last_seen_date), ''), jp.first_seen_date) >= ?")
            params.append(cutoff)
        params.append(max(1, limit))
        rows = conn.execute(
            f"""
            SELECT
              jp.id,
              COALESCE(jp.title, '') AS title,
              COALESCE(jp.company, '') AS company,
              COALESCE(jp.location, '') AS location,
              COALESCE(jjc.jd_text, '') AS jd_text
            FROM job_posts jp
            JOIN (
              SELECT jo.job_post_id, MAX(jo.id) AS latest_observation_id
              FROM job_observations jo
              GROUP BY jo.job_post_id
            ) latest ON latest.job_post_id = jp.id
            JOIN job_jd_contents jjc ON jjc.observation_id = latest.latest_observation_id
            WHERE {" AND ".join(where_parts)}
            ORDER BY COALESCE(jp.last_seen_date, '') DESC, jp.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [
            CandidateJob(
                job_id=int(row["id"]),
                title=str(row["title"] or "").strip(),
                company=str(row["company"] or "").strip(),
                location=str(row["location"] or "").strip(),
                jd_text=str(row["jd_text"] or "").strip(),
                cv_text=cv_text,
            )
            for row in rows
        ]
    finally:
        conn.close()


def decode_jd_texts(encoded_texts: list[str]) -> list[str]:
    """Decode base64-encoded JD texts from CLI input."""
    decoded: list[str] = []
    for raw in encoded_texts or []:
        if not raw or not isinstance(raw, str):
            continue
        try:
            text = base64.b64decode(raw, validate=True).decode("utf-8", errors="ignore")
        except Exception:
            continue
        trimmed = str(text or "").strip()
        if trimmed:
            decoded.append(trimmed)
    return decoded


def custom_job_id(text: str, index: int) -> int:
    """Build a stable positive pseudo job id for custom JD inputs."""
    hashed = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    numeric = int(hashed, 16) if hashed else index
    candidate = (numeric & 0x7FFFFFFF) + index
    return candidate if candidate > 0 else index


def build_custom_jobs(jd_texts: list[str], cv_text: str) -> list[CandidateJob]:
    """Convert manual JD text inputs into synthetic job payloads."""
    jobs: list[CandidateJob] = []
    for idx, text in enumerate(jd_texts, start=1):
        jobs.append(
            CandidateJob(
                job_id=custom_job_id(text, idx),
                title=f"Custom JD #{idx}",
                company="Manual input",
                location="Manual input",
                jd_text=text,
                cv_text=cv_text,
            )
        )
    return jobs
