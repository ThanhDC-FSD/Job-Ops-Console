import argparse
import csv
import json
import os
import re
import sqlite3
import time
import webbrowser
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from linkedin_jobs_jd import (
    HEADERS,
    _build_role_signature,
    _clean_multiline,
    _clean_text,
    _extract_job_id,
    _find_existing_job_post,
    _now_utc_iso,
    _today_utc_date,
    connect_sqlite,
    create_crawl_run,
    evaluate_missing_fit_scores,
    execute_with_retry,
    extract_job_details_from_url,
    init_sqlite,
    sync_cv_status_from_raw_cv,
    upsert_job_tracking_status,
)


DEFAULT_TRACKER_URL = "https://www.linkedin.com/jobs-tracker/?stage=applied"
FALLBACK_TRACKER_URLS = [
    "https://www.linkedin.com/jobs-tracker/?stage=applied",
    "https://www.linkedin.com/my-items/saved-jobs/?cardType=APPLIED",
    "https://www.linkedin.com/jobs/collections/applied/",
]
DEFAULT_PLAYWRIGHT_PROFILE_DIR = ".pw-profile"


def _load_local_env_vars(env_path: Path) -> Dict[str, str]:
    if not env_path.exists():
        return {}
    result: Dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            result[key] = value
    return result


def _extract_job_ids_from_text_blob(text: str) -> List[str]:
    if not text:
        return []
    found = set()
    patterns = [
        r"fsd_jobPosting:(\d{7,})",
        r"urn:li:(?:fsd_)?jobPosting:(\d{7,})",
        r"jobPosting[\"':/ ]+(\d{7,})",
        r"/jobs/view/(\d{7,})",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, text):
            found.add(str(value))
    return sorted(found)


def _extract_applied_count_hint(text: str) -> int:
    match = re.search(r"Applied[^0-9]{0,20}(\d+)", text or "", re.I)
    return int(match.group(1)) if match else 0


def _normalize_job_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("/"):
        return f"https://www.linkedin.com{href}"
    return href


def _infer_response_status(card_text: str) -> Dict[str, Any]:
    text = _clean_text(card_text).lower()
    if any(token in text for token in ["rejected", "not selected", "declined"]):
        return {"has_response": True, "response_status": "rejected"}
    if any(token in text for token in ["interview", "phone screen", "assessment"]):
        return {"has_response": True, "response_status": "interview_process"}
    if any(token in text for token in ["message from", "contacted", "in review", "application viewed"]):
        return {"has_response": True, "response_status": "in_review_or_contacted"}
    return {"has_response": False, "response_status": "applied"}


def _extract_applied_items_from_html(html: str, max_jobs: int) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    items: List[Dict[str, Any]] = []
    seen = set()
    applied_roots = soup.select("[data-view-name='opportunity-tracker-applied-stage']")
    link_candidates = []
    if applied_roots:
        for root in applied_roots:
            link_candidates.extend(root.select("a[href*='/jobs/view/']"))
    else:
        link_candidates = soup.select("a[href*='/jobs/view/']")

    for link in link_candidates:
        href = _normalize_job_url(link.get("href", ""))
        if not href:
            continue
        job_id = _extract_job_id(href)
        unique_key = job_id or href
        if unique_key in seen:
            continue
        container = link.find_parent(["li", "article", "div"])
        block_text = _clean_multiline(container.get_text("\n", strip=True)) if container else ""
        inferred = _infer_response_status(block_text)
        items.append(
            {
                "job_url": href,
                "job_id": job_id,
                "tracker_text": block_text,
                "has_response": bool(inferred["has_response"]),
                "response_status": str(inferred["response_status"]),
            }
        )
        seen.add(unique_key)
        if len(items) >= max_jobs:
            break

    # Newer LinkedIn tracker pages often render job cards through SDUI blobs
    # without exposing direct /jobs/view/ anchors in the DOM. Fall back to the
    # embedded job ids so we still capture the applied list.
    if len(items) < max_jobs:
        for job_id in _extract_job_ids_from_text_blob(html):
            unique_key = str(job_id).strip()
            if not unique_key or unique_key in seen:
                continue
            href = f"https://www.linkedin.com/jobs/view/{unique_key}/"
            items.append(
                {
                    "job_url": href,
                    "job_id": unique_key,
                    "tracker_text": "from_html_blob",
                    "has_response": False,
                    "response_status": "applied",
                }
            )
            seen.add(unique_key)
            if len(items) >= max_jobs:
                break

    return items


