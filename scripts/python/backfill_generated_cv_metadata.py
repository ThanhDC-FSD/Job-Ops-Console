from __future__ import annotations

import logging
import re
import sqlite3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from logging_utils import setup_logging


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite"
RAW_CV_ROOT = PROJECT_ROOT / "input" / "Raw_CV"

logger = setup_logging("ETL.BackfillGeneratedCV", log_dir="etl_runs")


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _token_set(value: str) -> set[str]:
    return {part for part in _normalize(value).split() if part}


def _strip_tags(value: str) -> str:
    return re.sub(r"</?(bold|italic|green|orange|center|size:\d+)>", "", str(value or ""), flags=re.IGNORECASE).strip()


def _extract_headline(cv_text: str, fallback: str) -> str:
    lines = [_strip_tags(line) for line in str(cv_text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) >= 2:
        first = lines[0]
        second = lines[1]
        if first.upper() == first and ("|" in second or len(second.split()) >= 4):
            return second[:250]
    for line in lines:
        if "@" in line or "dob:" in line.lower():
            continue
        return line[:250]
    return str(fallback or "").strip()[:250]


def _extract_summary(cv_text: str) -> str:
    lines = [_strip_tags(line) for line in str(cv_text or "").splitlines()]
    lines = [line for line in lines if line]
    capture = False
    collected: list[str] = []
    for line in lines:
        lower = line.lower()
        if "professional summary" in lower:
            capture = True
            continue
        if capture and ("experience" in lower or "technical skills" in lower or "education" in lower):
            break
        if capture:
            collected.append(line)
    if collected:
        return " ".join(collected)[:4000]
    bullet_lines = [line.lstrip("- ").strip() for line in lines if line.strip().startswith("- ")]
    if bullet_lines:
        return " ".join(bullet_lines[:3])[:4000]
    return " ".join(lines[1:4] if len(lines) > 1 else lines[:4])[:4000]


def _extract_experience_summary(cv_text: str) -> str:
    lines = [_strip_tags(line) for line in str(cv_text or "").splitlines()]
    lines = [line for line in lines if line]
    in_work = False
    current_role = ""
    current_company = ""
    bullets: list[str] = []
    sections: list[tuple[str, str, list[str]]] = []
    for line in lines:
        lower = line.lower()
        if "work experience" in lower:
            in_work = True
            continue
        if not in_work:
            continue
        if "technical skills" in lower or "education" in lower:
            break
        if line.startswith("- "):
            bullets.append(line.lstrip("- ").strip())
            continue
        if "|" in line and not line.lower().startswith("http"):
            if current_role or bullets:
                sections.append((current_role, current_company, bullets[:]))
            parts = [part.strip() for part in line.split("|", 1)]
            current_role = parts[0]
            current_company = parts[1] if len(parts) > 1 else ""
            bullets = []
    if current_role or bullets:
        sections.append((current_role, current_company, bullets[:]))

    sentences: list[str] = []
    for role, company, role_bullets in sections:
        if not role_bullets:
            continue
        opening = f"At {company}, I worked as {role}" if company else f"I worked as {role}"
        chosen = role_bullets[:2]
        detail = "; ".join(bullet[:220].rstrip(".") for bullet in chosen)
        if detail:
            sentences.append(f"{opening}, where I {detail[0].lower() + detail[1:]}.")
    text = " ".join(sentences).strip()
    words = text.split()
    if len(words) > 300:
        text = " ".join(words[:300]).rstrip(" ,;:.") + "."
    return text[:6000]


def _score_folder(path: Path, company: str, title: str) -> int:
    name_tokens = _token_set(path.name)
    if not name_tokens:
        return 0
    company_tokens = _token_set(company)
    title_tokens = _token_set(title)
    score = len(name_tokens & title_tokens) * 3 + len(name_tokens & company_tokens) * 4
    cv_files = list(path.glob("CV_*.txt"))
    if cv_files:
        score += 5
    if list(path.glob("cover_letter_*.txt")):
        score += 2
    return score


def _find_best_raw_folder(company: str, title: str) -> Path | None:
    best_path: Path | None = None
    best_score = 0
    for path in RAW_CV_ROOT.iterdir():
        if not path.is_dir():
            continue
        score = _score_folder(path, company, title)
        if score > best_score:
            best_score = score
            best_path = path
    return best_path if best_score > 0 else None


def main() -> None:
    logger.info(
        "Backfill start | db=%s raw_cv_root=%s",
        DB_PATH,
        RAW_CV_ROOT,
        extra={"event": "start"},
    )
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")

    updated = 0
    scanned = 0

    rows = conn.execute(
        """
        SELECT
          jat.job_post_id,
          COALESCE(jat.cv_source_path, '') AS cv_source_path,
          COALESCE(jat.cover_letter_path, '') AS cover_letter_path,
          COALESCE(jat.generated_headline, '') AS generated_headline,
          COALESCE(jat.generated_summary, '') AS generated_summary,
          COALESCE(jat.generated_experience_summary, '') AS generated_experience_summary,
          COALESCE(jp.company, '') AS company,
          COALESCE(jp.title, '') AS title
        FROM job_application_tracking jat
        JOIN job_posts jp ON jp.id = jat.job_post_id
        WHERE COALESCE(jat.cv_source_path, '') <> ''
        """
    ).fetchall()

    for row in rows:
        scanned += 1
        current_cover = str(row["cover_letter_path"] or "").strip()
        current_headline = str(row["generated_headline"] or "").strip()
        current_summary = str(row["generated_summary"] or "").strip()
        current_experience_summary = str(row["generated_experience_summary"] or "").strip()
        if current_cover and current_headline and current_summary and current_experience_summary:
            continue

        cv_source_path = str(row["cv_source_path"] or "").strip()
        cv_path = Path(cv_source_path)
        raw_folder: Path | None = None
        cv_txt_path: Path | None = None

        if cv_path.suffix.lower() == ".txt" and cv_path.exists():
            cv_txt_path = cv_path
            raw_folder = cv_path.parent
        else:
            raw_folder = _find_best_raw_folder(str(row["company"] or ""), str(row["title"] or ""))
            if raw_folder is not None:
                txt_candidates = sorted(raw_folder.glob("CV_*.txt"))
                if txt_candidates:
                    cv_txt_path = txt_candidates[0]

        if raw_folder is None or cv_txt_path is None or not cv_txt_path.exists():
            continue

        cover_candidates = sorted(raw_folder.glob("cover_letter_*.txt"))
        cover_path = str(cover_candidates[0].resolve()) if cover_candidates else current_cover
        cv_text = cv_txt_path.read_text(encoding="utf-8", errors="ignore")
        headline = current_headline or _extract_headline(cv_text, fallback=str(row["title"] or ""))
        summary = current_summary or _extract_summary(cv_text)
        experience_summary = current_experience_summary or _extract_experience_summary(cv_text)

        conn.execute(
            """
            UPDATE job_application_tracking
            SET cover_letter_path = ?,
                generated_headline = ?,
                generated_summary = ?,
                generated_experience_summary = ?
            WHERE job_post_id = ?
            """,
            (
                cover_path,
                headline,
                summary,
                experience_summary,
                int(row["job_post_id"]),
            ),
        )
        updated += 1

    conn.commit()
    conn.close()
    logger.info(
        "Backfill complete | db=%s rows_scanned=%s rows_updated=%s",
        DB_PATH,
        scanned,
        updated,
        extra={"event": "complete"},
    )


if __name__ == "__main__":
    main()
