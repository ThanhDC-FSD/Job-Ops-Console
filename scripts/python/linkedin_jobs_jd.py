import argparse
import csv
import atexit
import logging
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from difflib import SequenceMatcher
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPTS_PY = PROJECT_ROOT / "scripts" / "python"
if str(SCRIPTS_PY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PY))
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from logging_utils import setup_logging
from evaluate_cv_fit import (
    constraint_score,
    domain_fit_score,
    evidence_quality_score,
    hard_constraint_check,
    keyword_coverage_score,
    strip_tags,
    technical_fit_score,
    tokenize,
    top_keywords,
    weighted_total,
)
from app.config import TUNING_ENABLE_CONTEXT_PACK
from app.services.cv_rewrite_service import CvRewriteService
from app.services.job_detail_validator import validate_job_details
from app.services.text_vector_utils import build_hashed_embedding, split_text_chunks

logger = setup_logging("Crawl.LinkedInJobsJD", log_dir="components")

DEFAULT_URL = (
    "https://www.linkedin.com/jobs/search/?currentJobId=4370161753&f_JT=P&f_WT=2&f_TPR=r2592000&"
    "geoId=92000000&keywords=Full%20Stack%20Engineer&origin="
    "JOB_SEARCH_PAGE_LOCATION_HISTORY&refresh=true"
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PROGRAMMING_LANGUAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Python", re.compile(r"\bpython\b", re.IGNORECASE)),
    ("JavaScript", re.compile(r"\bjavascript\b", re.IGNORECASE)),
    ("TypeScript", re.compile(r"\btypescript\b", re.IGNORECASE)),
    ("Java", re.compile(r"\bjava\b", re.IGNORECASE)),
    ("Go", re.compile(r"\bgolang\b|\bgo\b", re.IGNORECASE)),
    ("Rust", re.compile(r"\brust\b", re.IGNORECASE)),
    ("Kotlin", re.compile(r"\bkotlin\b", re.IGNORECASE)),
    ("Swift", re.compile(r"\bswift\b", re.IGNORECASE)),
    ("PHP", re.compile(r"\bphp\b", re.IGNORECASE)),
    ("Ruby", re.compile(r"\bruby\b", re.IGNORECASE)),
    ("Scala", re.compile(r"\bscala\b", re.IGNORECASE)),
    ("Dart", re.compile(r"\bdart\b", re.IGNORECASE)),
    ("C++", re.compile(r"\bc\+\+\b", re.IGNORECASE)),
    ("C#", re.compile(r"(?<!\w)c#(?!\w)|\bc-sharp\b|\bdotnet\b|\basp\.net\b|(?<!\w)\.net(?!\w)", re.IGNORECASE)),
    ("SQL", re.compile(r"\bsql\b|\bpostgres(?:ql)?\b|\bmysql\b|\bsqlite\b", re.IGNORECASE)),
    ("HTML", re.compile(r"\bhtml(?:5)?\b", re.IGNORECASE)),
    ("CSS", re.compile(r"\bcss(?:3)?\b", re.IGNORECASE)),
]

PROGRAMMING_TITLE_HINTS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\bfrontend\b|\bfront-end\b", re.IGNORECASE), ["JavaScript", "TypeScript", "HTML", "CSS"]),
    (re.compile(r"\breact\b|\bvue\b|\bangular\b", re.IGNORECASE), ["JavaScript", "TypeScript"]),
    (re.compile(r"\bnode(?:\.js)?\b", re.IGNORECASE), ["JavaScript"]),
    (re.compile(r"\b\.net\b|\basp\.net\b|\bdotnet\b", re.IGNORECASE), ["C#"]),
]