def _merge_unique_items(items: List[Dict[str, Any]], max_jobs: int) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        job_url = str(item.get("job_url", "")).strip()
        job_id = str(item.get("job_id", "")).strip()
        unique_key = job_id or job_url
        if not unique_key or unique_key in seen:
            continue
        merged.append(item)
        seen.add(unique_key)
        if len(merged) >= max_jobs:
            break
    return merged


def _parse_cookie_header(cookie_header: str) -> List[Dict[str, Any]]:
    cookies: List[Dict[str, Any]] = []
    for part in str(cookie_header or "").split(";"):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        name, value = chunk.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"')
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": name.lower() == "li_at",
                "secure": True,
            }
        )
    return cookies


def _page_signature(items: List[Dict[str, Any]], html: str) -> str:
    ids = [str(item.get("job_id", "")).strip() for item in items if str(item.get("job_id", "")).strip()]
    if ids:
        return "|".join(ids[:12])
    return str(len(html or ""))


def crawl_applied_jobs_playwright(
    tracker_url: str,
    cookie_header: str,
    max_jobs: int,
    debug: bool = False,
    debug_dir: Path | None = None,
    profile_dir: Path | None = None,
    browser_channel: str = "chrome",
    headless: bool = True,
) -> List[Dict[str, Any]]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed. Run: python -m playwright install chromium") from exc

    out_dir = debug_dir or Path("input/crawled_job")
    if debug:
        out_dir.mkdir(parents=True, exist_ok=True)

    merged_items: List[Dict[str, Any]] = []
    applied_count_hint = 0
    page_no = 1
    user_data_dir = (profile_dir or Path(DEFAULT_PLAYWRIGHT_PROFILE_DIR)).resolve()
    user_data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = None
        context = None
        try:
            cookies = _parse_cookie_header(cookie_header) if cookie_header else []
            if cookies:
                browser = p.chromium.launch(
                    headless=headless,
                    channel=browser_channel,
                )
                context = browser.new_context(viewport={"width": 1460, "height": 960})
                context.add_cookies(cookies)
            else:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=headless,
                    channel=browser_channel,
                    viewport={"width": 1460, "height": 960},
                )

            page = context.new_page()
            page.goto(tracker_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)

            current_url = str(page.url or "").lower()
            if "login" in current_url or "checkpoint" in current_url:
                if headless:
                    raise RuntimeError(
                        "LinkedIn login required for Playwright fallback. Re-run non-headless or prepare .pw-profile."
                    )
                print("LinkedIn login required. Complete login in opened browser, then press Enter here...")
                input()
                page.goto(tracker_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)

            while True:
                html = page.content()
                page_items = _extract_applied_items_from_html(html=html, max_jobs=max_jobs)
                applied_count_hint = max(applied_count_hint, _extract_applied_count_hint(html))
                merged_items = _merge_unique_items([*merged_items, *page_items], max_jobs=max_jobs)

                if debug:
                    (out_dir / f"linkedin_applied_playwright_page_{page_no}.html").write_text(
                        html,
                        encoding="utf-8",
                    )

                if len(merged_items) >= max_jobs:
                    break
                if applied_count_hint and len(merged_items) >= applied_count_hint:
                    break

                indicators = page.locator("button[data-testid^='pagination-indicator-']")
                indicator_count = indicators.count()
                if indicator_count > 0 and page_no >= indicator_count:
                    break
                target_button = None
                current_marker = page.locator("button[aria-current='true']").first
                current_label = str(current_marker.text_content() or "").strip() if current_marker.count() else ""
                target_index = page_no
                if indicator_count > target_index:
                    target_button = page.locator(f"button[data-testid='pagination-indicator-{target_index}']").first
                else:
                    next_button = page.locator("button[data-testid='pagination-controls-next-button-visible']").first
                    if next_button.count():
                        disabled_attr = str(next_button.get_attribute("disabled") or "").strip().lower()
                        aria_disabled = str(next_button.get_attribute("aria-disabled") or "").strip().lower()
                        if not disabled_attr and aria_disabled != "true":
                            target_button = next_button
                if target_button is None or target_button.count() == 0:
                    break
                try:
                    target_button.scroll_into_view_if_needed(timeout=3000)
                except PlaywrightTimeoutError:
                    pass
                try:
                    target_button.click(timeout=5000)
                except PlaywrightTimeoutError:
                    break
                page.wait_for_timeout(5000)
                try:
                    if current_label:
                        page.wait_for_function(
                            """(label) => {
                                const btn = document.querySelector("button[aria-current='true']");
                                return !!btn && (btn.textContent || "").trim() !== label;
                            }""",
                            arg=current_label,
                            timeout=10000,
                        )
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1000)
                page_no += 1
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()

    if debug:
        (out_dir / "linkedin_applied_playwright_meta.txt").write_text(
            f"pages={page_no}\n"
            f"applied_count_hint={applied_count_hint}\n"
            f"items={len(merged_items)}\n",
            encoding="utf-8",
        )
        print(
            f"[DEBUG] playwright pages={page_no} applied_hint={applied_count_hint} items={len(merged_items)}"
        )

    return merged_items