INVALID_PROGRAMMING_LANGUAGE_VALUES = {"", "-", "unknown", "n/a", "na", "none", "null"}
SQLITE_BUSY_RETRY_DELAYS = (0.25, 0.5, 1.0, 2.0, 3.0)
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
WORK_MODEL_KEYWORDS = {
    "remote": "remote",
    "hybrid": "hybrid",
    "on-site": "on_site",
    "on site": "on_site",
    "onsite": "on_site",
    "in-office": "on_site",
    "office-based": "on_site",
}
EMPLOYMENT_TYPE_KEYWORDS = {
    "full-time": "full_time",
    "full time": "full_time",
    "part-time": "part_time",
    "part time": "part_time",
    "freelance": "contract",
    "freelancer": "contract",
    "contract": "contract",
    "internship": "internship",
    "temporary": "temporary",
    "volunteer": "volunteer",
}
JOB_TYPE_TAG_NORMALIZATION = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "on-site": "On-site",
    "on site": "On-site",
    "onsite": "On-site",
    "full-time": "Full-time",
    "full time": "Full-time",
    "part-time": "Part-time",
    "part time": "Part-time",
    "contract": "Contract",
    "internship": "Internship",
    "temporary": "Temporary",
    "volunteer": "Volunteer",
    "entry level": "Entry level",
    "associate": "Associate",
    "mid-senior level": "Mid-senior level",
    "director": "Director",
    "executive": "Executive",
}
_RUN_LOCK_PATH: Path | None = None
_LOCK_STALE_SECONDS = 2 * 60 * 60  # expire stale locks after 2 hours
SYNC_CV_PROGRESS_INTERVAL_SECONDS = 15.0
SYNC_CV_DEFAULT_MAX_WORKERS = 4
PAUSE_EXIT_CODE = 2
PAUSE_DIR = PROJECT_ROOT / "tmp_seek_automation" / "pauses"
CHECKPOINT_DIR = PROJECT_ROOT / "tmp_seek_automation" / "checkpoints"
TUNING_SKIP_UNCHANGED_JOB_EMBEDDINGS = str(os.getenv("TUNING_SKIP_UNCHANGED_JOB_EMBEDDINGS", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
}

JD_CANDIDATE_KEYS: list[tuple[str, int]] = [
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
]


def _safe_console_text(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _safe_print(*args, **kwargs) -> None:
    sep = kwargs.pop("sep", " ")
    end = kwargs.pop("end", "\n")
    file = kwargs.pop("file", sys.stdout)
    flush = kwargs.pop("flush", False)
    text = sep.join(str(a) for a in args)
    file.write(_safe_console_text(text) + end)
    if flush:
        file.flush()


def _phase_print(phase: str, message: str) -> None:
    _safe_print(f"[PHASE] {phase} | {message}", flush=True)


def _release_run_lock() -> None:
    global _RUN_LOCK_PATH
    if _RUN_LOCK_PATH is None:
        return
    try:
        _RUN_LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    _RUN_LOCK_PATH = None


def _current_automation_run_id() -> str:
    return str(os.getenv("AUTOMATION_RUN_ID", "") or "").strip()


def _pause_flag_path(run_id: str) -> Path:
    return PAUSE_DIR / f"run_{run_id}.pause"


def _pause_requested() -> bool:
    run_id = _current_automation_run_id()
    if not run_id:
        return False
    return _pause_flag_path(run_id).exists()


def _checkpoint_path(action_type: str) -> Path:
    run_id = _current_automation_run_id() or "unknown"
    safe_action = str(action_type or "unknown").strip().lower()
    return CHECKPOINT_DIR / f"run_{run_id}_{safe_action}.json"


def _write_checkpoint(payload: dict) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_path("crawl_filtered")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _pause_and_exit(payload: dict, reason: str) -> None:
    payload = dict(payload)
    payload["pause_reason"] = reason
    payload["paused_at"] = _now_utc_iso()
    payload["run_id"] = _current_automation_run_id()
    checkpoint_path = _write_checkpoint(payload)
    _safe_print(f"[PAUSE] reason={reason} checkpoint={checkpoint_path}", flush=True)
    raise SystemExit(PAUSE_EXIT_CODE)


def _load_checkpoint(path: str) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid checkpoint payload")
    return data


def _read_lock_metadata(lock_path: Path) -> dict[str, str]:
    try:
        raw = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        raw = ""
    if not raw:
        return {"pid": "", "started_at": "", "run_id": ""}
    parts = [part.strip() for part in raw.split("|")]
    return {
        "pid": parts[0] if len(parts) >= 1 else "",
        "started_at": parts[1] if len(parts) >= 2 else "",
        "run_id": parts[2] if len(parts) >= 3 else "",
    }


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
            output = (result.stdout or "").strip()
            return bool(output) and "No tasks are running" not in output
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _acquire_run_lock(lock_name: str) -> None:
    global _RUN_LOCK_PATH
    lock_dir = PROJECT_ROOT / "tmp_seek_automation" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{lock_name}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _cleanup_stale_lock(lock_path):
            return _acquire_run_lock(lock_name)
        metadata = _read_lock_metadata(lock_path)
        details = []
        if metadata.get("run_id"):
            details.append(f"run_id={metadata['run_id']}")
        if metadata.get("pid"):
            details.append(f"pid={metadata['pid']}")
        if metadata.get("started_at"):
            details.append(f"started_at={metadata['started_at']}")
        detail_text = f" ({', '.join(details)})" if details else ""
        _safe_print(f"[LOCK] Another '{lock_name}' run is active{detail_text}. Skip overlapping execution.")
        raise SystemExit(0)
    run_id = _current_automation_run_id()
    with os.fdopen(fd, "w", encoding="utf-8", errors="ignore") as fh:
        fh.write(f"{os.getpid()}|{_now_utc_iso()}|{run_id}")
    _RUN_LOCK_PATH = lock_path
    atexit.register(_release_run_lock)


def _cleanup_stale_lock(lock_path: Path) -> bool:
    metadata = _read_lock_metadata(lock_path)
    if not any(metadata.values()):
        return False
    pid_text = metadata.get("pid", "")
    timestamp = metadata.get("started_at", "")
    if not timestamp:
        return False

    try:
        pid = int(pid_text)
    except Exception:
        pid = 0

    try:
        created = datetime.fromisoformat(timestamp)
    except Exception:
        return False

    now = datetime.now(timezone.utc)
    if pid > 0 and not _is_pid_running(pid):
        try:
            lock_path.unlink(missing_ok=True)
            _safe_print(f"[LOCK] Removed orphaned '{lock_path.name}' (pid={pid} not running).")
            return True
        except Exception:
            return False

    if (now - created).total_seconds() < _LOCK_STALE_SECONDS:
        return False

    try:
        lock_path.unlink(missing_ok=True)
        _safe_print(f"[LOCK] Removed stale '{lock_path.name}' (age>{_LOCK_STALE_SECONDS}s).")
        return True
    except Exception:
        return False


def _fix_mojibake(text: str) -> str:
    if not text:
        return text
    if not any(token in text for token in ("\u00e2", "\u00c2", "\u00c3", "\ufffd")):
        return text
    try:
        fixed = text.encode("latin1").decode("utf-8")
        if fixed.count("\ufffd") <= text.count("\ufffd"):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return text


def _clean_text(value: str) -> str:
    if not value:
        return ""
    text = unescape(value).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return _fix_mojibake(text)


def _clean_multiline(value: str) -> str:
    if not value:
        return ""
    text = unescape(value).replace("\xa0", " ").replace("\r", "")
    lines = [_clean_text(line) for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


LINKEDIN_NOISE_MARKERS = (
    "Similar jobs",
    "People also viewed",
    "Show more jobs like this",
    "Show fewer jobs like this",
    "Promoted by hirer",
    "Responses managed off LinkedIn",
    "Explore top content on LinkedIn",
)


def _trim_linkedin_detail_noise(text: str) -> str:
    cleaned = _clean_multiline(text)
    if not cleaned:
        return ""
    cutoff = len(cleaned)
    lowered = cleaned.lower()
    for marker in LINKEDIN_NOISE_MARKERS:
        idx = lowered.find(marker.lower())
        if idx != -1:
            cutoff = min(cutoff, idx)
    trimmed = cleaned[:cutoff].strip()
    return trimmed or cleaned


def extract_programming_languages_from_text(text: str) -> List[str]:
    sample = str(text or "").strip()
    if not sample:
        return []
    found: List[str] = []
    for language, pattern in PROGRAMMING_LANGUAGE_PATTERNS:
        if pattern.search(sample):
            found.append(language)
    if not found:
        for pattern, hinted in PROGRAMMING_TITLE_HINTS:
            if pattern.search(sample):
                found.extend(hinted)
    unique = sorted({x.strip() for x in found if x and x.strip()})
    return [x for x in unique if x.lower() not in INVALID_PROGRAMMING_LANGUAGE_VALUES]


def fallback_programming_languages_from_title(title: str) -> List[str]:
    sample = str(title or "").strip().lower()
    if not sample:
        return []
    if any(k in sample for k in ("frontend", "front-end", "ui engineer", "web developer")):
        return ["JavaScript", "TypeScript", "HTML", "CSS"]
    if any(k in sample for k in (".net", "asp.net", "dotnet")):
        return ["C#"]
    if "node" in sample:
        return ["JavaScript"]
    if "python" in sample:
        return ["Python"]
    if "java" in sample:
        return ["Java"]
    if any(k in sample for k in ("devops", "sre")):
        return ["Python"]
    if any(k in sample for k in ("android",)):
        return ["Kotlin", "Java"]
    if any(k in sample for k in ("ios", "swift")):
        return ["Swift"]
    return []


def _text(node) -> str:
    return _clean_text(node.get_text(" ", strip=True)) if node else ""


def _extract_job_id(job_url: str) -> str:
    if not job_url:
        return ""
    parsed = urlparse(job_url)
    path = parsed.path or ""

    m = re.search(r"-(\d{7,})$", path)
    if m:
        return m.group(1)

    parts = path.rstrip("/").split("/")
    if parts and parts[-1].isdigit():
        return parts[-1]

    m = re.search(r"/jobPosting/(\d+)", path)
    if m:
        return m.group(1)

    qs = parse_qs(parsed.query)
    return qs.get("currentJobId", [""])[0]


def _canonical_job_id(*values: str) -> str:
    for value in values:
        job_id = _extract_job_id(str(value or "").strip())
        if job_id:
            return str(job_id)
        text = str(value or "").strip()
        if text.isdigit():
            return text
    return ""


def _canonical_job_url(*values: str) -> str:
    job_id = _canonical_job_id(*values)
    if job_id:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_job_type_values(row: Dict[str, Any]) -> tuple[str, str]:
    values: List[str] = []
    priority_values: List[str] = []
    raw_tags = row.get("job_type_tags")
    if isinstance(raw_tags, list):
        for x in raw_tags:
            token = str(x or "").strip().lower()
            if token:
                values.append(token)
                priority_values.append(token)
    about_sections = row.get("about_job_sections")
    if isinstance(about_sections, dict):
        for section_name, section_value in about_sections.items():
            values.append(str(section_name or "").strip().lower())
            if isinstance(section_value, list):
                values.extend(str(x or "").strip().lower() for x in section_value)
            elif section_value not in (None, ""):
                values.append(str(section_value).strip().lower())
    for key in ("employment_type", "workplace_type", "work_type", "work_model"):
        value = row.get(key)
        if isinstance(value, list):
            for x in value:
                token = str(x or "").strip().lower()
                if token:
                    values.append(token)
                    priority_values.append(token)
        elif value not in (None, ""):
            token = str(value).strip().lower()
            if token:
                values.append(token)
                priority_values.append(token)
    for key in (
        "description",
        "about_job",
        "jd",
        "meta_description",
        "og_description",
        "twitter_description",
        "full_page_text",
        "title",
    ):
        value = row.get(key)
        if isinstance(value, list):
            values.extend(str(x or "").strip().lower() for x in value)
        elif value not in (None, ""):
            values.append(str(value).strip().lower())
    sample = " \n ".join(v for v in values if v)
    priority_sample = " \n ".join(v for v in priority_values if v)
    work_model = ""
    employment_type = ""
    if not work_model:
        explicit_work_match = re.search(
            r"(?:workplace|workplace type|work model|work mode)\s*[:\n ]+\s*(on[- ]?site|hybrid|remote)",
            sample,
            flags=re.IGNORECASE,
        )
        if explicit_work_match:
            work_token = explicit_work_match.group(1).strip().lower()
            if work_token in {"on-site", "on site", "onsite"}:
                work_model = "on_site"
            elif work_token in {"hybrid", "remote"}:
                work_model = work_token
    if not work_model and priority_sample:
        for token, normalized in WORK_MODEL_KEYWORDS.items():
            if token in priority_sample:
                work_model = normalized
                break
    for token, normalized in WORK_MODEL_KEYWORDS.items():
        if work_model:
            break
        if token in sample and token != "remote":
            work_model = normalized
            break
    if not work_model and "this position is based in" in sample:
        if not any(token in sample for token in ("remote", "hybrid", "work from home", "wfh", "telecommute")):
            work_model = "on_site"
    if not employment_type:
        explicit_employment_match = re.search(
            r"(?:employment type|job type)\s*[:\n ]+\s*(full[- ]?time|part[- ]?time|contract|internship|temporary|volunteer)",
            sample,
            flags=re.IGNORECASE,
        )
        if explicit_employment_match:
            employment_token = explicit_employment_match.group(1).strip().lower().replace(" ", "-")
            employment_type = EMPLOYMENT_TYPE_KEYWORDS.get(employment_token, "")
    if not employment_type and priority_sample:
        for token, normalized in EMPLOYMENT_TYPE_KEYWORDS.items():
            if token in priority_sample:
                employment_type = normalized
                break
    for token, normalized in EMPLOYMENT_TYPE_KEYWORDS.items():
        if employment_type:
            break
        if token in sample:
            employment_type = normalized
            break
    return work_model, employment_type


def _detect_easy_apply(row: Dict[str, Any]) -> int:
    values: List[str] = []
    for key in ("apply_url", "about_job", "jd", "full_page_text", "title"):
        value = row.get(key)
        if value not in (None, ""):
            values.append(str(value).strip().lower())
    raw_tags = row.get("job_type_tags")
    if isinstance(raw_tags, list):
        values.extend(str(x or "").strip().lower() for x in raw_tags)
    sample = " \n ".join(v for v in values if v)
    if "easy apply" in sample:
        return 1
    apply_url = str(row.get("apply_url") or "").strip().lower()
    if "linkedin.com" in apply_url or "onsiteapply" in apply_url or "easyapply" in apply_url:
        return 1
    return 0


def _with_recent_window(search_url: str, window_days: int) -> str:
    parsed = urlparse(search_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["f_TPR"] = [f"r{max(1, window_days) * 86400}"]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _apply_company_search_filter(search_url: str, company_filter: str) -> str:
    cleaned = _clean_text(company_filter)
    if not cleaned:
        return search_url
    parsed = urlparse(search_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["keywords"] = [cleaned]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _parse_posted_age_days(posted_time: str) -> Optional[int]:
    if not posted_time:
        return None
    t = _clean_text(posted_time).lower()
    t = t.replace("reposted", "").strip()

    if t in {"just now", "today"}:
        return 0
    if t == "yesterday":
        return 1

    m_plus = re.search(r"(\d+)\+\s*days?\s*ago", t)
    if m_plus:
        return int(m_plus.group(1))

    m = re.search(r"(\d+)\s*(hour|day|week|month|year)s?\s*ago", t)
    if not m:
        return None

    value = int(m.group(1))
    unit = m.group(2)
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


def _filter_recent_rows(rows: List[Dict[str, Any]], window_days: int) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        days = _parse_posted_age_days(str(row.get("posted_time", "")))
        # Keep rows with unknown posted_time because some pages don't expose this field reliably.
        if days is None or days <= window_days:
            filtered.append(row)
    return filtered


def _normalize_company_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _company_filter_match(company: str, needle: str) -> bool:
    if not needle:
        return True
    hay = _normalize_company_text(company)
    target = _normalize_company_text(needle)
    return target in hay


def extract_job_cards_playwright(page) -> List[Dict[str, str]]:
    page.wait_for_selector("ul.scaffold-layout__list-container li", timeout=30000)
    cards = page.locator("ul.scaffold-layout__list-container li")
    jobs: List[Dict[str, str]] = []

    for i in range(cards.count()):
        card = cards.nth(i)
        link = card.locator("a.job-card-container__link").first
        href = link.get_attribute("href") or ""
        title = (card.locator(".job-card-list__title").first.inner_text() or "").strip()
        company = (card.locator(".job-card-container__company-name").first.inner_text() or "").strip()
        location = (card.locator(".job-card-container__metadata-item").first.inner_text() or "").strip()

        if href and href.startswith("/"):
            href = f"https://www.linkedin.com{href}"

        jobs.append(
            {
                "index": str(i),
                "title": title,
                "company": company,
                "location": location,
                "job_url": href,
            }
        )
    return jobs


def extract_jd_for_card_playwright(page, idx: int) -> Dict[str, str]:
    card = page.locator("ul.scaffold-layout__list-container li").nth(idx)
    card.click(timeout=15000)

    page.wait_for_timeout(1800)
    desc_selectors = [
        ".jobs-description__content",
        "#job-details",
        ".jobs-box__html-content",
        ".jobs-description-content__text",
    ]

    jd_text = ""
    for selector in desc_selectors:
        node = page.locator(selector).first
        try:
            if node.is_visible(timeout=3000):
                jd_text = (node.inner_text() or "").strip()
                if jd_text:
                    break
        except PlaywrightTimeoutError:
            continue

    return {"jd": jd_text}


def extract_job_cards_api(session: requests.Session, search_url: str, max_jobs: int) -> List[Dict[str, str]]:
    parsed = urlparse(search_url)
    query_pairs = parse_qs(parsed.query)
    params = {k: v[0] for k, v in query_pairs.items() if v}

    collected: List[Dict[str, str]] = []
    start = 0
    page_size = 25

    while len(collected) < max_jobs:
        params["start"] = str(start)
        resp = session.get(
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search/",
            params=params,
            timeout=30,
        )
        if resp.status_code != 200 or not resp.text.strip():
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("li")
        if not cards:
            break

        for card in cards:
            link_node = card.select_one("a.base-card__full-link")
            title_node = card.select_one("h3.base-search-card__title")
            company_node = card.select_one("h4.base-search-card__subtitle")
            location_node = card.select_one("span.job-search-card__location")

            href = (link_node.get("href", "") if link_node else "").strip()
            if href.startswith("/"):
                href = f"https://www.linkedin.com{href}"
            if not href:
                continue

            collected.append(
                {
                    "index": str(len(collected)),
                    "title": _text(title_node),
                    "company": _text(company_node),
                    "location": _text(location_node),
                    "job_url": href,
                }
            )
            if len(collected) >= max_jobs:
                break

        start += page_size
        time.sleep(0.5)

    return collected


def extract_jd_for_card_api(session: requests.Session, job_url: str) -> Dict[str, str]:
    job_id = _extract_job_id(job_url)
    if not job_id:
        return {"jd": "", "error": "Could not parse job id"}

    detail_resp = session.get(
        f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
        timeout=30,
    )
    if detail_resp.status_code != 200:
        return {"jd": "", "error": f"HTTP {detail_resp.status_code}"}

    soup = BeautifulSoup(detail_resp.text, "html.parser")
    desc_node = (
        soup.select_one("div.show-more-less-html__markup")
        or soup.select_one("div.description__text")
        or soup.select_one("section.show-more-less-html")
    )
    return {"jd": _text(desc_node)}


def parse_about_sections(about_text: str) -> Dict[str, Any]:
    lines = [line.strip() for line in about_text.splitlines() if line.strip()]
    sections: Dict[str, Any] = {}
    current: Optional[str] = None
    current_lines: List[str] = []

    def flush_current() -> None:
        nonlocal current, current_lines
        if not current:
            return
        if len(current_lines) == 1:
            sections[current] = current_lines[0]
        elif current_lines:
            sections[current] = current_lines
        else:
            sections[current] = ""
        current = None
        current_lines = []

    named_headers = {
        "Description",
        "Required",
        "WFH Set-Up",
        "Your Superpowers",
        "Work Setup",
        "Working Hours",
        "Compensation",
        "Benefits",
        "Why does this role exist?",
        "The Impact you'll make",
        "Skills, Knowledge and Expertise",
    }

    for line in lines:
        kv_match = re.match(r"^([A-Za-z][A-Za-z0-9 /&()'\-]{1,50}):\s*(.+)$", line)
        heading_match = line.endswith(":") and len(line) <= 90

        if kv_match:
            flush_current()
            sections[kv_match.group(1).strip()] = kv_match.group(2).strip()
            continue

        if heading_match:
            flush_current()
            current = line[:-1].strip()
            continue

        if line in named_headers:
            flush_current()
            current = line
            continue

        if current:
            current_lines.append(line)
        else:
            sections.setdefault("_intro", [])
            sections["_intro"].append(line)

    flush_current()
    if "_intro" in sections and len(sections["_intro"]) == 1:
        sections["_intro"] = sections["_intro"][0]
    return sections


def _collect_job_type_tags_from_text(*texts: str) -> List[str]:
    tags: List[str] = []
    for raw_text in texts:
        text = _clean_text(raw_text)
        if not text:
            continue
        parts = [text]
        parts.extend(
            part.strip()
            for part in re.split(r"[\n\r\u00b7\u2022|,/]+", text)
            if part and part.strip()
        )
        for part in parts:
            normalized = re.sub(r"\s+", " ", part).strip().lower()
            if not normalized:
                continue
            canonical = JOB_TYPE_TAG_NORMALIZATION.get(normalized)
            if canonical and canonical not in tags:
                tags.append(canonical)
    return tags


def _extract_job_type_tags_from_full_page_text(full_page_text: str) -> List[str]:
    if not full_page_text:
        return []
    text = _clean_multiline(full_page_text)
    lowered = text.lower()
    tags = _collect_job_type_tags_from_text(text)

    work_match = re.search(
        r"(?:workplace|workplace type|work model|work mode)\s*[:\n ]+\s*(on[- ]?site|hybrid|remote)",
        lowered,
        flags=re.IGNORECASE,
    )
    if work_match:
        tags.extend(_collect_job_type_tags_from_text(work_match.group(1)))

    employment_match = re.search(
        r"(?:employment type|job type)\s*[:\n ]+\s*(full[- ]?time|part[- ]?time|contract|internship|temporary|volunteer)",
        lowered,
        flags=re.IGNORECASE,
    )
    if employment_match:
        tags.extend(_collect_job_type_tags_from_text(employment_match.group(1)))

    deduped: List[str] = []
    for tag in tags:
        if tag not in deduped:
            deduped.append(tag)
    return deduped


def extract_job_details_from_url(
    session: requests.Session,
    job_url: str,
    title_fallback: str = "",
    company_fallback: str = "",
    location_fallback: str = "",
) -> Dict[str, Any]:
    job_id = _extract_job_id(job_url)
    result: Dict[str, Any] = {
        "job_id": job_id,
        "job_url_final": "",
        "title": title_fallback,
        "company": company_fallback,
        "location": location_fallback,
        "posted_time": "",
        "applicant_insight": "",
        "response_note": "",
        "job_type_tags": [],
        "apply_url": "",
        "about_job": "",
        "about_job_sections": {},
        "about_company": "",
        "description": "",
        "meta_description": "",
        "og_description": "",
        "twitter_description": "",
        "full_page_text": "",
        "jd": "",
        "jd_source": "",
        "error": "",
    }
    if not job_url:
        result["error"] = "Missing job_url"
        return result

    # Prefer per-job API first.
    api_fallback = extract_jd_for_card_api(session, job_url)
    if api_fallback.get("jd"):
        result["jd"] = api_fallback["jd"]
        result["jd_source"] = "api_jobPosting"
    elif api_fallback.get("error"):
        result["error"] = api_fallback["error"]

    try:
        resp = session.get(job_url, timeout=30, allow_redirects=True)
    except requests.RequestException as e:
        result["error"] = str(e)
        return result

    result["job_url_final"] = _canonical_job_url(str(resp.url), job_url, str(result.get("job_id", "")))
    if resp.status_code != 200:
        result["error"] = f"HTTP {resp.status_code}"
        return result

    soup = BeautifulSoup(resp.text, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()

    meta_description = _clean_multiline(
        str((soup.find("meta", attrs={"name": "description"}) or {}).get("content", "") or "")
    )
    og_description = _clean_multiline(
        str((soup.find("meta", attrs={"property": "og:description"}) or {}).get("content", "") or "")
    )
    twitter_description = _clean_multiline(
        str((soup.find("meta", attrs={"name": "twitter:description"}) or {}).get("content", "") or "")
    )
    if meta_description:
        result["meta_description"] = meta_description
    if og_description:
        result["og_description"] = og_description
    if twitter_description:
        result["twitter_description"] = twitter_description

    title_node = soup.find("h1")
    if not title_node:
        title_node = next(
            (
                p
                for p in soup.find_all(["h1", "h2", "p"])
                if 8 <= len(_text(p)) <= 140
                and any(k in _text(p).lower() for k in ["engineer", "developer", "manager", "analyst", "designer"])
            ),
            None,
        )
    if title_node:
        result["title"] = _text(title_node)

    company_node = soup.select_one('[aria-label^="Company,"] a') or soup.select_one('a[href*="/company/"]')
    if company_node:
        result["company"] = _text(company_node)

    meta_line = ""
    for p in soup.find_all("p"):
        line = _text(p)
        if re.search(r"\s*[\u00b7\u2022]\s*", line) and (
            "ago" in line.lower() or "clicked apply" in line.lower() or "applicants" in line.lower()
        ):
            meta_line = line
            break
    if meta_line:
        parts = [_clean_text(part) for part in re.split(r"\s*[\u00b7\u2022]\s*", meta_line) if _clean_text(part)]
        if parts:
            result["location"] = parts[0]
        if len(parts) > 1:
            result["posted_time"] = parts[1]
        if len(parts) > 2:
            result["applicant_insight"] = " | ".join(parts[2:])

    note_node = next(
        (node for node in soup.find_all(["p", "span"]) if "responses managed off linkedin" in _text(node).lower()),
        None,
    )
    if note_node:
        result["response_note"] = _text(note_node)

    desc_node = (
        soup.select_one("div.show-more-less-html__markup")
        or soup.select_one(".show-more-less-html__markup")
        or soup.select_one(".jobs-description__content")
        or soup.select_one("#job-details")
        or soup.select_one(".jobs-box__html-content")
        or soup.select_one(".jobs-description-content__text")
    )
    if desc_node is not None:
        detail_text = _clean_multiline(desc_node.get_text("\n", strip=True))
        if detail_text:
            result["description"] = detail_text
            if not result["about_job"]:
                result["about_job"] = detail_text
                result["about_job_sections"] = parse_about_sections(detail_text)
            if not result["jd"] or len(detail_text) > len(str(result.get("jd", "") or "")):
                result["jd"] = detail_text
                result["jd_source"] = "job_url_html_detail"

    tags: List[str] = []
    for node in soup.find_all(["button", "span", "li", "p"]):
        t = _text(node)
        if not t or len(t) > 120:
            continue
        for tag in _collect_job_type_tags_from_text(t):
            if tag not in tags:
                tags.append(tag)
    result["job_type_tags"] = tags

    for a in soup.find_all("a", href=True):
        label = _clean_text(a.get("aria-label", "")).lower()
        text = _text(a).lower()
        if label.startswith("apply") or text == "apply":
            result["apply_url"] = urljoin(str(resp.url), a["href"])
            break

    about_heading = next((h for h in soup.find_all(["h2", "h3"]) if _text(h).lower() == "about the job"), None)
    if about_heading:
        box = about_heading.find_next(attrs={"data-testid": "expandable-text-box"})
        if box is None:
            box = about_heading.find_next("span")
        if box is not None:
            about_text = _clean_multiline(box.get_text("\n", strip=True))
            result["about_job"] = about_text
            result["about_job_sections"] = parse_about_sections(about_text)
            if not result["jd"] or len(about_text) > len(str(result.get("jd", "") or "")):
                result["jd"] = about_text
                result["jd_source"] = "job_url_html"

    about_company_heading = next((h for h in soup.find_all(["h2", "h3"]) if _text(h).lower() == "about the company"), None)
    if about_company_heading:
        company_box = about_company_heading.find_parent()
        if company_box is not None:
            result["about_company"] = _clean_multiline(company_box.get_text("\n", strip=True))

    root = soup.find(attrs={"data-view-name": "job-detail-page"}) or soup.find("main") or soup.body or soup
    result["full_page_text"] = _trim_linkedin_detail_noise(root.get_text("\n", strip=True))
    fallback_tags = _extract_job_type_tags_from_full_page_text(result["full_page_text"])
    for tag in fallback_tags:
        if tag not in result["job_type_tags"]:
            result["job_type_tags"].append(tag)

    if not result["jd"]:
        for key, source in (
            ("meta_description", "meta_description"),
            ("og_description", "og_description"),
            ("twitter_description", "twitter_description"),
        ):
            candidate = _clean_multiline(str(result.get(key, "") or ""))
            if candidate and len(candidate) >= 120:
                result["jd"] = candidate
                result["jd_source"] = source
                break

    if not result["jd"]:
        api_retry = extract_jd_for_card_api(session, str(resp.url))
        if api_retry.get("jd"):
            result["jd"] = api_retry["jd"]
            result["jd_source"] = "api_jobPosting_retry"
        elif api_retry.get("error") and not result.get("error"):
            result["error"] = api_retry["error"]

    return result



def _normalize_for_signature(text: str) -> str:
    text = _clean_text(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_role_signature(row: Dict[str, Any]) -> str:
    title = _normalize_for_signature(str(row.get("title", "")))
    company = _normalize_for_signature(str(row.get("company", "")))
    jd = _normalize_for_signature(str(row.get("jd", "")))[:2500]
    about_job = _normalize_for_signature(str(row.get("about_job", "")))[:1000]
    location = _normalize_for_signature(str(row.get("location", "")))
    payload = f"{title}|{company}|{jd}|{about_job}|{location}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _today_utc_date() -> str:
    return date.today().isoformat()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_sqlite(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass
    return conn


def execute_with_retry(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
    attempts = (0.0, *SQLITE_BUSY_RETRY_DELAYS)
    last_error: sqlite3.OperationalError | None = None
    for idx, delay in enumerate(attempts):
        if delay > 0:
            time.sleep(delay)
        try:
            return conn.execute(sql, params)
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            last_error = exc
            if idx == len(attempts) - 1:
                break
    if last_error is not None:
        raise last_error
    return conn.execute(sql, params)


def init_sqlite(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA busy_timeout = 30000;

        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_date TEXT NOT NULL,
            started_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            source_url TEXT,
            input_jobs_json TEXT,
            max_jobs INTEGER,
            output_json TEXT,
            output_csv TEXT,
            total_jobs INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS job_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            linkedin_job_id TEXT,
            job_url TEXT NOT NULL,
            job_url_final TEXT,
            role_signature TEXT NOT NULL,
            title TEXT,
            company TEXT,
            location TEXT,
            normalized_work_model TEXT,
            normalized_employment_type TEXT,
            normalized_easy_apply INTEGER NOT NULL DEFAULT 0,
            first_seen_date TEXT NOT NULL,
            last_seen_date TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1,
            latest_posted_time TEXT,
            latest_payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_job_posts_linkedin_job_id
            ON job_posts(linkedin_job_id)
            WHERE linkedin_job_id IS NOT NULL AND linkedin_job_id <> '';

        CREATE INDEX IF NOT EXISTS ix_job_posts_role_signature
            ON job_posts(role_signature);

        CREATE INDEX IF NOT EXISTS ix_job_posts_last_seen_date
            ON job_posts(last_seen_date);

        CREATE TABLE IF NOT EXISTS job_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_run_id INTEGER NOT NULL,
            job_post_id INTEGER NOT NULL,
            crawl_date TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            posted_time TEXT,
            applicant_insight TEXT,
            row_json TEXT NOT NULL,
            is_duplicate_signature INTEGER NOT NULL DEFAULT 0,
            duplicate_of_job_post_id INTEGER,
            FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
            FOREIGN KEY (duplicate_of_job_post_id) REFERENCES job_posts(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_job_observations_crawl_job
            ON job_observations(crawl_date, job_post_id);

        CREATE TABLE IF NOT EXISTS job_jd_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL UNIQUE,
            job_post_id INTEGER NOT NULL,
            jd_text TEXT NOT NULL,
            jd_source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (observation_id) REFERENCES job_observations(id) ON DELETE CASCADE,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_job_jd_contents_job_post
            ON job_jd_contents(job_post_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS job_text_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_post_id INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            source_key TEXT NOT NULL DEFAULT '',
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
            UNIQUE(job_post_id, content_type, source_key, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS ix_job_text_embeddings_job_post
            ON job_text_embeddings(job_post_id, content_type, source_key, chunk_index);

        CREATE TABLE IF NOT EXISTS job_text_embedding_state (
            job_post_id INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            source_key TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (job_post_id, content_type, source_key),
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS job_generated_artifact_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_post_id INTEGER NOT NULL,
            documents_date_folder TEXT NOT NULL DEFAULT '',
            company_folder_name TEXT NOT NULL DEFAULT '',
            version_number INTEGER NOT NULL DEFAULT 1,
            run_folder_name TEXT NOT NULL DEFAULT '',
            output_slug TEXT NOT NULL DEFAULT '',
            output_basename TEXT NOT NULL DEFAULT '',
            cv_text TEXT NOT NULL DEFAULT '',
            portfolio_text TEXT NOT NULL DEFAULT '',
            cover_letter_text TEXT NOT NULL DEFAULT '',
            fit_report_text TEXT NOT NULL DEFAULT '',
            headline TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            experience_summary TEXT NOT NULL DEFAULT '',
            llm_model TEXT NOT NULL DEFAULT '',
            llm_backend TEXT NOT NULL DEFAULT '',
            llm_usage_json TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL DEFAULT 'etl_backfill',
            materialized_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(job_post_id, documents_date_folder, company_folder_name, version_number)
        );

        CREATE INDEX IF NOT EXISTS ix_job_generated_artifact_sets_job_post
            ON job_generated_artifact_sets(job_post_id, updated_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS job_programming_languages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_post_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'jd_text',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
            UNIQUE(job_post_id, language)
        );

        CREATE INDEX IF NOT EXISTS ix_job_programming_languages_job_post
            ON job_programming_languages(job_post_id);
        CREATE INDEX IF NOT EXISTS ix_job_programming_languages_language
            ON job_programming_languages(language);

        CREATE TABLE IF NOT EXISTS job_detail_validations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_post_id INTEGER NOT NULL UNIQUE,
            source_hash TEXT NOT NULL DEFAULT '',
            posted_time TEXT NOT NULL DEFAULT '',
            linkedin_posted_date TEXT NOT NULL DEFAULT '',
            applicant_insight TEXT NOT NULL DEFAULT '',
            compensation_text TEXT NOT NULL DEFAULT '',
            work_model TEXT NOT NULL DEFAULT '',
            employment_type TEXT NOT NULL DEFAULT '',
            easy_apply INTEGER NOT NULL DEFAULT 0,
            application_status TEXT NOT NULL DEFAULT '',
            response_note TEXT NOT NULL DEFAULT '',
            programming_language TEXT NOT NULL DEFAULT '',
            validation_model TEXT NOT NULL DEFAULT '',
            validation_backend TEXT NOT NULL DEFAULT '',
            validation_usage_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_job_detail_validations_job_post
            ON job_detail_validations(job_post_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS job_application_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_post_id INTEGER NOT NULL UNIQUE,
            has_cv INTEGER NOT NULL DEFAULT 0,
            cv_source_path TEXT,
            cv_folder_name TEXT,
            cv_created_date TEXT,
            cv_match_method TEXT,
            cv_match_score REAL,
            cv_last_synced_at TEXT,
            is_applied INTEGER NOT NULL DEFAULT 0,
            applied_first_seen_at TEXT,
            applied_last_seen_date TEXT,
            applied_source TEXT,
            has_response INTEGER NOT NULL DEFAULT 0,
            response_status TEXT,
            response_last_checked_at TEXT,
            tracker_payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS job_fit_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_post_id INTEGER NOT NULL,
            cv_profile TEXT NOT NULL,
            cv_source_path TEXT,
            total_score REAL NOT NULL,
            fit_hard REAL,
            fit_medium REAL,
            fit_soft REAL,
            domain_score REAL NOT NULL,
            tech_score REAL NOT NULL,
            evidence_score REAL NOT NULL,
            constraint_score REAL NOT NULL,
            status TEXT NOT NULL,
            fit_reason TEXT,
            fit_reason_hard TEXT,
            fit_reason_medium TEXT,
            fit_reason_soft TEXT,
            primary_issue_metric TEXT,
            primary_issue_score REAL,
            primary_issue_text TEXT,
            main_issue TEXT,
            matched_keywords_json TEXT,
            missing_keywords_json TEXT,
            evaluated_at TEXT NOT NULL,
            evaluator_version TEXT,
            FOREIGN KEY (job_post_id) REFERENCES job_posts(id) ON DELETE CASCADE,
            UNIQUE(job_post_id, cv_profile)
        );

        CREATE INDEX IF NOT EXISTS ix_fit_job_post_id ON job_fit_scores(job_post_id);
        """
    )
    post_cols = conn.execute("PRAGMA table_info(job_posts)").fetchall()
    post_names = {str(c["name"]) for c in post_cols}
    if "normalized_work_model" not in post_names:
        conn.execute("ALTER TABLE job_posts ADD COLUMN normalized_work_model TEXT")
    if "normalized_employment_type" not in post_names:
        conn.execute("ALTER TABLE job_posts ADD COLUMN normalized_employment_type TEXT")
    if "normalized_easy_apply" not in post_names:
        conn.execute("ALTER TABLE job_posts ADD COLUMN normalized_easy_apply INTEGER NOT NULL DEFAULT 0")
    cols = conn.execute("PRAGMA table_info(job_fit_scores)").fetchall()
    names = {str(c["name"]) for c in cols}
    if "fit_reason" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason TEXT")
    if "fit_reason_hard" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason_hard TEXT")
    if "fit_reason_medium" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason_medium TEXT")
    if "fit_reason_soft" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_reason_soft TEXT")
    if "primary_issue_metric" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN primary_issue_metric TEXT")
    if "primary_issue_score" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN primary_issue_score REAL")
    if "primary_issue_text" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN primary_issue_text TEXT")
    if "main_issue" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN main_issue TEXT")
    if "fit_hard" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_hard REAL")
    if "fit_medium" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_medium REAL")
    if "fit_soft" not in names:
        conn.execute("ALTER TABLE job_fit_scores ADD COLUMN fit_soft REAL")


def create_crawl_run(conn: sqlite3.Connection, args: argparse.Namespace, crawl_date: str) -> int:
    cur = execute_with_retry(
        conn,
        """
        INSERT INTO crawl_runs (
            crawl_date, started_at, mode, source_url, input_jobs_json, max_jobs, output_json, output_csv
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            crawl_date,
            _now_utc_iso(),
            args.mode,
            args.url,
            args.input_jobs_json or "",
            args.max_jobs,
            str(Path(args.output_json).resolve()),
            str(Path(args.output_csv).resolve()),
        ),
    )
    return int(cur.lastrowid)


def upsert_job_text_embeddings(
    conn: sqlite3.Connection,
    *,
    job_post_id: int,
    content_type: str,
    source_key: str,
    content_text: str,
    updated_at: str,
) -> None:
    text = str(content_text or "").strip()
    normalized_content_type = str(content_type or "").strip()
    normalized_source_key = str(source_key or "").strip()
    if TUNING_SKIP_UNCHANGED_JOB_EMBEDDINGS and text:
        # Skip the full delete/re-embed cycle when the raw JD content is unchanged.
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing_state = conn.execute(
            """
            SELECT content_hash
            FROM job_text_embedding_state
            WHERE job_post_id = ? AND content_type = ? AND source_key = ?
            """,
            (int(job_post_id), normalized_content_type, normalized_source_key),
        ).fetchone()
        if existing_state and str(existing_state["content_hash"] or "").strip() == content_hash:
            return
    conn.execute(
        "DELETE FROM job_text_embeddings WHERE job_post_id = ? AND content_type = ? AND source_key = ?",
        (int(job_post_id), normalized_content_type, normalized_source_key),
    )
    if not text:
        conn.execute(
            """
            DELETE FROM job_text_embedding_state
            WHERE job_post_id = ? AND content_type = ? AND source_key = ?
            """,
            (int(job_post_id), normalized_content_type, normalized_source_key),
        )
        return
    chunks = split_text_chunks(text)
    for idx, chunk in enumerate(chunks):
        token_count = len(tokenize(chunk))
        conn.execute(
            """
            INSERT INTO job_text_embeddings (
                job_post_id, content_type, source_key, chunk_index, chunk_text, embedding_json,
                token_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(job_post_id),
                normalized_content_type,
                normalized_source_key,
                idx,
                chunk,
                json.dumps(build_hashed_embedding(chunk), ensure_ascii=False),
                token_count,
                updated_at,
                updated_at,
            ),
        )
    conn.execute(
        """
        INSERT INTO job_text_embedding_state (
            job_post_id, content_type, source_key, content_hash, chunk_count, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_post_id, content_type, source_key) DO UPDATE SET
            content_hash = excluded.content_hash,
            chunk_count = excluded.chunk_count,
            updated_at = excluded.updated_at
        """,
        (
            int(job_post_id),
            normalized_content_type,
            normalized_source_key,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            len(chunks),
            updated_at,
        ),
    )


def _slugify_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_")
    return text[:140] or "artifact"


def _extract_documents_version_info(path_value: str) -> tuple[str, str, int, str]:
    text = str(path_value or "").strip()
    if not text:
        return ("", "", 0, "")
    normalized = re.sub(r"[\\/]+", "/", text)
    match = re.search(r"/documents/([^/]+)/([^/]+)/CV(\d+)/([^/]+)$", normalized, flags=re.IGNORECASE)
    if not match:
        return ("", "", 0, "")
    return (match.group(1), match.group(2), int(match.group(3)), Path(match.group(4)).stem)


def _safe_read_text(path: Optional[Path]) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def upsert_generated_artifact_set_from_files(
    conn: sqlite3.Connection,
    *,
    job_post_id: int,
    folder: Path,
    company: str,
    title: str,
    tracking_row: Optional[sqlite3.Row],
) -> None:
    cv_file = next((p for p in folder.glob("CV_*.txt")), None)
    if cv_file is None:
        return
    portfolio_txt = next((p for p in folder.glob("PORTFOLIO_*.txt")), None)
    cover_letter_txt = next((p for p in folder.glob("cover_letter_*.txt")), None)
    fit_report_md = next((p for p in folder.glob("*_fit_report.md")), None)
    tracking = dict(tracking_row) if tracking_row is not None else {}
    documents_date_folder = ""
    company_folder_name = ""
    version_number = 0
    output_basename = ""
    for candidate in (
        str(tracking.get("cv_source_path") or ""),
        str(tracking.get("portfolio_path") or ""),
        str(tracking.get("cover_letter_docx_path") or ""),
        str(tracking.get("cover_letter_pdf_path") or ""),
    ):
        documents_date_folder, company_folder_name, version_number, output_basename = _extract_documents_version_info(candidate)
        if version_number > 0:
            break
    if not documents_date_folder:
        documents_date_folder = _extract_cv_date_from_folder(folder.name) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not company_folder_name:
        company_folder_name = _slugify_filename(company or "Company")
    if version_number <= 0:
        row = conn.execute(
            """
            SELECT MAX(version_number) AS max_version
            FROM job_generated_artifact_sets
            WHERE documents_date_folder = ? AND company_folder_name = ?
            """,
            (documents_date_folder, company_folder_name),
        ).fetchone()
        version_number = int((row["max_version"] if row else 0) or 0) + 1
    if not output_basename:
        output_basename = f"CV_DINH_CONG_THANH_{_slugify_filename(company)}_{_slugify_filename(title)}"
    output_slug = cv_file.stem[3:] if cv_file.stem.startswith("CV_") else cv_file.stem
    now_iso = _now_utc_iso()
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'etl_backfill', ?, ?)
        ON CONFLICT(job_post_id, documents_date_folder, company_folder_name, version_number) DO UPDATE SET
            run_folder_name = excluded.run_folder_name,
            output_slug = excluded.output_slug,
            output_basename = excluded.output_basename,
            cv_text = excluded.cv_text,
            portfolio_text = excluded.portfolio_text,
            cover_letter_text = excluded.cover_letter_text,
            fit_report_text = excluded.fit_report_text,
            headline = CASE WHEN excluded.headline <> '' THEN excluded.headline ELSE job_generated_artifact_sets.headline END,
            summary = CASE WHEN excluded.summary <> '' THEN excluded.summary ELSE job_generated_artifact_sets.summary END,
            experience_summary = CASE WHEN excluded.experience_summary <> '' THEN excluded.experience_summary ELSE job_generated_artifact_sets.experience_summary END,
            llm_model = CASE WHEN excluded.llm_model <> '' THEN excluded.llm_model ELSE job_generated_artifact_sets.llm_model END,
            llm_backend = CASE WHEN excluded.llm_backend <> '' THEN excluded.llm_backend ELSE job_generated_artifact_sets.llm_backend END,
            llm_usage_json = CASE WHEN excluded.llm_usage_json <> '' THEN excluded.llm_usage_json ELSE job_generated_artifact_sets.llm_usage_json END,
            updated_at = excluded.updated_at
        """,
        (
            int(job_post_id),
            documents_date_folder,
            company_folder_name,
            int(version_number),
            folder.name,
            output_slug,
            output_basename,
            _safe_read_text(cv_file),
            _safe_read_text(portfolio_txt),
            _safe_read_text(cover_letter_txt),
            _safe_read_text(fit_report_md),
            str(tracking.get("generated_headline") or ""),
            str(tracking.get("generated_summary") or ""),
            str(tracking.get("generated_experience_summary") or ""),
            str(tracking.get("generated_llm_model") or ""),
            str(tracking.get("generated_llm_backend") or ""),
            str(tracking.get("generated_llm_usage_json") or ""),
            now_iso,
            now_iso,
        ),
    )


def _find_existing_job_post(
    conn: sqlite3.Connection, linkedin_job_id: str, job_url: str, job_url_final: str
) -> Optional[sqlite3.Row]:
    linkedin_job_id = _canonical_job_id(linkedin_job_id, job_url_final, job_url)
    job_url_final = _canonical_job_url(job_url_final, job_url, linkedin_job_id)
    if linkedin_job_id:
        row = conn.execute("SELECT * FROM job_posts WHERE linkedin_job_id = ?", (linkedin_job_id,)).fetchone()
        if row:
            return row

    if job_url_final:
        row = conn.execute("SELECT * FROM job_posts WHERE job_url_final = ?", (job_url_final,)).fetchone()
        if row:
            return row

    if job_url:
        row = conn.execute("SELECT * FROM job_posts WHERE job_url = ?", (job_url,)).fetchone()
        if row:
            return row

    return None


def _list_repost_dates(conn: sqlite3.Connection, role_signature: str) -> List[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT jo.crawl_date
        FROM job_observations jo
        JOIN job_posts jp ON jp.id = jo.job_post_id
        WHERE jp.role_signature = ?
        ORDER BY jo.crawl_date
        """,
        (role_signature,),
    ).fetchall()
    return [str(row["crawl_date"]) for row in rows]


def _duration_days(repost_dates: List[str]) -> int:
    if not repost_dates:
        return 0
    first = date.fromisoformat(repost_dates[0])
    last = date.fromisoformat(repost_dates[-1])
    return (last - first).days + 1


def _clean_one_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\r", " ").replace("\n", " ")).strip()


def _normalize_payload_candidate(key: str, value: str) -> str:
    def _stringify_nested(raw: Any) -> str:
        if raw in (None, ""):
            return ""
        if isinstance(raw, str):
            return _clean_multiline(raw)
        if isinstance(raw, list):
            parts = [_stringify_nested(item) for item in raw]
            return "\n".join(part for part in parts if part).strip()
        if isinstance(raw, dict):
            parts: list[str] = []
            for nested_key, nested_value in raw.items():
                rendered = _stringify_nested(nested_value)
                if not rendered:
                    continue
                label = _clean_text(str(nested_key or ""))
                if label and rendered.lower() != label.lower():
                    separator = ":\n" if "\n" in rendered else ": "
                    parts.append(f"{label}{separator}{rendered}")
                else:
                    parts.append(rendered)
            return "\n\n".join(part for part in parts if part).strip()
        return _clean_text(str(raw))

    text = _stringify_nested(value)
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


def _looks_like_fallback_jd(text: str) -> bool:
    sample = _clean_one_line(text).lower()
    if not sample:
        return True
    return sample.startswith("job context (fallback jd):") or sample.startswith("fallback jd:")


def _payload_jd_candidates(row: Dict[str, Any]) -> List[tuple[int, int, str, str]]:
    out: List[tuple[int, int, str, str]] = []
    for key, priority in JD_CANDIDATE_KEYS:
        value = _normalize_payload_candidate(key, row.get(key, ""))
        if value and not _looks_like_fallback_jd(value):
            out.append((priority, -len(value), key, value))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _load_payload_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        data = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _payload_richness_score(row: Dict[str, Any]) -> tuple[int, int, int]:
    candidates = _payload_jd_candidates(row)
    best_jd_len = len(candidates[0][3]) if candidates else 0
    non_jd_text = "\n".join(
        [
            _clean_one_line(str(row.get("descriptionText", "") or "")),
            _clean_one_line(str(row.get("requirements", "") or "")),
            _clean_one_line(str(row.get("skills", "") or "")),
            _clean_one_line(str(row.get("technologies", "") or "")),
            _clean_one_line(str(row.get("summary", "") or "")),
            _clean_one_line(str(row.get("details", "") or "")),
            _clean_one_line(str(row.get("content", "") or "")),
            _clean_one_line(str(row.get("meta_description", "") or "")),
            _clean_one_line(str(row.get("og_description", "") or "")),
            _clean_one_line(str(row.get("twitter_description", "") or "")),
        ]
    ).strip()
    non_jd_len = len(non_jd_text)
    return (best_jd_len, non_jd_len, best_jd_len + non_jd_len + len(candidates))


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


def _select_best_payload(current_row: Dict[str, Any], existing_payload_json: str) -> str:
    current_payload = _load_payload_dict(current_row)
    existing_payload = _load_payload_dict(existing_payload_json)
    if not existing_payload:
        return json.dumps(current_payload, ensure_ascii=False)

    current_score = _payload_richness_score(current_payload)
    existing_score = _payload_richness_score(existing_payload)
    current_error = str(current_payload.get("error", "") or "").strip().upper()
    current_is_throttled = current_error.startswith("HTTP 429")
    current_has_structured_jd = any(current_score)
    existing_has_structured_jd = any(existing_score)

    if current_has_structured_jd and current_score >= existing_score:
        return json.dumps(current_payload, ensure_ascii=False)
    if current_is_throttled and existing_has_structured_jd:
        merged = dict(existing_payload)
        for key in (
            "job_id",
            "job_url",
            "job_url_final",
            "title",
            "company",
            "location",
            "posted_time",
            "applicant_insight",
            "response_note",
            "job_type_tags",
            "apply_url",
            "role_signature",
        ):
            value = current_payload.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value
        merged["error"] = current_payload.get("error", merged.get("error", ""))
        return json.dumps(merged, ensure_ascii=False)
    if existing_score > current_score:
        return json.dumps(existing_payload, ensure_ascii=False)
    return json.dumps(current_payload, ensure_ascii=False)


def _find_peer_jd_text(conn: sqlite3.Connection, *, job_post_id: int, role_signature: str, title: str, company: str) -> tuple[str, str]:
    if role_signature:
        peer = conn.execute(
            """
            SELECT COALESCE(jjc.jd_text, '') AS jd_text, COALESCE(jjc.jd_source, '') AS jd_source
            FROM job_posts cur
            JOIN job_posts peer ON peer.role_signature = cur.role_signature AND peer.id <> cur.id
            JOIN job_observations jo ON jo.job_post_id = peer.id
            JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
            WHERE cur.id = ?
              AND COALESCE(TRIM(jjc.jd_text), '') <> ''
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
              AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
            ORDER BY jo.crawl_date DESC, jo.id DESC
            LIMIT 1
            """,
            (job_post_id,),
        ).fetchone()
        if peer:
            return str(peer["jd_text"]), f"peer_role_signature:{peer['jd_source']}"

    if title and company:
        peer = conn.execute(
            """
            SELECT COALESCE(jjc.jd_text, '') AS jd_text, COALESCE(jjc.jd_source, '') AS jd_source
            FROM job_posts peer
            JOIN job_observations jo ON jo.job_post_id = peer.id
            JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
            WHERE peer.id <> ?
              AND COALESCE(LOWER(TRIM(peer.title)), '') = COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(LOWER(TRIM(peer.company)), '') = COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(TRIM(jjc.jd_text), '') <> ''
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
              AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
            ORDER BY jo.crawl_date DESC, jo.id DESC
            LIMIT 1
            """,
            (job_post_id, title, company),
        ).fetchone()
        if peer:
            return str(peer["jd_text"]), f"peer_title_company:{peer['jd_source']}"
    if company:
        peers = conn.execute(
            """
            SELECT
              peer.id,
              COALESCE(peer.title, '') AS title,
              COALESCE(jjc.jd_text, '') AS jd_text,
              COALESCE(jjc.jd_source, '') AS jd_source
            FROM job_posts peer
            JOIN job_observations jo ON jo.job_post_id = peer.id
            JOIN job_jd_contents jjc ON jjc.observation_id = jo.id
            WHERE peer.id <> ?
              AND COALESCE(LOWER(TRIM(peer.company)), '') = COALESCE(LOWER(TRIM(?)), '')
              AND COALESCE(TRIM(jjc.jd_text), '') <> ''
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'job context (fallback jd):%'
              AND LOWER(TRIM(COALESCE(jjc.jd_text, ''))) NOT LIKE 'fallback jd:%'
              AND LOWER(COALESCE(jjc.jd_source, '')) NOT LIKE '%full_page_text%'
            ORDER BY jo.crawl_date DESC, jo.id DESC
            LIMIT 200
            """,
            (job_post_id, company),
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


def _minimal_jd_from_row(row: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "Job context (fallback JD):",
            f"Title: {str(row.get('title', '') or '').strip() or 'N/A'}",
            f"Company: {str(row.get('company', '') or '').strip() or 'N/A'}",
            f"Location: {str(row.get('location', '') or '').strip() or 'N/A'}",
            f"Posted: {str(row.get('posted_time', '') or '').strip() or 'N/A'}",
            f"URL: {str(row.get('job_url_final', '') or row.get('job_url', '') or '').strip() or 'N/A'}",
        ]
    )


def save_rows_to_sqlite(
    rows: List[Dict[str, Any]], db_path: Path, args: argparse.Namespace, crawl_date: str
) -> Dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(db_path)
    try:
        init_sqlite(conn)
        run_id = create_crawl_run(conn, args, crawl_date)
        inserted_posts = 0
        duplicate_posts = 0
        jd_backfilled_payload = 0
        jd_backfilled_peer = 0
        jd_backfilled_minimal = 0
        language_backfilled_title = 0
        payload_preserved_existing = 0
        touched_job_post_ids: set[int] = set()
        conn.execute(
            """
            DELETE FROM job_programming_languages
            WHERE LOWER(TRIM(COALESCE(language, ''))) IN ('', '-', 'unknown', 'n/a', 'na', 'none', 'null')
            """
        )

        total_rows = len(rows)
        for idx, row in enumerate(rows, start=1):
            if idx == 1 or idx % 25 == 0 or idx == total_rows:
                _phase_print("db_write", f"persisting_rows {idx}/{total_rows}")
            role_signature = _build_role_signature(row)
            row["role_signature"] = role_signature
            job_url = str(row.get("job_url", ""))
            job_url_final = str(row.get("job_url_final", ""))
            linkedin_job_id = _canonical_job_id(
                str(row.get("job_id", "")),
                job_url_final,
                job_url,
            )
            job_url_final = _canonical_job_url(job_url_final, job_url, linkedin_job_id)
            normalized_work_model, normalized_employment_type = _normalize_job_type_values(row)
            normalized_easy_apply = _detect_easy_apply(row)
            now_iso = _now_utc_iso()
            row_json = json.dumps(row, ensure_ascii=False)

            existing = _find_existing_job_post(conn, linkedin_job_id, job_url, job_url_final)
            if existing:
                job_post_id = int(existing["id"])
                seen_increment = 0
                best_payload_json = _select_best_payload(row, str(existing["latest_payload_json"] or ""))
                if best_payload_json != row_json:
                    payload_preserved_existing += 1
                already_seen_today = conn.execute(
                    "SELECT 1 FROM job_observations WHERE crawl_date = ? AND job_post_id = ?",
                    (crawl_date, job_post_id),
                ).fetchone()
                if not already_seen_today:
                    seen_increment = 1
                conn.execute(
                    """
                    UPDATE job_posts
                    SET
                        job_url = ?,
                        job_url_final = ?,
                        role_signature = ?,
                        title = ?,
                        company = ?,
                        location = ?,
                        normalized_work_model = ?,
                        normalized_employment_type = ?,
                        normalized_easy_apply = ?,
                        last_seen_date = ?,
                        seen_count = seen_count + ?,
                        latest_posted_time = ?,
                        latest_payload_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        job_url,
                        job_url_final,
                        role_signature,
                        str(row.get("title", "")),
                        str(row.get("company", "")),
                        str(row.get("location", "")),
                        normalized_work_model,
                        normalized_employment_type,
                        normalized_easy_apply,
                        crawl_date,
                        seen_increment,
                        str(row.get("posted_time", "")),
                        best_payload_json,
                        now_iso,
                        job_post_id,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO job_posts (
                        linkedin_job_id, job_url, job_url_final, role_signature, title, company, location,
                        normalized_work_model, normalized_employment_type, normalized_easy_apply,
                        first_seen_date, last_seen_date, seen_count, latest_posted_time, latest_payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        linkedin_job_id,
                        job_url,
                        job_url_final,
                        role_signature,
                        str(row.get("title", "")),
                        str(row.get("company", "")),
                        str(row.get("location", "")),
                        normalized_work_model,
                        normalized_employment_type,
                        normalized_easy_apply,
                        crawl_date,
                        crawl_date,
                        str(row.get("posted_time", "")),
                        row_json,
                        now_iso,
                        now_iso,
                    ),
                )
                job_post_id = int(cur.lastrowid)
                inserted_posts += 1
            touched_job_post_ids.add(job_post_id)

            duplicate_anchor = conn.execute(
                """
                SELECT id
                FROM job_posts
                WHERE role_signature = ? AND id <> ?
                ORDER BY first_seen_date ASC, id ASC
                LIMIT 1
                """,
                (role_signature, job_post_id),
            ).fetchone()
            is_duplicate_signature = 1 if duplicate_anchor else 0
            duplicate_of_job_post_id = int(duplicate_anchor["id"]) if duplicate_anchor else None
            if is_duplicate_signature:
                duplicate_posts += 1

            conn.execute(
                """
                INSERT OR REPLACE INTO job_observations (
                    crawl_run_id, job_post_id, crawl_date, observed_at, posted_time, applicant_insight, row_json,
                    is_duplicate_signature, duplicate_of_job_post_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    job_post_id,
                    crawl_date,
                    now_iso,
                    str(row.get("posted_time", "")),
                    str(row.get("applicant_insight", "")),
                    row_json,
                    is_duplicate_signature,
                    duplicate_of_job_post_id,
                ),
            )

            obs_row = conn.execute(
                """
                SELECT id
                FROM job_observations
                WHERE crawl_date = ? AND job_post_id = ?
                LIMIT 1
                """,
                (crawl_date, job_post_id),
            ).fetchone()
            observation_id = int(obs_row["id"]) if obs_row else 0
            jd_text = _clean_one_line(str(row.get("jd", "") or ""))
            jd_source = str(row.get("jd_source", "") or "").strip()
            if not jd_text:
                candidates = _payload_jd_candidates(row)
                if candidates:
                    _, _, key, value = candidates[0]
                    if len(value) >= 120:
                        jd_text = value
                        jd_source = f"payload_fallback:{key}"
                        jd_backfilled_payload += 1
            if not jd_text:
                peer_jd, peer_source = _find_peer_jd_text(
                    conn,
                    job_post_id=job_post_id,
                    role_signature=role_signature,
                    title=str(row.get("title", "") or ""),
                    company=str(row.get("company", "") or ""),
                )
                if peer_jd:
                    jd_text = _clean_one_line(peer_jd)
                    jd_source = peer_source or "peer_fallback"
                    jd_backfilled_peer += 1
            if not jd_text:
                jd_text = _minimal_jd_from_row(row)
                jd_source = "minimal_context_fallback"
                jd_backfilled_minimal += 1

            if observation_id and jd_text:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO job_jd_contents (
                        observation_id, job_post_id, jd_text, jd_source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        job_post_id,
                        jd_text,
                        jd_source,
                        now_iso,
                        now_iso,
                    ),
                )
                upsert_job_text_embeddings(
                    conn,
                    job_post_id=job_post_id,
                    content_type="jd",
                    source_key=jd_source or "jd_text",
                    content_text=jd_text,
                    updated_at=now_iso,
                )

            language_parts = [
                str(row.get("title", "") or ""),
                str(jd_text or ""),
                str(row.get("about_job", "") or ""),
                str(row.get("description", "") or ""),
                str(row.get("applicant_insight", "") or ""),
            ]
            if not any(part.strip() for part in language_parts[1:4]):
                language_parts.append(str(row.get("full_page_text", "") or ""))
            language_source = "\n".join(language_parts).strip()
            languages = extract_programming_languages_from_text(language_source)
            if not languages:
                languages = fallback_programming_languages_from_title(str(row.get("title", "") or ""))
                if languages:
                    language_backfilled_title += 1
            conn.execute("DELETE FROM job_programming_languages WHERE job_post_id = ?", (job_post_id,))
            for language in languages:
                conn.execute(
                    """
                    INSERT INTO job_programming_languages (
                        job_post_id, language, source, created_at, updated_at
                    ) VALUES (?, ?, 'crawl_etl', ?, ?)
                    ON CONFLICT(job_post_id, language)
                    DO UPDATE SET
                        source = excluded.source,
                        updated_at = excluded.updated_at
                    """,
                    (job_post_id, language, now_iso, now_iso),
                )

            repost_dates = _list_repost_dates(conn, role_signature)
            row["crawl_date"] = crawl_date
            row["is_duplicate_with_previous_post"] = bool(is_duplicate_signature)
            row["duplicate_of_job_post_id"] = duplicate_of_job_post_id
            row["repost_dates"] = repost_dates
            row["repost_count"] = len(repost_dates)
            row["repost_duration_days"] = _duration_days(repost_dates)
            row["seen_first_date"] = repost_dates[0] if repost_dates else ""
            row["seen_last_date"] = repost_dates[-1] if repost_dates else ""

        conn.execute("UPDATE crawl_runs SET total_jobs = ? WHERE id = ?", (len(rows), run_id))
        conn.commit()
        return {
            "run_id": run_id,
            "rows": len(rows),
            "inserted_posts": inserted_posts,
            "duplicate_posts": duplicate_posts,
            "jd_backfilled_payload": jd_backfilled_payload,
            "jd_backfilled_peer": jd_backfilled_peer,
            "jd_backfilled_minimal": jd_backfilled_minimal,
            "language_backfilled_title": language_backfilled_title,
            "payload_preserved_existing": payload_preserved_existing,
            "touched_job_post_ids": sorted(touched_job_post_ids),
        }
    finally:
        conn.close()


def build_context_packs_for_jobs(db_path: Path, *, job_post_ids: List[int]) -> dict[str, int]:
    # English: Build compact JD context packs offline so online CV rewrite can avoid repeated prompt assembly work.
    if not TUNING_ENABLE_CONTEXT_PACK:
        return {"built": 0, "skipped": len(list(job_post_ids or []))}
    ids = sorted({int(x) for x in (job_post_ids or []) if int(x) > 0})
    if not ids:
        return {"built": 0, "skipped": 0}
    service = CvRewriteService(project_root=PROJECT_ROOT)
    conn = connect_sqlite(db_path)
    try:
        init_sqlite(conn)
        built = 0
        for job_post_id in ids:
            row = conn.execute(
                """
                SELECT
                  COALESCE((
                    SELECT jjc.jd_text
                    FROM job_jd_contents jjc
                    JOIN job_observations jo ON jo.id = jjc.observation_id
                    WHERE jo.job_post_id = ?
                    ORDER BY jo.crawl_date DESC, jo.id DESC
                    LIMIT 1
                  ), '') AS jd_text
                """,
                (job_post_id,),
            ).fetchone()
            jd_text = str((row["jd_text"] if row else "") or "").strip()
            if not jd_text:
                continue
            service.build_context_pack_for_job(job_id=job_post_id, jd_text=jd_text)
            built += 1
        return {"built": built, "skipped": max(0, len(ids) - built)}
    finally:
        conn.close()


def _estimate_posted_date_from_text(posted_time: str, last_seen_date: str, first_seen_date: str) -> str:
    days = _parse_posted_age_days(posted_time or "")
    base = str(last_seen_date or first_seen_date or "").strip()
    if not base:
        return ""
    try:
        base_date = datetime.fromisoformat(base).date()
    except ValueError:
        return ""
    if days is None:
        return base_date.isoformat()
    return (base_date - date.resolution * days).isoformat()


def backfill_job_detail_validations(conn: sqlite3.Connection, *, job_post_ids: Optional[List[int]] = None, force: bool = False) -> dict[str, int]:
    where_sql = ""
    params: list[Any] = []
    if job_post_ids:
        placeholders = ",".join("?" for _ in job_post_ids)
        where_sql = f"WHERE jp.id IN ({placeholders})"
        params.extend(int(x) for x in job_post_ids)
    rows = conn.execute(
        f"""
        SELECT
          jp.id AS job_post_id,
          COALESCE(jp.title, '') AS title,
          COALESCE(jp.company, '') AS company,
          COALESCE(jp.location, '') AS location,
          COALESCE(jp.latest_posted_time, '') AS latest_posted_time,
          COALESCE(jp.first_seen_date, '') AS first_seen_date,
          COALESCE(jp.last_seen_date, '') AS last_seen_date,
          COALESCE(jp.latest_payload_json, '') AS latest_payload_json,
          COALESCE(jdv.source_hash, '') AS existing_source_hash,
          COALESCE((
            SELECT jjc.jd_text
            FROM job_jd_contents jjc
            JOIN job_observations jo ON jo.id = jjc.observation_id
            WHERE jo.job_post_id = jp.id
            ORDER BY jo.crawl_date DESC, jo.id DESC
            LIMIT 1
          ), '') AS jd_text
        FROM job_posts jp
        LEFT JOIN job_detail_validations jdv ON jdv.job_post_id = jp.id
        {where_sql}
        ORDER BY jp.id ASC
        """,
        params,
    ).fetchall()
    scanned = 0
    updated = 0
    skipped = 0
    for row in rows:
        scanned += 1
        try:
            payload = json.loads(str(row["latest_payload_json"] or "{}"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("title", str(row["title"] or ""))
        payload.setdefault("company", str(row["company"] or ""))
        payload.setdefault("location", str(row["location"] or ""))
        payload.setdefault("posted_time", str(row["latest_posted_time"] or ""))
        jd_text = str(row["jd_text"] or "").strip()
        validated = validate_job_details(payload=payload, jd_text=jd_text)
        if not force and validated["source_hash"] == str(row["existing_source_hash"] or ""):
            skipped += 1
            continue
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        linkedin_posted_date = _estimate_posted_date_from_text(
            str(validated.get("posted_time") or ""),
            str(row["last_seen_date"] or ""),
            str(row["first_seen_date"] or ""),
        )
        conn.execute(
            """
            INSERT INTO job_detail_validations (
              job_post_id, source_hash, posted_time, linkedin_posted_date, applicant_insight,
              compensation_text, work_model, employment_type, easy_apply, application_status,
              response_note, programming_language, validation_model, validation_backend,
              validation_usage_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_post_id) DO UPDATE SET
              source_hash = excluded.source_hash,
              posted_time = excluded.posted_time,
              linkedin_posted_date = excluded.linkedin_posted_date,
              applicant_insight = excluded.applicant_insight,
              compensation_text = excluded.compensation_text,
              work_model = excluded.work_model,
              employment_type = excluded.employment_type,
              easy_apply = excluded.easy_apply,
              application_status = excluded.application_status,
              response_note = excluded.response_note,
              programming_language = excluded.programming_language,
              validation_model = excluded.validation_model,
              validation_backend = excluded.validation_backend,
              validation_usage_json = excluded.validation_usage_json,
              updated_at = excluded.updated_at
            """,
            (
                int(row["job_post_id"]),
                validated["source_hash"],
                str(validated.get("posted_time") or ""),
                linkedin_posted_date,
                str(validated.get("applicant_insight") or ""),
                str(validated.get("compensation_text") or ""),
                str(validated.get("work_model") or ""),
                str(validated.get("employment_type") or ""),
                int(validated.get("easy_apply") or 0),
                str(validated.get("application_status") or ""),
                str(validated.get("response_note") or ""),
                str(validated.get("programming_language") or ""),
                str(validated.get("validation_model") or ""),
                str(validated.get("validation_backend") or ""),
                str(validated.get("validation_usage_json") or ""),
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE job_posts
            SET normalized_work_model = ?,
                normalized_employment_type = ?,
                normalized_easy_apply = ?,
                latest_posted_time = CASE
                  WHEN COALESCE(TRIM(?), '') <> '' THEN ?
                  ELSE latest_posted_time
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(validated.get("work_model") or ""),
                str(validated.get("employment_type") or ""),
                int(validated.get("easy_apply") or 0),
                str(validated.get("posted_time") or ""),
                str(validated.get("posted_time") or ""),
                now,
                int(row["job_post_id"]),
            ),
        )
        langs = [x.strip() for x in str(validated.get("programming_language") or "").split(",") if x.strip()]
        if langs:
            conn.execute("DELETE FROM job_programming_languages WHERE job_post_id = ?", (int(row["job_post_id"]),))
            for lang in langs:
                conn.execute(
                    """
                    INSERT INTO job_programming_languages (
                      job_post_id, language, source, created_at, updated_at
                    ) VALUES (?, ?, 'detail_validation', ?, ?)
                    ON CONFLICT(job_post_id, language) DO UPDATE SET
                      source = excluded.source,
                      updated_at = excluded.updated_at
                    """,
                    (int(row["job_post_id"]), lang, now, now),
                )
        updated += 1
    conn.commit()
    return {"scanned": scanned, "updated": updated, "skipped": skipped}


def _upsert_fit_score(conn: sqlite3.Connection, data: Dict[str, Any]) -> None:
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


def _build_detailed_fit_reason(
    *,
    mode: str,
    mode_ok: bool,
    total_score: float,
    domain_score: float,
    tech_score: float,
    evidence_score: float,
    constraint_score_value: float,
    matched_keywords: List[str],
    missing_keywords: List[str],
    constraint_note: str,
) -> str:
    strengths = ", ".join(matched_keywords[:8]) if matched_keywords else "none"
    gaps = ", ".join(missing_keywords[:8]) if missing_keywords else "none"
    verdict = "PASS" if mode_ok else "FAIL"
    return (
        f"Mode={mode.upper()} | Constraint={verdict}. "
        f"Total={total_score:.2f}. "
        f"Scores(domain={domain_score:.2f}, tech={tech_score:.2f}, evidence={evidence_score:.2f}, compliance={constraint_score_value:.2f}). "
        f"Strengths: {strengths}. "
        f"Gaps: {gaps}. "
        f"Constraint note: {constraint_note}"
    )


def _build_fit_jd_text(job: sqlite3.Row | Dict[str, Any], payload: Dict[str, Any]) -> str:
    return "\n".join(
        [
            str((job["jd_text"] if isinstance(job, sqlite3.Row) else job.get("jd_text", "")) or "").strip(),
            str(payload.get("jd", "")).strip(),
            str(payload.get("about_job", "")).strip(),
            str(payload.get("description", "")).strip(),
            str(payload.get("jobDescription", "")).strip(),
            str(payload.get("job_description", "")).strip(),
            str(payload.get("details", "")).strip(),
            str(payload.get("requirements", "")).strip(),
            str(payload.get("skills", "")).strip(),
            str(payload.get("technologies", "")).strip(),
            str(payload.get("full_page_text", "")).strip(),
            str((job["title"] if isinstance(job, sqlite3.Row) else job.get("title", "")) or ""),
            str((job["company"] if isinstance(job, sqlite3.Row) else job.get("company", "")) or ""),
            str((job["location"] if isinstance(job, sqlite3.Row) else job.get("location", "")) or ""),
        ]
    ).strip()


def _primary_issue(
    *,
    mode_ok: bool,
    constraint_note: str,
    domain_score: float,
    tech_score: float,
    evidence_score: float,
    compliance_score: float,
) -> tuple[str, float, str]:
    if not mode_ok:
        return ("constraint", round(compliance_score, 2), constraint_note or "Constraint failed.")
    metrics = [
        ("domain", round(domain_score, 2), f"Lowest score is domain fit ({domain_score:.2f})."),
        ("tech", round(tech_score, 2), f"Lowest score is technical fit ({tech_score:.2f})."),
        ("evidence", round(evidence_score, 2), f"Lowest score is evidence quality ({evidence_score:.2f})."),
        ("compliance", round(compliance_score, 2), f"Lowest score is compliance ({compliance_score:.2f})."),
    ]
    metric, score, text = min(metrics, key=lambda item: item[1])
    return metric, score, text


def _select_jobs_missing_fit(
    conn: sqlite3.Connection,
    *,
    cv_profile: str,
    only_crawl_run_id: Optional[int] = None,
    include_existing: bool = False,
    job_post_ids: Optional[List[int]] = None,
) -> List[sqlite3.Row]:
    params: List[Any] = [cv_profile]
    where_run = ""
    if only_crawl_run_id is not None:
        where_run = "AND jo.crawl_run_id = ?"
        params.append(int(only_crawl_run_id))
    where_job_ids = ""
    if job_post_ids:
        placeholders = ",".join("?" for _ in job_post_ids)
        where_job_ids = f"AND jp.id IN ({placeholders})"
        params.extend(int(x) for x in job_post_ids)
    fit_where = "" if include_existing else "AND fs.id IS NULL"
    return conn.execute(
        f"""
        SELECT DISTINCT
            jp.id,
            jp.title,
            jp.company,
            jp.location,
            jp.latest_payload_json,
            (
                SELECT jjc.jd_text
                FROM job_jd_contents jjc
                WHERE jjc.job_post_id = jp.id
                ORDER BY jjc.updated_at DESC, jjc.id DESC
                LIMIT 1
            ) AS jd_text
        FROM job_posts jp
        JOIN job_observations jo ON jo.job_post_id = jp.id
        LEFT JOIN job_fit_scores fs
            ON fs.job_post_id = jp.id
           AND fs.cv_profile = ?
        WHERE 1=1
          {fit_where}
          {where_run}
          {where_job_ids}
        ORDER BY jp.last_seen_date DESC, jp.id DESC
        """,
        params,
    ).fetchall()


def evaluate_missing_fit_scores(
    db_path: Path,
    *,
    cv_path: Path,
    crawl_run_id: Optional[int] = None,
    cv_profile: str = "full_doc_stlye",
    include_existing: bool = False,
    constraint_mode: str = "medium",
    job_post_ids: Optional[List[int]] = None,
) -> Dict[str, int]:
    if not cv_path.exists():
        return {"missing_before": 0, "evaluated": 0, "missing_after": 0, "skipped_no_cv": 1}

    cv_text = cv_path.read_text(encoding="utf-8", errors="ignore")
    cv_clean = strip_tags(cv_text)
    cv_tokens_set = set(tokenize(cv_clean))
    now_iso = _now_utc_iso()

    conn = connect_sqlite(db_path)
    try:
        init_sqlite(conn)
        missing_before_rows = _select_jobs_missing_fit(
            conn,
            cv_profile=cv_profile,
            only_crawl_run_id=crawl_run_id,
            include_existing=include_existing,
            job_post_ids=job_post_ids,
        )
        evaluated = 0
        for job in missing_before_rows:
            payload: Dict[str, Any] = {}
            try:
                payload = json.loads(job["latest_payload_json"] or "{}")
            except Exception:
                payload = {}

            jd_text = _build_fit_jd_text(job, payload)
            jd_clean = strip_tags(jd_text)
            jd_tokens_set = set(tokenize(jd_clean))

            if not jd_tokens_set:
                _upsert_fit_score(
                    conn,
                    {
                        "job_post_id": int(job["id"]),
                        "cv_profile": cv_profile,
                        "cv_source_path": str(cv_path.resolve()),
                        "total_score": 0.0,
                        "fit_hard": 0.0,
                        "fit_medium": 0.0,
                        "fit_soft": 0.0,
                        "domain_score": 0.0,
                        "tech_score": 0.0,
                        "evidence_score": 0.0,
                        "constraint_score": 0.0,
                        "status": "not_evaluated",
                        "fit_reason": "JD content missing or too short to evaluate.",
                        "fit_reason_hard": "Mode=HARD | Constraint=FAIL. JD content missing or too short to evaluate.",
                        "fit_reason_medium": "Mode=MEDIUM | Constraint=FAIL. JD content missing or too short to evaluate.",
                        "fit_reason_soft": "Mode=SOFT | Constraint=FAIL. JD content missing or too short to evaluate.",
                        "primary_issue_metric": "constraint",
                        "primary_issue_score": 0.0,
                        "primary_issue_text": "JD content missing or too short to evaluate.",
                        "main_issue": "Constraint — JD content missing or too short to evaluate.",
                        "matched_keywords_json": "[]",
                        "missing_keywords_json": "[]",
                        "evaluated_at": now_iso,
                        "evaluator_version": "fit-v2-crawl-inline",
                    },
                )
                evaluated += 1
                continue

            jd_keywords = top_keywords(jd_clean, limit=40)
            keyword_score, matched_keywords, missing_keywords = keyword_coverage_score(jd_keywords, cv_tokens_set)
            technical_score = technical_fit_score(jd_tokens_set, cv_tokens_set)
            domain_score = domain_fit_score(jd_tokens_set, cv_tokens_set)
            evidence_score = evidence_quality_score(cv_clean)
            compliance_score, _ = constraint_score(jd_clean, cv_clean)
            domain_blended = (0.6 * domain_score) + (0.4 * keyword_score)
            base_total = round(weighted_total(domain_blended, technical_score, evidence_score, compliance_score), 2)

            mode_totals: Dict[str, float] = {}
            mode_notes: Dict[str, str] = {}
            mode_ok: Dict[str, bool] = {}
            for mode_name in ("hard", "medium", "soft"):
                ok, _, _, note = hard_constraint_check(jd_clean, mode=mode_name)
                mode_ok[mode_name] = bool(ok)
                mode_notes[mode_name] = note or ""
                mode_totals[mode_name] = base_total if ok else 0.0

            selected_mode = (constraint_mode or "medium").strip().lower()
            if selected_mode not in {"hard", "medium", "soft"}:
                selected_mode = "medium"
            total_score = round(mode_totals[selected_mode], 2)
            if not mode_ok[selected_mode]:
                fit_reason = mode_notes[selected_mode] or "Constraint failed."
            elif total_score >= 85:
                fit_reason = "Strong fit across domain, technical, and evidence dimensions."
            elif total_score >= 70:
                fit_reason = "Partial fit: some gaps remain in domain/keywords."
            else:
                fit_reason = "Low fit score against required domain/technical keywords."
            primary_issue_metric, primary_issue_score, primary_issue_text = _primary_issue(
                mode_ok=mode_ok[selected_mode],
                constraint_note=mode_notes[selected_mode],
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                compliance_score=round(compliance_score, 2),
            )
            primary_issue_label = {
                "constraint": "Constraint",
                "domain": "Domain",
                "tech": "Technical",
                "evidence": "Evidence",
                "compliance": "Compliance",
            }.get(primary_issue_metric, "Issue")
            main_issue = f"{primary_issue_label} — {primary_issue_text}"
            fit_reason_hard = _build_detailed_fit_reason(
                mode="hard",
                mode_ok=mode_ok["hard"],
                total_score=round(mode_totals["hard"], 2),
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                constraint_score_value=round(compliance_score, 2),
                matched_keywords=matched_keywords,
                missing_keywords=missing_keywords,
                constraint_note=mode_notes["hard"],
            )
            fit_reason_medium = _build_detailed_fit_reason(
                mode="medium",
                mode_ok=mode_ok["medium"],
                total_score=round(mode_totals["medium"], 2),
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                constraint_score_value=round(compliance_score, 2),
                matched_keywords=matched_keywords,
                missing_keywords=missing_keywords,
                constraint_note=mode_notes["medium"],
            )
            fit_reason_soft = _build_detailed_fit_reason(
                mode="soft",
                mode_ok=mode_ok["soft"],
                total_score=round(mode_totals["soft"], 2),
                domain_score=round(domain_blended, 2),
                tech_score=round(technical_score, 2),
                evidence_score=round(evidence_score, 2),
                constraint_score_value=round(compliance_score, 2),
                matched_keywords=matched_keywords,
                missing_keywords=missing_keywords,
                constraint_note=mode_notes["soft"],
            )
            status = (
                "ready_to_apply"
                if (mode_ok[selected_mode] and total_score >= 85)
                else "needs_improvement"
                if (mode_ok[selected_mode] and total_score >= 70)
                else "not_compatible"
            )

            _upsert_fit_score(
                conn,
                {
                    "job_post_id": int(job["id"]),
                    "cv_profile": cv_profile,
                    "cv_source_path": str(cv_path.resolve()),
                    "total_score": total_score,
                    "fit_hard": round(mode_totals["hard"], 2),
                    "fit_medium": round(mode_totals["medium"], 2),
                    "fit_soft": round(mode_totals["soft"], 2),
                    "domain_score": round(domain_blended, 2),
                    "tech_score": round(technical_score, 2),
                    "evidence_score": round(evidence_score, 2),
                    "constraint_score": round(compliance_score, 2),
                    "status": status,
                    "fit_reason": fit_reason,
                    "fit_reason_hard": fit_reason_hard,
                    "fit_reason_medium": fit_reason_medium,
                    "fit_reason_soft": fit_reason_soft,
                    "primary_issue_metric": primary_issue_metric,
                    "primary_issue_score": primary_issue_score,
                    "primary_issue_text": primary_issue_text,
                    "main_issue": main_issue,
                    "matched_keywords_json": json.dumps(matched_keywords[:120], ensure_ascii=False),
                    "missing_keywords_json": json.dumps(missing_keywords[:120], ensure_ascii=False),
                    "evaluated_at": now_iso,
                    "evaluator_version": "fit-v2-crawl-inline",
                },
            )
            evaluated += 1

        conn.commit()
        missing_after = len(
            _select_jobs_missing_fit(
                conn,
                cv_profile=cv_profile,
                only_crawl_run_id=crawl_run_id,
                include_existing=False,
                job_post_ids=job_post_ids,
            )
        )
        return {
            "missing_before": len(missing_before_rows),
            "evaluated": evaluated,
            "missing_after": missing_after,
            "skipped_no_cv": 0,
        }
    finally:
        conn.close()


def _tokenize(value: str) -> List[str]:
    normalized = _normalize_for_signature(value)
    return [token for token in normalized.split(" ") if token]


def _extract_cv_date_from_folder(folder_name: str) -> str:
    m = re.match(r"^(\d{6})_", folder_name)
    if not m:
        return ""
    raw = m.group(1)
    try:
        return datetime.strptime(raw, "%y%m%d").date().isoformat()
    except ValueError:
        return ""


def _find_best_job_post_match_for_cv(
    conn: sqlite3.Connection, folder_name: str, cv_file_name: str, fit_report_name: str, jd_hint_text: str
) -> Optional[Dict[str, Any]]:
    candidates, linkedin_job_index, token_index = _load_job_post_match_candidates(conn)
    return _find_best_job_post_match_from_candidates(
        folder_name=folder_name,
        cv_file_name=cv_file_name,
        fit_report_name=fit_report_name,
        jd_hint_text=jd_hint_text,
        candidates=candidates,
        linkedin_job_index=linkedin_job_index,
        token_index=token_index,
    )


def _load_job_post_match_candidates(
    conn: sqlite3.Connection,
) -> tuple[list[Dict[str, Any]], dict[str, int], dict[str, list[int]]]:
    rows = conn.execute("SELECT id, linkedin_job_id, title, company FROM job_posts").fetchall()
    candidates: list[Dict[str, Any]] = []
    linkedin_job_index: dict[str, int] = {}
    token_index: dict[str, list[int]] = {}
    for row in rows:
        candidate_text = f"{row['title'] or ''} {row['company'] or ''}".strip()
        candidate_norm = _normalize_for_signature(candidate_text)
        if not candidate_norm:
            continue
        candidate_tokens = set(_tokenize(candidate_norm))
        if not candidate_tokens:
            continue
        item = {
            "id": int(row["id"]),
            "title": str(row["title"] or ""),
            "company": str(row["company"] or ""),
            "norm": candidate_norm,
            "tokens": candidate_tokens,
        }
        idx = len(candidates)
        candidates.append(item)
        linkedin_job_id = str(row["linkedin_job_id"] or "").strip()
        if linkedin_job_id:
            linkedin_job_index[linkedin_job_id] = int(row["id"])
        for token in candidate_tokens:
            token_index.setdefault(token, []).append(idx)
    return candidates, linkedin_job_index, token_index


def _find_best_job_post_match_from_candidates(
    *,
    folder_name: str,
    cv_file_name: str,
    fit_report_name: str,
    jd_hint_text: str,
    candidates: list[Dict[str, Any]],
    linkedin_job_index: dict[str, int],
    token_index: dict[str, list[int]],
) -> Optional[Dict[str, Any]]:
    hint = " ".join([folder_name, cv_file_name, fit_report_name, jd_hint_text]).strip()
    hint_norm = _normalize_for_signature(hint)
    if not hint_norm:
        return None

    m_job_id = re.search(r"\b(\d{7,})\b", hint_norm)
    if m_job_id:
        matched_job_id = linkedin_job_index.get(m_job_id.group(1))
        if matched_job_id:
            return {"job_post_id": int(matched_job_id), "score": 1.0, "method": "linkedin_job_id"}

    hint_tokens = set(_tokenize(hint_norm))
    if not hint_tokens:
        return None

    best: Optional[Dict[str, Any]] = None
    overlap_counts: dict[int, int] = {}
    for token in hint_tokens:
        for idx in token_index.get(token, []):
            overlap_counts[idx] = overlap_counts.get(idx, 0) + 1
    candidate_indexes = list(overlap_counts.keys()) if overlap_counts else list(range(len(candidates)))
    if overlap_counts and len(candidate_indexes) > 240:
        candidate_indexes.sort(key=lambda idx: overlap_counts.get(idx, 0), reverse=True)
        candidate_indexes = candidate_indexes[:240]

    for idx in candidate_indexes:
        candidate = candidates[idx]
        candidate_norm = str(candidate["norm"])
        candidate_tokens = set(candidate["tokens"])
        overlap = len(hint_tokens.intersection(candidate_tokens)) / max(1, len(hint_tokens))
        ratio = SequenceMatcher(None, hint_norm, candidate_norm).ratio()
        score = (0.7 * overlap) + (0.3 * ratio)
        if best is None or score > float(best["score"]):
            best = {
                "job_post_id": int(candidate["id"]),
                "score": float(score),
                "method": "title_company_fuzzy",
                "title": str(candidate["title"]),
                "company": str(candidate["company"]),
            }

    if best and float(best["score"]) >= 0.22:
        return best
    return None


def _sync_cv_max_workers() -> int:
    raw = str(os.getenv("JOB_OPS_SYNC_CV_WORKERS", "") or "").strip()
    if raw.isdigit():
        return max(1, min(8, int(raw)))
    cpu_count = os.cpu_count() or SYNC_CV_DEFAULT_MAX_WORKERS
    return max(2, min(SYNC_CV_DEFAULT_MAX_WORKERS, cpu_count))


def _sync_cv_folder_match_task(
    folder: Path,
    jd_root: Path,
    candidates: list[Dict[str, Any]],
    linkedin_job_index: dict[str, int],
    token_index: dict[str, list[int]],
) -> Dict[str, Any]:
    cv_file = next((p for p in folder.glob("CV_*.txt")), None)
    if cv_file is None:
        return {"folder": folder, "matched": False, "reason": "missing_cv"}
    fit_report = next((p for p in folder.glob("*_fit_report.md")), None)
    jd_hint_text = _load_jd_hint_from_raw_cv_folder(folder.name, jd_root=jd_root)
    match = _find_best_job_post_match_from_candidates(
        folder_name=folder.name,
        cv_file_name=cv_file.name,
        fit_report_name=fit_report.name if fit_report else "",
        jd_hint_text=jd_hint_text,
        candidates=candidates,
        linkedin_job_index=linkedin_job_index,
        token_index=token_index,
    )
    return {
        "folder": folder,
        "cv_file": cv_file,
        "matched": bool(match),
        "match": match,
        "cv_created_date": _extract_cv_date_from_folder(folder.name),
    }


def _load_jd_hint_from_raw_cv_folder(raw_cv_folder_name: str, jd_root: Path) -> str:
    parts = raw_cv_folder_name.split("_", 2)
    if len(parts) < 3:
        return ""
    jd_slug = parts[2].strip()
    if not jd_slug:
        return ""
    jd_path = jd_root / f"{jd_slug}.txt"
    if not jd_path.exists():
        return ""
    try:
        return jd_path.read_text(encoding="utf-8", errors="ignore")[:2200]
    except OSError:
        return ""


def upsert_job_tracking_status(
    conn: sqlite3.Connection,
    *,
    job_post_id: int,
    has_cv: Optional[bool] = None,
    cv_source_path: str = "",
    cv_folder_name: str = "",
    cv_created_date: str = "",
    cv_match_method: str = "",
    cv_match_score: float = 0.0,
    is_applied: Optional[bool] = None,
    applied_last_seen_date: str = "",
    applied_source: str = "",
    has_response: Optional[bool] = None,
    response_status: str = "",
    tracker_payload_json: str = "",
) -> None:
    now_iso = _now_utc_iso()
    existing = conn.execute(
        "SELECT * FROM job_application_tracking WHERE job_post_id = ?",
        (job_post_id,),
    ).fetchone()
    if existing:
        existing_cv_source_path = str(existing["cv_source_path"] or "").strip()
        incoming_cv_source_path = str(cv_source_path or "").strip()
        existing_lower = existing_cv_source_path.lower()
        incoming_lower = incoming_cv_source_path.lower()
        preserve_existing_uploadable = bool(
            existing_cv_source_path
            and (existing_lower.endswith(".pdf") or existing_lower.endswith(".docx") or "/documents/" in existing_lower.replace("\\", "/"))
            and incoming_lower.endswith(".txt")
        )
        effective_cv_source_path = existing_cv_source_path if preserve_existing_uploadable else incoming_cv_source_path
        conn.execute(
            """
            UPDATE job_application_tracking
            SET
                has_cv = COALESCE(?, has_cv),
                cv_source_path = CASE WHEN ? <> '' THEN ? ELSE cv_source_path END,
                cv_folder_name = CASE WHEN ? <> '' THEN ? ELSE cv_folder_name END,
                cv_created_date = CASE WHEN ? <> '' THEN ? ELSE cv_created_date END,
                cv_match_method = CASE WHEN ? <> '' THEN ? ELSE cv_match_method END,
                cv_match_score = CASE WHEN ? > 0 THEN ? ELSE cv_match_score END,
                cv_last_synced_at = CASE WHEN ? IS NOT NULL THEN ? ELSE cv_last_synced_at END,
                is_applied = COALESCE(?, is_applied),
                applied_first_seen_at = CASE
                    WHEN COALESCE(applied_first_seen_at, '') <> '' THEN applied_first_seen_at
                    WHEN ? <> '' THEN ?
                    ELSE applied_first_seen_at
                END,
                applied_last_seen_date = CASE WHEN ? <> '' THEN ? ELSE applied_last_seen_date END,
                applied_source = CASE WHEN ? <> '' THEN ? ELSE applied_source END,
                has_response = COALESCE(?, has_response),
                response_status = CASE WHEN ? <> '' THEN ? ELSE response_status END,
                response_last_checked_at = CASE WHEN ? IS NOT NULL THEN ? ELSE response_last_checked_at END,
                tracker_payload_json = CASE WHEN ? <> '' THEN ? ELSE tracker_payload_json END,
                updated_at = ?
            WHERE job_post_id = ?
            """,
            (
                int(has_cv) if has_cv is not None else None,
                effective_cv_source_path,
                effective_cv_source_path,
                cv_folder_name,
                cv_folder_name,
                cv_created_date,
                cv_created_date,
                cv_match_method,
                cv_match_method,
                cv_match_score,
                cv_match_score,
                int(has_cv) if has_cv is not None else None,
                now_iso,
                int(is_applied) if is_applied is not None else None,
                applied_last_seen_date,
                applied_last_seen_date,
                applied_last_seen_date,
                applied_last_seen_date,
                applied_source,
                applied_source,
                int(has_response) if has_response is not None else None,
                response_status,
                response_status,
                int(is_applied) if is_applied is not None else None,
                now_iso,
                tracker_payload_json,
                tracker_payload_json,
                now_iso,
                job_post_id,
            ),
        )
        return

    conn.execute(
        """
        INSERT INTO job_application_tracking (
            job_post_id, has_cv, cv_source_path, cv_folder_name, cv_created_date, cv_match_method, cv_match_score,
            cv_last_synced_at, is_applied, applied_first_seen_at, applied_last_seen_date, applied_source, has_response, response_status,
            response_last_checked_at, tracker_payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_post_id,
            int(has_cv) if has_cv is not None else 0,
            cv_source_path,
            cv_folder_name,
            cv_created_date,
            cv_match_method,
            cv_match_score,
            now_iso if has_cv is not None else "",
            int(is_applied) if is_applied is not None else 0,
            applied_last_seen_date,
            applied_last_seen_date,
            applied_source,
            int(has_response) if has_response is not None else 0,
            response_status,
            now_iso if is_applied is not None else "",
            tracker_payload_json,
            now_iso,
            now_iso,
        ),
    )


def sync_cv_status_from_raw_cv(
    db_path: Path,
    raw_cv_root: Path,
    jd_root: Optional[Path] = None,
    *,
    resume_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    if not raw_cv_root.exists():
        return {"folders": 0, "mapped": 0, "unmatched": 0, "artifact_sets": 0}

    jd_root = jd_root or raw_cv_root.parent / "JD"
    folders_list = [folder for folder in sorted(raw_cv_root.iterdir()) if folder.is_dir()]
    folder_lookup = {folder.name: folder for folder in folders_list}
    if resume_state and isinstance(resume_state.get("folders_order"), list):
        folders_order = [str(name) for name in resume_state.get("folders_order") if str(name) in folder_lookup]
    else:
        folders_order = [folder.name for folder in folders_list]
    total_folders = len(folders_order)
    if total_folders == 0:
        return {"folders": 0, "mapped": 0, "unmatched": 0, "artifact_sets": 0}

    conn = connect_sqlite(db_path)
    try:
        init_sqlite(conn)
        candidates, linkedin_job_index, token_index = _load_job_post_match_candidates(conn)
        mapped = int(resume_state.get("mapped", 0)) if resume_state else 0
        unmatched = int(resume_state.get("unmatched", 0)) if resume_state else 0
        folders = total_folders
        artifact_sets = int(resume_state.get("artifact_sets", 0)) if resume_state else 0
        processed = int(resume_state.get("processed", 0)) if resume_state else 0
        start_index = int(resume_state.get("next_index", 0)) if resume_state else 0
        last_report = time.perf_counter()
        workers = _sync_cv_max_workers()
        _phase_print("sync_cv", f"raw_cv_dir={raw_cv_root.resolve()} folders={total_folders} workers={workers}")
        pause_requested = False
        next_index = max(0, min(start_index, total_folders))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sync_cv") as executor:
            future_to_folder: dict[Any, Path] = {}

            def submit_next() -> None:
                nonlocal next_index, processed, unmatched
                while next_index < total_folders and len(future_to_folder) < workers and not pause_requested:
                    folder_name = folders_order[next_index]
                    next_index += 1
                    folder = folder_lookup.get(folder_name)
                    if folder is None:
                        processed += 1
                        unmatched += 1
                        continue
                    future = executor.submit(
                        _sync_cv_folder_match_task,
                        folder,
                        jd_root.resolve(),
                        candidates,
                        linkedin_job_index,
                        token_index,
                    )
                    future_to_folder[future] = folder

            submit_next()
            while future_to_folder:
                done, _ = wait(set(future_to_folder.keys()), timeout=1.0, return_when=FIRST_COMPLETED)
                for future in done:
                    processed += 1
                    folder = future_to_folder.pop(future, None)
                    try:
                        result = future.result()
                    except Exception as exc:
                        unmatched += 1
                        _safe_print(f"[sync_cv] worker_error folder={folder} error={exc}")
                        continue
                    folder = result["folder"]
                    match = result.get("match")
                    if not result.get("matched") or not match:
                        unmatched += 1
                        continue

                    upsert_job_tracking_status(
                        conn,
                        job_post_id=int(match["job_post_id"]),
                        has_cv=True,
                        cv_source_path=str(result["cv_file"].resolve()),
                        cv_folder_name=folder.name,
                        cv_created_date=str(result.get("cv_created_date") or ""),
                        cv_match_method=str(match["method"]),
                        cv_match_score=float(match["score"]),
                    )
                    tracking_row = conn.execute(
                        "SELECT * FROM job_application_tracking WHERE job_post_id = ?",
                        (int(match["job_post_id"]),),
                    ).fetchone()
                    upsert_generated_artifact_set_from_files(
                        conn,
                        job_post_id=int(match["job_post_id"]),
                        folder=folder,
                        company=str(match.get("company") or ""),
                        title=str(match.get("title") or ""),
                        tracking_row=tracking_row,
                    )
                    artifact_sets += 1
                    mapped += 1
                    if mapped % 25 == 0:
                        conn.commit()

                now = time.perf_counter()
                if (now - last_report) >= SYNC_CV_PROGRESS_INTERVAL_SECONDS:
                    conn.commit()
                    _phase_print(
                        "sync_cv",
                        f"progress {processed}/{total_folders} mapped={mapped} unmatched={unmatched} pending={len(future_to_folder)}",
                    )
                    last_report = now

                if not pause_requested and _pause_requested():
                    pause_requested = True

                if not pause_requested:
                    submit_next()

            if pause_requested:
                conn.commit()
                resume_payload = {
                    "phase": "sync_cv",
                    "db_path": str(db_path.resolve()),
                    "raw_cv_root": str(raw_cv_root.resolve()),
                    "jd_root": str(jd_root.resolve()),
                    "resume_state": {
                        "folders_order": folders_order,
                        "next_index": next_index,
                        "processed": processed,
                        "mapped": mapped,
                        "unmatched": unmatched,
                        "artifact_sets": artifact_sets,
                    },
                    "skip_persist_outputs": True,
                }
                _pause_and_exit(resume_payload, reason="sync_cv_pause_requested")
        conn.commit()
        _phase_print(
            "sync_cv",
            f"done folders={folders} mapped={mapped} unmatched={unmatched} artifact_sets={artifact_sets}",
        )
        return {"folders": folders, "mapped": mapped, "unmatched": unmatched, "artifact_sets": artifact_sets}
    finally:
        conn.close()


def save_json(rows: List[Dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv(rows: List[Dict[str, Any]], output: Path) -> None:
    if not rows:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        normalized_rows = []
        for row in rows:
            normalized = {}
            for key in fieldnames:
                value = row.get(key, "")
                if isinstance(value, (dict, list)):
                    normalized[key] = json.dumps(value, ensure_ascii=False)
                else:
                    normalized[key] = value
            normalized_rows.append(normalized)
        writer.writerows(normalized_rows)


def main() -> None:
    _acquire_run_lock("linkedin_jobs_jd")
    parser = argparse.ArgumentParser(description="Crawl LinkedIn Jobs search and extract JD.")
    parser.add_argument("--url", default=DEFAULT_URL, help="LinkedIn jobs search URL")
    parser.add_argument("--max-jobs", type=int, default=200, help="Max jobs to extract (hard cap)")
    parser.add_argument("--window-days", type=int, default=30, help="Only keep jobs posted within N recent days")
    parser.add_argument(
        "--input-jobs-json",
        default="",
        help="Read existing jobs from JSON (must contain job_url). If set, script enriches those jobs.",
    )
    parser.add_argument("--output-json", default="linkedin_jobs_jd.json", help="Output JSON file")
    parser.add_argument("--output-csv", default="linkedin_jobs_jd.csv", help="Output CSV file")
    parser.add_argument("--sqlite-db", default="input/crawled_job/linkedin_jobs_jd.sqlite", help="SQLite output file")
    parser.add_argument("--cv-path", default="input/full_doc_stlye.txt", help="CV base file for fit evaluation")
    parser.add_argument(
        "--constraint-mode",
        default="medium",
        choices=["hard", "medium", "soft"],
        help="Constraint strictness for fit evaluation",
    )
    parser.add_argument("--no-evaluate-fit", action="store_true", help="Skip auto evaluate fit after crawl")
    parser.add_argument("--raw-cv-dir", default="input/Raw_CV", help="Raw CV directory for status sync")
    parser.add_argument("--no-sync-raw-cv", action="store_true", help="Skip syncing CV status from Raw_CV")
    parser.add_argument("--no-detail-validation", action="store_true", help="Skip LLM-assisted detail validation")
    parser.add_argument("--crawl-date", default="", help="Crawl date (YYYY-MM-DD). Default: today")
    parser.add_argument("--sleep-seconds", type=float, default=0.35, help="Delay between job detail requests")
    parser.add_argument("--resume-checkpoint", default="", help="Resume from a checkpoint JSON file")
    parser.add_argument("--company-filter", default="", help="Only keep jobs whose company name matches this text")
    parser.add_argument(
        "--mode",
        choices=["api", "playwright"],
        default="api",
        help="Data collection mode. api = no login, playwright = browser automation",
    )
    parser.add_argument(
        "--profile-dir",
        default=".pw-profile",
        help="Playwright user profile dir for keeping LinkedIn login session",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless. Keep off for first-time manual login.",
    )
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        help="Browser channel for Playwright (chrome/chromium/msedge). Default: chrome",
    )
    args = parser.parse_args()
    company_filter = str(args.company_filter or "").strip()

    def _apply_company_filter_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not company_filter:
            return items
        before = len(items)
        filtered = [item for item in items if _company_filter_match(str(item.get("company", "")), company_filter)]
        if before != len(filtered):
            _safe_print(f"[FILTER] Company '{company_filter}' kept {len(filtered)}/{before} jobs")
        return filtered
    if args.resume_checkpoint:
        checkpoint = _load_checkpoint(str(args.resume_checkpoint))
        phase = str(checkpoint.get("phase") or "").strip().lower()
        if phase != "sync_cv":
            raise ValueError(f"Unsupported resume phase: {phase}")
        resume_state = checkpoint.get("resume_state")
        db_path = Path(checkpoint.get("db_path") or args.sqlite_db).resolve()
        raw_cv_root = Path(checkpoint.get("raw_cv_root") or args.raw_cv_dir).resolve()
        jd_root = Path(checkpoint.get("jd_root") or (raw_cv_root.parent / "JD")).resolve()
        _phase_print("sync_cv", f"resume checkpoint={args.resume_checkpoint}")
        cv_sync_stats = sync_cv_status_from_raw_cv(
            db_path=db_path,
            raw_cv_root=raw_cv_root,
            jd_root=jd_root,
            resume_state=resume_state if isinstance(resume_state, dict) else None,
        )
        _safe_print(
            f"[RESUME] sync_cv done folders={cv_sync_stats['folders']} mapped={cv_sync_stats['mapped']} "
            f"unmatched={cv_sync_stats['unmatched']}",
            flush=True,
        )
        return
    logger.info(
        "Crawl start | url=%s max_jobs=%s window_days=%s mode=%s",
        args.url,
        args.max_jobs,
        args.window_days,
        args.mode,
        extra={"event": "start"},
    )

    args.url = _with_recent_window(args.url, args.window_days)
    if company_filter:
        args.url = _apply_company_search_filter(args.url, company_filter)
        _safe_print(f"[FILTER] Company search set to '{company_filter}'")
    out_json = Path(args.output_json).resolve()
    out_csv = Path(args.output_csv).resolve()
    db_path = Path(args.sqlite_db).resolve()
    crawl_date = args.crawl_date.strip() or _today_utc_date()
    date.fromisoformat(crawl_date)

    rows: List[Dict[str, Any]] = []
    jobs: List[Dict[str, Any]] = []

    session = requests.Session()
    session.headers.update(HEADERS)

    if args.input_jobs_json:
        input_path = Path(args.input_jobs_json).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Input jobs JSON not found: {input_path}")
        source_jobs = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(source_jobs, list):
            raise ValueError("Input jobs JSON must be a list of objects")
        jobs = [job for job in source_jobs if isinstance(job, dict) and job.get("job_url")]
        jobs = _apply_company_filter_list(jobs)
        _safe_print(f"[INPUT] Loaded {len(jobs)} jobs from {input_path}")

    elif args.mode == "api":
        jobs = extract_job_cards_api(session, args.url, args.max_jobs)
        jobs = _apply_company_filter_list(jobs)
        _safe_print(f"[API] Found {len(jobs)} jobs (max-jobs={args.max_jobs})")

    elif args.mode == "playwright":
        profile_dir = Path(args.profile_dir).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=args.headless,
                channel=args.browser_channel,
                viewport={"width": 1440, "height": 960},
            )
            page = context.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)

            if "linkedin.com/login" in page.url or "checkpoint" in page.url:
                _safe_print("Please complete login/checkpoint in the opened browser, then press Enter here...")
                input()
                page.goto(args.url, wait_until="domcontentloaded", timeout=60000)

            try:
                jobs = extract_job_cards_playwright(page)
                jobs = _apply_company_filter_list(jobs)
            except PlaywrightTimeoutError:
                _safe_print("Could not find job cards. Make sure you are logged in and page loaded correctly.")
                context.close()
                return

            total = min(len(jobs), args.max_jobs)
            _safe_print(f"[Playwright] Found {len(jobs)} jobs. Extracting {total}...")
            for i in range(total):
                row = dict(jobs[i])
                try:
                    row.update(extract_jd_for_card_playwright(page, i))
                except Exception as e:
                    row["jd"] = ""
                    row["error"] = str(e)
                rows.append(row)
                _safe_print(f"[{i + 1}/{total}] {row.get('title', '')} | {row.get('company', '')}")
                time.sleep(0.8)

            context.close()

    if jobs:
        total = min(len(jobs), args.max_jobs)
        source_label = "INPUT" if args.input_jobs_json else "API"
        _phase_print("extract_job_detail", f"source={source_label.lower()} total={total}")
        _safe_print(f"[{source_label}] Enriching {total} jobs via job_url HTML...")
        for i in range(total):
            row = dict(jobs[i])
            row.pop("error", None)
            try:
                details = extract_job_details_from_url(
                    session=session,
                    job_url=row.get("job_url", ""),
                    title_fallback=row.get("title", ""),
                    company_fallback=row.get("company", ""),
                    location_fallback=row.get("location", ""),
                )
                row.update(details)
            except Exception as e:
                row["jd"] = ""
                row["error"] = str(e)
            rows.append(row)
            _safe_print(f"[{i + 1}/{total}] {row.get('title', '')} | {row.get('company', '')}")
            time.sleep(max(0.0, args.sleep_seconds))

    before_filter = len(rows)
    rows = _filter_recent_rows(rows, args.window_days)
    if before_filter != len(rows):
        _safe_print(f"[FILTER] Kept {len(rows)}/{before_filter} jobs within {args.window_days} days")

    _phase_print("db_write", f"rows={len(rows)} db={db_path}")
    db_stats = save_rows_to_sqlite(rows, db_path, args, crawl_date)
    context_pack_stats = None
    if TUNING_ENABLE_CONTEXT_PACK:
        _phase_print("context_pack", f"job_posts={len(list(db_stats.get('touched_job_post_ids') or []))}")
        context_pack_stats = build_context_packs_for_jobs(
            db_path,
            job_post_ids=list(db_stats.get("touched_job_post_ids") or []),
        )
    detail_validation_stats = None
    if not args.no_detail_validation:
        _phase_print("detail_validation", f"job_posts={len(list(db_stats.get('touched_job_post_ids') or []))}")
        conn = connect_sqlite(db_path)
        try:
            detail_validation_stats = backfill_job_detail_validations(
                conn,
                job_post_ids=list(db_stats.get("touched_job_post_ids") or []),
                force=False,
            )
        finally:
            conn.close()
    fit_stats = None
    if not args.no_evaluate_fit:
        _phase_print("evaluate_fit", f"crawl_run_id={db_stats['run_id']} constraint_mode={args.constraint_mode}")
        fit_stats = evaluate_missing_fit_scores(
            db_path=db_path,
            cv_path=Path(args.cv_path).resolve(),
            crawl_run_id=db_stats["run_id"],
            include_existing=True,
            constraint_mode=args.constraint_mode,
        )
    cv_sync_stats = None
    if not args.no_sync_raw_cv:
        if _pause_requested():
            resume_payload = {
                "phase": "sync_cv",
                "db_path": str(db_path.resolve()),
                "raw_cv_root": str(Path(args.raw_cv_dir).resolve()),
                "jd_root": str((Path(args.raw_cv_dir).resolve().parent / "JD").resolve()),
                "resume_state": {
                    "next_index": 0,
                    "processed": 0,
                    "mapped": 0,
                    "unmatched": 0,
                    "artifact_sets": 0,
                },
                "skip_persist_outputs": True,
            }
            _pause_and_exit(resume_payload, reason="pause_requested_before_sync_cv")
        _phase_print("sync_cv", f"raw_cv_dir={Path(args.raw_cv_dir).resolve()}")
        cv_sync_stats = sync_cv_status_from_raw_cv(db_path=db_path, raw_cv_root=Path(args.raw_cv_dir).resolve())
    _phase_print("persist_outputs", "writing json/csv/db summary")
    save_json(rows, out_json)
    save_csv(rows, out_csv)
    _safe_print(f"Saved JSON: {out_json}")
    _safe_print(f"Saved CSV : {out_csv}")
    _safe_print(f"Saved DB  : {db_path}")
    _safe_print(
        f"[DB] crawl_run_id={db_stats['run_id']} rows={db_stats['rows']} "
        f"inserted_posts={db_stats['inserted_posts']} duplicate_posts={db_stats['duplicate_posts']} "
        f"jd_backfill(payload={db_stats.get('jd_backfilled_payload', 0)},"
        f"peer={db_stats.get('jd_backfilled_peer', 0)},"
        f"minimal={db_stats.get('jd_backfilled_minimal', 0)}) "
        f"lang_backfill_title={db_stats.get('language_backfilled_title', 0)}"
    )
    if fit_stats is not None:
        if fit_stats.get("skipped_no_cv"):
            _safe_print(f"[FIT] Skipped: CV file not found at {Path(args.cv_path).resolve()}")
        else:
            _safe_print(
                f"[FIT] missing_before={fit_stats['missing_before']} "
                f"evaluated={fit_stats['evaluated']} missing_after={fit_stats['missing_after']}"
            )
    if cv_sync_stats is not None:
        _safe_print(
            f"[CV SYNC] folders={cv_sync_stats['folders']} mapped={cv_sync_stats['mapped']} "
            f"unmatched={cv_sync_stats['unmatched']}"
        )
    if detail_validation_stats is not None:
        _safe_print(
            f"[DETAIL VALIDATION] scanned={detail_validation_stats['scanned']} "
            f"updated={detail_validation_stats['updated']} skipped={detail_validation_stats['skipped']}"
        )
    if context_pack_stats is not None:
        _safe_print(
            f"[CONTEXT PACK] built={context_pack_stats['built']} skipped={context_pack_stats['skipped']}"
        )
    logger.info(
        "Crawl complete | rows=%s db=%s",
        len(rows),
        db_path,
        extra={"event": "complete"},
    )


if __name__ == "__main__":
    main()