def _is_login_or_authwall_response(response: requests.Response) -> bool:
    final_url = (response.url or "").lower()
    text = response.text.lower()
    if "/uas/login" in final_url or "linkedin.com/login" in final_url:
        return True
    if "sign in" in text and "linkedin" in text and "session_redirect" in text:
        return True
    return False


def _cookie_header_from_args(args: argparse.Namespace) -> str:
    env_values = _load_local_env_vars(Path(".env").resolve())
    direct = (
        (args.cookie_header or "").strip()
        or os.getenv("LINKEDIN_COOKIE_HEADER", "").strip()
        or env_values.get("LINKEDIN_COOKIE_HEADER", "").strip()
    )
    if direct:
        return direct

    li_at = (
        (args.li_at or "").strip()
        or os.getenv("LI_AT", "").strip()
        or env_values.get("LI_AT", "").strip()
    )
    jsessionid = (
        (args.jsessionid or "").strip()
        or os.getenv("JSESSIONID", "").strip()
        or env_values.get("JSESSIONID", "").strip()
    )
    if not li_at:
        return ""
    parts = [f"li_at={li_at}"]
    if jsessionid:
        if not (jsessionid.startswith('"') and jsessionid.endswith('"')):
            jsessionid = f'"{jsessionid}"'
        parts.append(f"JSESSIONID={jsessionid}")
    return "; ".join(parts)


def crawl_applied_jobs_http(
    tracker_url: str,
    cookie_header: str,
    max_jobs: int,
    debug: bool = False,
    debug_dir: Path | None = None,
    profile_dir: Path | None = None,
    browser_channel: str = "chrome",
    headless: bool = True,
    enable_playwright_fallback: bool = True,
) -> List[Dict[str, Any]]:
    session = requests.Session()
    headers = dict(HEADERS)
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    if cookie_header:
        headers["Cookie"] = cookie_header
    session.headers.update(headers)

    selected_response: requests.Response | None = None
    selected_source = ""
    for url in [tracker_url] + [u for u in FALLBACK_TRACKER_URLS if u != tracker_url]:
        try:
            resp = session.get(url, timeout=45, allow_redirects=True)
        except requests.RequestException:
            continue
        selected_response = resp
        selected_source = url
        if not _is_login_or_authwall_response(resp):
            break

    if selected_response is None:
        raise RuntimeError("Could not fetch any applied tracker URL.")

    if _is_login_or_authwall_response(selected_response):
        raise RuntimeError(
            "LinkedIn session is not authenticated. Provide cookie via --cookie-header or --li-at, then run again."
        )

    html = selected_response.text
    items = _extract_applied_items_from_html(html=html, max_jobs=max_jobs)
    applied_count_hint = _extract_applied_count_hint(html)

    # If we got fewer cards than UI hint, force-fetch the canonical tracker applied page.
    if applied_count_hint > len(items) and "stage=applied" not in (selected_response.url or ""):
        try:
            canonical = session.get(
                "https://www.linkedin.com/jobs-tracker/?stage=applied",
                timeout=45,
                allow_redirects=True,
            )
            if not _is_login_or_authwall_response(canonical):
                canonical_items = _extract_applied_items_from_html(canonical.text, max_jobs=max_jobs)
                if len(canonical_items) > len(items):
                    selected_response = canonical
                    selected_source = "https://www.linkedin.com/jobs-tracker/?stage=applied"
                    html = canonical.text
                    items = canonical_items
        except requests.RequestException:
            pass

    if (
        enable_playwright_fallback
        and applied_count_hint > 0
        and len(items) < min(applied_count_hint, max_jobs)
    ):
        try:
            pw_items = crawl_applied_jobs_playwright(
                tracker_url="https://www.linkedin.com/jobs-tracker/?stage=applied",
                cookie_header=cookie_header,
                max_jobs=max_jobs,
                debug=debug,
                debug_dir=debug_dir,
                profile_dir=profile_dir,
                browser_channel=browser_channel,
                headless=headless,
            )
            if len(pw_items) > len(items):
                items = pw_items
        except Exception as exc:
            if debug:
                out_dir = debug_dir or Path("input/crawled_job")
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "linkedin_applied_playwright_error.txt").write_text(str(exc), encoding="utf-8")
                print(f"[DEBUG] playwright fallback failed: {exc}")

    if debug:
        out_dir = debug_dir or Path("input/crawled_job")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "linkedin_applied_http_debug_page.html").write_text(html, encoding="utf-8")
        (out_dir / "linkedin_applied_http_debug_meta.txt").write_text(
            f"source_url={selected_source}\n"
            f"final_url={selected_response.url}\n"
            f"status_code={selected_response.status_code}\n"
            f"applied_count_hint={applied_count_hint}\n"
            f"items={len(items)}\n",
            encoding="utf-8",
        )
        print(
            f"[DEBUG] source_url={selected_source} final_url={selected_response.url} "
            f"status={selected_response.status_code} applied_hint={applied_count_hint} items={len(items)}"
        )

    return items


def save_applied_to_sqlite(
    items: List[Dict[str, Any]],
    db_path: Path,
    tracker_url: str,
    crawl_date: str,
    output_json: Path,
    output_csv: Path,
    max_jobs: int,
) -> Dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(db_path)
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        init_sqlite(conn)
        args_ns = SimpleNamespace(
            mode="tracker_applied_http",
            url=tracker_url,
            input_jobs_json="",
            max_jobs=max_jobs,
            output_json=str(output_json),
            output_csv=str(output_csv),
        )
        run_id = create_crawl_run(conn, args_ns, crawl_date)

        created_posts = 0
        updated_tracking = 0
        for i, item in enumerate(items, start=1):
            job_url = str(item.get("job_url", ""))
            if not job_url:
                continue

            details = extract_job_details_from_url(
                session=session,
                job_url=job_url,
                title_fallback="",
                company_fallback="",
                location_fallback="",
            )
            row = {**item, **details}
            job_id = str(row.get("job_id", "") or _extract_job_id(job_url))
            now_iso = _now_utc_iso()

            existing = _find_existing_job_post(
                conn=conn,
                linkedin_job_id=job_id,
                job_url=job_url,
                job_url_final=str(row.get("job_url_final", "")),
            )
            if existing:
                job_post_id = int(existing["id"])
                execute_with_retry(
                    conn,
                    """
                    UPDATE job_posts
                    SET
                        job_url = ?,
                        job_url_final = ?,
                        title = COALESCE(NULLIF(?, ''), title),
                        company = COALESCE(NULLIF(?, ''), company),
                        location = COALESCE(NULLIF(?, ''), location),
                        last_seen_date = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        job_url,
                        str(row.get("job_url_final", "")),
                        str(row.get("title", "")),
                        str(row.get("company", "")),
                        str(row.get("location", "")),
                        crawl_date,
                        now_iso,
                        job_post_id,
                    ),
                )
            else:
                role_signature = _build_role_signature(row)
                cur = execute_with_retry(
                    conn,
                    """
                    INSERT INTO job_posts (
                        linkedin_job_id, job_url, job_url_final, role_signature, title, company, location,
                        first_seen_date, last_seen_date, seen_count, latest_posted_time, latest_payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        job_url,
                        str(row.get("job_url_final", "")),
                        role_signature,
                        str(row.get("title", "")),
                        str(row.get("company", "")),
                        str(row.get("location", "")),
                        crawl_date,
                        crawl_date,
                        str(row.get("posted_time", "")),
                        json.dumps(row, ensure_ascii=False),
                        now_iso,
                        now_iso,
                    ),
                )
                job_post_id = int(cur.lastrowid)
                created_posts += 1

            upsert_job_tracking_status(
                conn,
                job_post_id=job_post_id,
                is_applied=True,
                applied_last_seen_date=crawl_date,
                applied_source="linkedin_applied_http",
                has_response=bool(row.get("has_response", False)),
                response_status=str(row.get("response_status", "applied")),
                tracker_payload_json=json.dumps(
                    {
                        "tracker_text": row.get("tracker_text", ""),
                        "job_url": job_url,
                        "run_id": run_id,
                    },
                    ensure_ascii=False,
                ),
            )
            updated_tracking += 1
            print(f"[{i}/{len(items)}] Applied sync: {row.get('title', '')} | {row.get('company', '')}")
            time.sleep(0.2)

        execute_with_retry(conn, "UPDATE crawl_runs SET total_jobs = ? WHERE id = ?", (len(items), run_id))
        conn.commit()
        return {
            "run_id": run_id,
            "rows": len(items),
            "created_posts": created_posts,
            "updated_tracking": updated_tracking,
        }
    finally:
        conn.close()


def save_json(items: List[Dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv(items: List[Dict[str, Any]], output: Path) -> None:
    if not items:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = list(items[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        normalized = []
        for row in items:
            data = {}
            for key in fieldnames:
                value = row.get(key, "")
                data[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            normalized.append(data)
        writer.writerows(normalized)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync LinkedIn Applied Jobs tracker to SQLite")
    parser.add_argument("--tracker-url", default=DEFAULT_TRACKER_URL, help="LinkedIn applied jobs URL")
    parser.add_argument("--max-jobs", type=int, default=300, help="Max applied jobs to read")
    parser.add_argument("--sqlite-db", default="input/crawled_job/linkedin_jobs_jd.sqlite", help="SQLite DB file")
    parser.add_argument("--output-json", default="input/crawled_job/linkedin_applied_jobs.json", help="Output JSON file")
    parser.add_argument("--output-csv", default="input/crawled_job/linkedin_applied_jobs.csv", help="Output CSV file")
    parser.add_argument("--crawl-date", default="", help="Crawl date (YYYY-MM-DD). Default: today")
    parser.add_argument("--cookie-header", default="", help="Raw Cookie header from logged-in browser")
    parser.add_argument("--li-at", default="", help="LinkedIn li_at cookie value")
    parser.add_argument("--jsessionid", default="", help="LinkedIn JSESSIONID cookie value")
    parser.add_argument("--open-browser", action="store_true", help="Open applied jobs URL in current default browser")
    parser.add_argument("--raw-cv-dir", default="input/Raw_CV", help="Raw CV directory for status sync")
    parser.add_argument("--cv-path", default="input/full_doc_stlye.txt", help="CV base file for fit evaluation")
    parser.add_argument(
        "--constraint-mode",
        default="medium",
        choices=["hard", "medium", "soft"],
        help="Constraint strictness for fit evaluation",
    )
    parser.add_argument("--no-evaluate-fit", action="store_true", help="Skip auto evaluate fit after crawl")
    parser.add_argument("--no-sync-raw-cv", action="store_true", help="Skip syncing CV status from Raw_CV")
    parser.add_argument("--debug", action="store_true", help="Enable debug artifacts")
    parser.add_argument("--debug-dir", default="input/crawled_job", help="Debug output directory")
    parser.add_argument("--profile-dir", default=DEFAULT_PLAYWRIGHT_PROFILE_DIR, help="Playwright profile dir")
    parser.add_argument("--browser-channel", default="chrome", help="Playwright browser channel (chrome/chromium/msedge)")
    parser.add_argument("--headless", action="store_true", help="Run Playwright fallback in headless mode")
    parser.add_argument("--no-playwright-fallback", action="store_true", help="Disable Playwright pagination fallback")
    args = parser.parse_args()

    if args.open_browser:
        webbrowser.open_new_tab(args.tracker_url)

    cookie_header = _cookie_header_from_args(args)
    if not cookie_header:
        raise RuntimeError(
            "Missing LinkedIn cookie. Provide --cookie-header OR --li-at (and optional --jsessionid), "
            "or set LI_AT/JSESSIONID in .env."
        )

    crawl_date = args.crawl_date.strip() or _today_utc_date()
    items = crawl_applied_jobs_http(
        tracker_url=args.tracker_url,
        cookie_header=cookie_header,
        max_jobs=args.max_jobs,
        debug=args.debug,
        debug_dir=Path(args.debug_dir).resolve(),
        profile_dir=Path(args.profile_dir).resolve(),
        browser_channel=str(args.browser_channel or "chrome").strip() or "chrome",
        headless=bool(args.headless),
        enable_playwright_fallback=not bool(args.no_playwright_fallback),
    )
    print(f"[TRACKER] Found {len(items)} applied jobs")

    stats = save_applied_to_sqlite(
        items=items,
        db_path=Path(args.sqlite_db).resolve(),
        tracker_url=args.tracker_url,
        crawl_date=crawl_date,
        output_json=Path(args.output_json).resolve(),
        output_csv=Path(args.output_csv).resolve(),
        max_jobs=args.max_jobs,
    )
    fit_stats = None
    if not args.no_evaluate_fit:
        fit_stats = evaluate_missing_fit_scores(
            db_path=Path(args.sqlite_db).resolve(),
            cv_path=Path(args.cv_path).resolve(),
            crawl_run_id=stats["run_id"],
            include_existing=True,
            constraint_mode=args.constraint_mode,
        )

    if not args.no_sync_raw_cv:
        cv_stats = sync_cv_status_from_raw_cv(Path(args.sqlite_db).resolve(), Path(args.raw_cv_dir).resolve())
        print(
            f"[CV SYNC] folders={cv_stats['folders']} mapped={cv_stats['mapped']} unmatched={cv_stats['unmatched']}"
        )

    save_json(items, Path(args.output_json).resolve())
    save_csv(items, Path(args.output_csv).resolve())
    print(f"Saved JSON: {Path(args.output_json).resolve()}")
    print(f"Saved CSV : {Path(args.output_csv).resolve()}")
    print(f"Saved DB  : {Path(args.sqlite_db).resolve()}")
    print(
        f"[DB] crawl_run_id={stats['run_id']} rows={stats['rows']} "
        f"created_posts={stats['created_posts']} tracking_updates={stats['updated_tracking']}"
    )
    if fit_stats is not None:
        if fit_stats.get("skipped_no_cv"):
            print(f"[FIT] Skipped: CV file not found at {Path(args.cv_path).resolve()}")
        else:
            print(
                f"[FIT] target={fit_stats['missing_before']} "
                f"evaluated={fit_stats['evaluated']} missing_after={fit_stats['missing_after']}"
            )


if __name__ == "__main__":
    main()
