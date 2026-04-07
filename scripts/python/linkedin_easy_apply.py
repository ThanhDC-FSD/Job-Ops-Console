import argparse
import json
import os
import re
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPLY_DEBUG_DIR = PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "apply_debug"
TRACE_LOG_PATH = PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "linkedin_apply.trace.log"
PY_BROWSER_SYNC_LOG_PATH = PROJECT_ROOT / "apps" / "backend" / "app" / "logs" / "linkedin_extension.sync.log"
DOCUMENTS_DIR = PROJECT_ROOT / "documents"


def _trace(event: str, **fields: Any) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = " ".join(f"{k}={fields[k]}" for k in sorted(fields))
    line = f"{ts} | {event}"
    if payload:
        line = f"{line} | {payload}"
    try:
        TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_LOG_PATH.open("a", encoding="utf-8", errors="ignore") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _clip(value: Any, max_len: int = 2000) -> str:
    text = str(value if value is not None else "")
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}...(truncated {len(text) - max_len} chars)"


def _write_python_browser_log(event: str, payload: dict[str, Any]) -> None:
    try:
        PY_BROWSER_SYNC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "synced_at_gmt7": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "source": "playwright_python",
            "runtime_mode": "python_browser_control",
            "log": {
                "at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                "event": event,
                "payload": payload or {},
            },
        }
        with PY_BROWSER_SYNC_LOG_PATH.open("a", encoding="utf-8", errors="ignore") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _attach_page_debug_listeners(page, runtime_mode: str, job_id: int | None = None) -> None:
    setattr(page, "_li_debug_runtime_mode", runtime_mode)
    setattr(page, "_li_debug_job_id", int(job_id) if job_id else 0)
    if getattr(page, "_li_debug_attached", False):
        return
    setattr(page, "_li_debug_attached", True)

    def emit(event: str, **payload: Any) -> None:
        data = {
            "job_id": int(getattr(page, "_li_debug_job_id", 0) or 0),
            "runtime_mode": str(getattr(page, "_li_debug_runtime_mode", runtime_mode) or runtime_mode),
            "url": _clip(getattr(page, "url", "")),
            **payload,
        }
        _trace(event, **{k: _clip(v, 1200) if isinstance(v, str) else v for k, v in data.items()})
        _write_python_browser_log(event, data)

    def on_console(msg) -> None:
        try:
            location = msg.location or {}
        except Exception:
            location = {}
        emit(
            "page.console",
            level=_clip(getattr(msg, "type", "")),
            text=_clip(msg.text, 4000),
            location=location,
        )

    def on_page_error(err) -> None:
        emit("page.error", error=_clip(err, 4000))

    def on_request(req) -> None:
        try:
            headers = req.headers or {}
        except Exception:
            headers = {}
        emit(
            "page.request",
            method=_clip(req.method),
            resource_type=_clip(req.resource_type),
            request_url=_clip(req.url, 2500),
            headers={k: _clip(v, 300) for k, v in list(headers.items())[:12]},
        )

    def on_response(res) -> None:
        try:
            req = res.request
            method = req.method
            resource_type = req.resource_type
        except Exception:
            method = ""
            resource_type = ""
        emit(
            "page.response",
            status=int(res.status or 0),
            ok=bool(res.ok),
            method=_clip(method),
            resource_type=_clip(resource_type),
            response_url=_clip(res.url, 2500),
        )

    def on_request_failed(req) -> None:
        failure = ""
        try:
            failure = req.failure or ""
        except Exception:
            failure = ""
        emit(
            "page.request_failed",
            method=_clip(req.method),
            resource_type=_clip(req.resource_type),
            request_url=_clip(req.url, 2500),
            failure=_clip(failure, 1500),
        )

    def on_frame_navigated(frame) -> None:
        if frame != page.main_frame:
            return
        emit("page.navigated", frame_url=_clip(frame.url, 2500), title=_clip(page.title(), 500))

    def on_popup(popup) -> None:
        try:
            popup_job_id = int(getattr(page, "_li_debug_job_id", 0) or 0)
        except Exception:
            popup_job_id = 0
        emit("page.popup_opened", popup_url=_clip(popup.url, 2500))
        _attach_page_debug_listeners(
            popup,
            runtime_mode=str(getattr(page, "_li_debug_runtime_mode", runtime_mode) or runtime_mode),
            job_id=popup_job_id,
        )

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    page.on("framenavigated", on_frame_navigated)
    page.on("popup", on_popup)
    emit("page.listeners_attached", title=_clip(page.title(), 500))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _upsert_applied(conn: sqlite3.Connection, job_post_id: int, payload: dict[str, Any]) -> None:
    now_iso = _now_iso()
    conn.execute(
        """
        INSERT INTO job_application_tracking (
            job_post_id, has_cv, cv_last_synced_at, is_applied, applied_first_seen_at, applied_last_seen_date, applied_source,
            has_response, response_status, response_last_checked_at, tracker_payload_json, created_at, updated_at
        ) VALUES (?, 1, ?, 1, ?, ?, 'linkedin_easy_apply', 0, '', ?, ?, ?, ?)
        ON CONFLICT(job_post_id) DO UPDATE SET
            is_applied = 1,
            applied_first_seen_at = COALESCE(job_application_tracking.applied_first_seen_at, excluded.applied_first_seen_at),
            applied_last_seen_date = excluded.applied_last_seen_date,
            applied_source = excluded.applied_source,
            tracker_payload_json = excluded.tracker_payload_json,
            response_last_checked_at = excluded.response_last_checked_at,
            updated_at = excluded.updated_at
        """,
        (
            int(job_post_id),
            now_iso,
            now_iso,
            _today(),
            now_iso,
            str(payload),
            now_iso,
            now_iso,
        ),
    )


def _dismiss_apply_modal(page) -> None:
    try:
        for _ in range(3):
            close_btn = page.get_by_role("button", name="Dismiss")
            if close_btn.count() > 0:
                close_btn.first.click(timeout=1500)
                time.sleep(0.2)
            discard = page.get_by_role("button", name="Discard")
            if discard.count() > 0:
                discard.first.click(timeout=1500)
                time.sleep(0.2)
    except Exception:
        return


def _is_uploadable_cv_path(path: Path) -> bool:
    return path.suffix.lower() in {".pdf", ".doc", ".docx", ".rtf"}


def _resolve_uploadable_cv_path(raw_path: Path) -> Path:
    candidate = Path(raw_path).resolve()
    if candidate.exists() and _is_uploadable_cv_path(candidate):
        return candidate

    stem_candidates: list[Path] = []
    for ext in (".pdf", ".docx", ".doc", ".rtf"):
        stem_candidates.append(candidate.with_suffix(ext))
    for sibling in stem_candidates:
        if sibling.exists() and sibling.is_file():
            _trace("cv_path_resolved", requested=str(raw_path), resolved=str(sibling), source="same_stem")
            return sibling

    run_folder = candidate.parent if candidate.parent.exists() else None
    if run_folder is not None:
        folder_name = run_folder.name
        parts = folder_name.split("_", 2)
        run_tag = "_".join(parts[:2]) if len(parts) >= 2 else folder_name
        if DOCUMENTS_DIR.exists() and run_tag:
            matches: list[Path] = []
            for ext in ("*.pdf", "*.docx", "*.doc", "*.rtf"):
                matches.extend(DOCUMENTS_DIR.glob(ext))
            filtered = [
                p for p in matches
                if p.is_file() and p.stem.lower().endswith(run_tag.lower())
            ]
            filtered.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            if filtered:
                _trace("cv_path_resolved", requested=str(raw_path), resolved=str(filtered[0]), source="documents_run_tag")
                return filtered[0]

    return candidate


def _upload_cv_if_needed(page, cv_path: Path) -> None:
    try:
        upload_buttons = [
            page.get_by_role("button", name=re.compile(r"(upload resume|upload cv|choose file|replace)", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"(resume)", re.IGNORECASE)),
        ]
        for locator in upload_buttons:
            try:
                if locator.count() > 0:
                    locator.first.click(timeout=1500)
                    time.sleep(0.2)
                    break
            except Exception:
                continue
    except Exception:
        pass
    try:
        upload_path = _resolve_uploadable_cv_path(cv_path)
        file_input = page.locator("input[type='file']")
        if file_input.count() > 0:
            file_input.first.set_input_files(str(upload_path))
            _trace("cv_upload_set", cv_path=str(upload_path), requested_cv_path=str(cv_path))
            time.sleep(1.0)
        else:
            _trace("cv_upload_input_missing", requested_cv_path=str(cv_path), resolved_cv_path=str(upload_path))
    except Exception:
        _trace("cv_upload_failed", requested_cv_path=str(cv_path), error="set_input_files_failed")


def _handle_apply_interstitials(page) -> None:
    prompts = [
        re.compile(r"(continue applying|continue application)", re.IGNORECASE),
        re.compile(r"(review your application)", re.IGNORECASE),
        re.compile(r"(not now)", re.IGNORECASE),
    ]
    for pattern in prompts:
        try:
            btn = page.get_by_role("button", name=pattern)
            if btn.count() > 0:
                btn.first.click(timeout=1500)
                _trace("apply_interstitial_click", pattern=pattern.pattern)
                time.sleep(0.5)
        except Exception:
            continue


def _fill_combobox_field(page, cb, desired_text: str) -> bool:
    input_id = str(cb.get_attribute("id") or "").strip()
    try:
        cb.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass
    try:
        cb.click(timeout=2000)
    except Exception:
        return False
    try:
        cb.press("Control+A")
        cb.press("Backspace")
    except Exception:
        pass
    try:
        cb.fill("")
    except Exception:
        pass
    try:
        cb.type(desired_text, delay=40, timeout=3000)
    except Exception:
        try:
            cb.fill(desired_text, timeout=3000)
        except Exception:
            return False
    time.sleep(0.4)

    option_locators = []
    if input_id:
        option_locators.append(page.locator(f"#{input_id}-ta [role='option']"))
    option_locators.extend(
        [
            page.locator("[role='listbox'] [role='option']"),
            page.locator("li[role='option']"),
            page.locator(".basic-typeahead__selectable"),
            page.locator(".search-typeahead-v2__hit"),
        ]
    )

    chosen = False
    desired_low = desired_text.lower()
    for locator in option_locators:
        try:
            count = locator.count()
        except Exception:
            count = 0
        if count <= 0:
            continue
        for i in range(min(count, 8)):
            try:
                option = locator.nth(i)
                text = str(option.inner_text(timeout=1000) or "").strip()
                if not text:
                    continue
                low = text.lower()
                if desired_low in low or low in desired_low:
                    option.click(timeout=1500)
                    chosen = True
                    break
            except Exception:
                continue
        if chosen:
            break
        try:
            locator.first.click(timeout=1500)
            chosen = True
            break
        except Exception:
            continue

    if not chosen:
        try:
            cb.press("ArrowDown")
            time.sleep(0.15)
            cb.press("Enter")
            chosen = True
        except Exception:
            chosen = False

    try:
        cb.press("Tab")
    except Exception:
        pass
    time.sleep(0.25)

    try:
        final_value = str(cb.input_value() or "").strip()
        aria_invalid = str(cb.get_attribute("aria-invalid") or "").strip().lower()
        aria_expanded = str(cb.get_attribute("aria-expanded") or "").strip().lower()
        ok = bool(final_value) and aria_invalid not in {"true", "1"} and aria_expanded not in {"true", "1"}
        if not ok:
            _trace(
                "combobox_fill_incomplete",
                input_id=input_id or "-",
                final_value=final_value[:120],
                aria_invalid=aria_invalid or "-",
                aria_expanded=aria_expanded or "-",
            )
        return ok
    except Exception:
        return chosen


def _build_location_candidates(page, base_location: str) -> list[str]:
    raw = str(base_location or "").strip()
    candidates: list[str] = []
    if raw:
        candidates.append(raw)
        parts = [x.strip() for x in raw.split(",") if x.strip()]
        if parts:
            candidates.append(parts[0])
        if len(parts) >= 2:
            candidates.append(", ".join(parts[:2]))
    try:
        page_text = str(page.locator("main").inner_text(timeout=1500) or "")
    except Exception:
        page_text = ""
    m = re.search(r"\n([A-ZÀ-ỹ][^\n]{1,80}?,\s*[A-ZÀ-ỹ][^\n]{1,80}?,\s*[A-ZÀ-ỹ][^\n]{1,80}?)\n", page_text)
    if m:
        job_loc = str(m.group(1) or "").strip()
        if job_loc:
            candidates.append(job_loc)
            parts = [x.strip() for x in job_loc.split(",") if x.strip()]
            if parts:
                candidates.append(parts[0])
            if len(parts) >= 2:
                candidates.append(", ".join(parts[:2]))
    seen = set()
    out: list[str] = []
    for item in candidates:
        key = item.lower()
        if item and key not in seen:
            out.append(item)
            seen.add(key)
    return out


def _fill_required_fields(page) -> None:
    # Defaults can be overridden in .env
    first_name = _load_env_value("LINKEDIN_FIRST_NAME") or _load_env_value("FIRST_NAME") or "Thanh"
    last_name = _load_env_value("LINKEDIN_LAST_NAME") or _load_env_value("LAST_NAME") or "Dinh"
    phone_number = _load_env_value("LINKEDIN_PHONE") or _load_env_value("PHONE_NUMBER") or "0900000000"
    location_text = _load_env_value("LINKEDIN_LOCATION") or "Hanoi, Vietnam"
    preferred_email = _load_env_value("LINKEDIN_EMAIL") or _load_env_value("EMAIL_ADDRESS")
    preferred_phone_country = _load_env_value("LINKEDIN_PHONE_COUNTRY") or "Vietnam (+84)"

    try:
        required_inputs = page.locator("div[role='dialog'] input[required]:not([role='combobox'])")
        total = required_inputs.count()
        for i in range(total):
            inp = required_inputs.nth(i)
            input_id = str(inp.get_attribute("id") or "")
            current_value = str(inp.input_value() or "").strip()
            if current_value:
                continue
            lower_id = input_id.lower()
            fill_value = ""
            if "first" in lower_id and "name" in lower_id:
                fill_value = first_name
            elif "last" in lower_id and "name" in lower_id:
                fill_value = last_name
            elif "phone" in lower_id and ("number" in lower_id or "nationalnumber" in lower_id):
                fill_value = phone_number
            elif "location" in lower_id:
                fill_value = location_text
            if fill_value:
                inp.fill(fill_value, timeout=2000)
                time.sleep(0.1)
    except Exception:
        pass

    try:
        required_selects = page.locator("div[role='dialog'] select[required]")
        total = required_selects.count()
        for i in range(total):
            sel = required_selects.nth(i)
            sid = str(sel.get_attribute("id") or "").lower()
            chosen = False
            if "phone" in sid and "country" in sid:
                try:
                    sel.select_option(label=preferred_phone_country, timeout=1500)
                    chosen = True
                except Exception:
                    chosen = False
            elif "email" in sid and preferred_email:
                try:
                    sel.select_option(label=preferred_email, timeout=1500)
                    chosen = True
                except Exception:
                    chosen = False
            if chosen:
                continue
            try:
                options = sel.locator("option")
                opt_count = options.count()
                for j in range(opt_count):
                    opt = options.nth(j)
                    text = str(opt.text_content() or "").strip()
                    value = str(opt.get_attribute("value") or "").strip()
                    low = text.lower()
                    if not text or "select an option" in low:
                        continue
                    sel.select_option(value=value)
                    chosen = True
                    break
            except Exception:
                pass
    except Exception:
        pass

    try:
        comboboxes = page.locator("div[role='dialog'] input[role='combobox'][required]")
        total = comboboxes.count()
        for i in range(total):
            cb = comboboxes.nth(i)
            current_value = str(cb.input_value() or "").strip()
            if current_value:
                continue
            label_text = ""
            try:
                label_id = str(cb.get_attribute("id") or "")
                if label_id:
                    label = page.locator(f"label[for='{label_id}']")
                    if label.count() > 0:
                        label_text = str(label.first.inner_text(timeout=1000) or "").strip().lower()
            except Exception:
                label_text = ""
            desired_value = location_text
            if "city" in label_text or "location" in label_text or not label_text:
                desired_value = location_text
            location_candidates = _build_location_candidates(page, desired_value)
            ok = False
            chosen_value = desired_value
            for candidate in location_candidates:
                chosen_value = candidate
                ok = _fill_combobox_field(page, cb, candidate)
                _trace(
                    "combobox_fill_attempt",
                    input_id=str(cb.get_attribute("id") or "-"),
                    ok=ok,
                    desired_value=candidate,
                )
                if ok:
                    break
            _trace(
                "combobox_fill_final",
                input_id=str(cb.get_attribute("id") or "-"),
                ok=ok,
                desired_value=chosen_value,
                candidates=" || ".join(location_candidates[:5]),
            )
    except Exception:
        pass


def _find_submit_button(page):
    scoped = [
        ("button[data-easy-apply-submit-button]", "Submit application"),
        ("button[data-live-test-easy-apply-submit-button]", "Submit application"),
        ("button[aria-label*='Submit']", "Submit application"),
        ("button[aria-label*='Send application']", "Send application"),
    ]
    for selector, name in scoped:
        try:
            btn = page.locator("div[role='dialog']").locator(selector)
            if btn.count() > 0:
                return btn.first, name
        except Exception:
            continue
    for name in ["Submit application", "Send application", "Review"]:
        btn = page.locator("div[role='dialog']").get_by_role("button", name=name)
        if btn.count() > 0:
            return btn.first, name
    return None, ""


def _find_next_button(page):
    selectors = [
        "button[data-easy-apply-next-button]",
        "button[data-live-test-easy-apply-next-button]",
        "button[aria-label*='Continue to next step']",
    ]
    for selector in selectors:
        try:
            btn = page.locator("div[role='dialog']").locator(selector)
            if btn.count() > 0:
                return btn.first
        except Exception:
            continue
    for name in ["Next", "Continue", "Review"]:
        btn = page.locator("div[role='dialog']").get_by_role("button", name=name)
        if btn.count() > 0:
            return btn.first
    return None


def _complete_apply_flow(page, cv_path: Path) -> tuple[bool, str]:
    try:
        for _ in range(10):
            _handle_apply_interstitials(page)
            _upload_cv_if_needed(page, cv_path)
            _fill_required_fields(page)

            submit_btn, submit_name = _find_submit_button(page)
            if submit_btn is not None and submit_name in {"Submit application", "Send application"}:
                try:
                    submit_btn.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass
                submit_btn.click(timeout=4000)
                time.sleep(1.1)
                return True, "submitted"

            next_btn = _find_next_button(page)
            if next_btn is None:
                break
            try:
                next_btn.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            try:
                disabled_attr = str(next_btn.get_attribute("disabled") or "").strip().lower()
                aria_disabled = str(next_btn.get_attribute("aria-disabled") or "").strip().lower()
                if disabled_attr or aria_disabled in {"true", "1"}:
                    _trace("apply_next_disabled", url=str(page.url or ""))
                    return False, "apply_validation_blocked"
            except Exception:
                pass
            next_btn.click(timeout=3000)
            time.sleep(0.8)
    except PlaywrightTimeoutError:
        _dismiss_apply_modal(page)
        return False, "apply_timeout"
    except Exception:
        _dismiss_apply_modal(page)
        return False, "apply_flow_failed"

    _dismiss_apply_modal(page)
    return False, "apply_not_submitted"


def _has_easy_apply_form_open(page) -> bool:
    selectors = [
        "div[role='dialog']",
        "form[data-easy-apply-form]",
        "div.jobs-easy-apply-content",
        "div.jobs-apply-form__content",
        "input[role='combobox'][required]",
        "input[type='file']",
    ]
    for selector in selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    try:
        if page.get_by_text(re.compile(r"(save this application|apply to .+|be sure to include an updated resume)", re.IGNORECASE)).count() > 0:
            return True
    except Exception:
        pass
    return False


def _open_external_apply_fallback(page) -> str:
    selectors = [
        "a[data-control-name*='jobdetails_topcard_inapply']",
        "a[data-tracking-control-name*='public_jobs_apply-link']",
        "a[data-tracking-control-name*='topcard_inapply']",
        "a[data-control-name*='jobdetails_topcard_inapply']",
        "a[href*='linkedin.com/jobs/view/externalApply']",
        "a[href*='externalApply']",
        "a[href*='apply']",
        "a[href*='linkedin.com/jobs/view/'][target='_blank']",
    ]
    href = ""
    for selector in selectors:
        try:
            node = page.locator(selector).first
            if node.count() > 0:
                href = str(node.get_attribute("href") or "").strip()
                if href:
                    break
        except Exception:
            continue
    if not href:
        try:
            anchors = page.eval_on_selector_all(
                "a[href]",
                """(nodes) => nodes.map((n) => ({href: n.href || '', text: (n.innerText || n.textContent || '').trim()}))""",
            )
            for item in anchors or []:
                text = str((item or {}).get("text") or "").strip().lower()
                link = str((item or {}).get("href") or "").strip()
                if not link:
                    continue
                if any(k in text for k in ("easy apply", "apply", "ứng tuyển", "nộp đơn", "apply now")):
                    href = link
                    break
        except Exception:
            pass
    if not href:
        return ""
    try:
        new_page = page.context.new_page()
        new_page.goto(href, wait_until="domcontentloaded", timeout=45000)
        try:
            new_page.bring_to_front()
        except Exception:
            pass
        _trace("external_apply_opened", external_url=href)
        return href
    except Exception:
        return ""


def _diagnose_apply_state(page) -> dict[str, Any]:
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    try:
        title = str(page.title() or "")
    except Exception:
        title = ""
    try:
        has_easy_apply_button = (
            page.get_by_role("button", name="Easy Apply").count() > 0
            or page.locator("button").filter(has_text="Easy Apply").count() > 0
        )
    except Exception:
        has_easy_apply_button = False
    try:
        has_apply_button = page.get_by_role("button", name="Apply").count() > 0
    except Exception:
        has_apply_button = False
    try:
        login_wall = ("login" in url.lower()) or ("checkpoint" in url.lower())
    except Exception:
        login_wall = False
    return {
        "url": url,
        "title": title[:200],
        "has_easy_apply_button": bool(has_easy_apply_button),
        "has_apply_button": bool(has_apply_button),
        "login_wall": bool(login_wall),
    }


def _capture_debug_artifacts(page, job_id: int) -> dict[str, str]:
    APPLY_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = APPLY_DEBUG_DIR / f"job_{job_id}_{stamp}.png"
    html_path = APPLY_DEBUG_DIR / f"job_{job_id}_{stamp}.html"
    out: dict[str, str] = {}
    try:
        page.screenshot(path=str(png_path), full_page=True)
        out["screenshot_path"] = str(png_path)
    except Exception:
        pass
    try:
        html_path.write_text(page.content(), encoding="utf-8", errors="ignore")
        out["html_path"] = str(html_path)
    except Exception:
        pass
    return out


def _run_easy_apply(page, cv_path: Path) -> tuple[bool, str, dict[str, Any]]:
    try:
        easy_btn = page.get_by_role("button", name=re.compile(r"(easy apply|ứng tuyển nhanh|nộp đơn nhanh)", re.IGNORECASE))
        if easy_btn.count() == 0:
            alt_btn = page.locator("button, a").filter(
                has_text=re.compile(r"(easy apply|apply now|apply|ứng tuyển|nộp đơn)", re.IGNORECASE)
            )
            if alt_btn.count() == 0:
                external_url = _open_external_apply_fallback(page)
                if external_url:
                    return False, "external_apply_opened", {"external_apply_url": external_url}
                return False, "easy_apply_button_not_found", {}
            alt_btn.first.click(timeout=4000)
        else:
            easy_btn.first.click(timeout=4000)
        time.sleep(0.6)
    except Exception:
        return False, "easy_apply_button_click_failed", {}

    if not _has_easy_apply_form_open(page):
        for _ in range(8):
            time.sleep(0.75)
            _handle_apply_interstitials(page)
            if _has_easy_apply_form_open(page):
                break
    if not _has_easy_apply_form_open(page):
        try:
            direct_job_id = _extract_job_id_from_url(str(page.url or ""))
        except Exception:
            direct_job_id = ""
        if direct_job_id:
            direct_apply_url = f"https://www.linkedin.com/jobs/view/{direct_job_id}/apply/?openSDUIApplyFlow=true"
            try:
                _trace("direct_apply_try", url=direct_apply_url)
                page.goto(direct_apply_url, wait_until="domcontentloaded", timeout=45000)
                for _ in range(12):
                    time.sleep(0.75)
                    _handle_apply_interstitials(page)
                    if _has_easy_apply_form_open(page):
                        break
                if _has_easy_apply_form_open(page):
                    ok2, status2 = _complete_apply_flow(page, cv_path=cv_path)
                    return ok2, status2, {
                        "external_apply_url": direct_apply_url,
                        "external_apply_runtime": "direct_apply_url_same_tab",
                    }
            except Exception:
                pass
        external_url = _open_external_apply_fallback(page)
        if external_url:
            meta = {"external_apply_url": external_url}
            low = external_url.lower()
            if "linkedin.com/jobs/view/" in low and "/apply/" in low:
                try:
                    candidate_pages = list(page.context.pages)
                    if page not in candidate_pages:
                        candidate_pages.append(page)
                    for _ in range(12):
                        for ext_page in reversed(candidate_pages):
                            try:
                                _handle_apply_interstitials(ext_page)
                                if _has_easy_apply_form_open(ext_page):
                                    ok2, status2 = _complete_apply_flow(ext_page, cv_path=cv_path)
                                    meta["external_apply_runtime"] = "internal_linkedin_apply_page"
                                    return ok2, status2, meta
                            except Exception:
                                continue
                        time.sleep(0.75)
                except Exception:
                    pass
            return False, "external_apply_opened", meta
        return False, "apply_form_not_opened", {}
    ok, status = _complete_apply_flow(page, cv_path=cv_path)
    return ok, status, {}


def _extract_job_id_from_url(job_url: str) -> str:
    sample = str(job_url or "")
    m = re.search(r"-(\d{7,})", sample)
    if m:
        return m.group(1)
    m = re.search(r"/jobs/view/(\d{7,})", sample)
    if m:
        return m.group(1)
    return ""


def _job_url_variants(job_url: str) -> list[str]:
    out: list[str] = []
    base = str(job_url or "").strip()
    if base:
        out.append(base)
    job_id = _extract_job_id_from_url(base)
    if job_id:
        out.append(f"https://www.linkedin.com/jobs/view/{job_id}/")
        out.append(f"https://www.linkedin.com/jobs/view/{job_id}/?trk=public_jobs_topcard-title")
    seen = set()
    unique: list[str] = []
    for u in out:
        if u and u not in seen:
            unique.append(u)
            seen.add(u)
    return unique


def _load_jobs(conn: sqlite3.Connection, job_ids: list[int]) -> list[sqlite3.Row]:
    placeholders = ",".join(["?"] * len(job_ids))
    return conn.execute(
        f"""
        SELECT id, title, company, COALESCE(job_url_final, job_url) AS job_url
        FROM job_posts
        WHERE id IN ({placeholders})
        ORDER BY id ASC
        """,
        job_ids,
    ).fetchall()


def _load_tracked_applied_job_ids(conn: sqlite3.Connection, job_ids: list[int]) -> set[int]:
    if not job_ids:
        return set()
    placeholders = ",".join(["?"] * len(job_ids))
    rows = conn.execute(
        f"""
        SELECT job_post_id
        FROM job_application_tracking
        WHERE job_post_id IN ({placeholders})
          AND COALESCE(is_applied, 0) = 1
        """,
        job_ids,
    ).fetchall()
    return {int(r[0]) for r in rows if r and r[0] is not None}


def _load_env_value(key: str) -> str:
    val = str(os.getenv(key, "") or "").strip()
    if val:
        return val
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        if k.strip() == key:
            return v.strip().strip("'").strip('"')
    return ""


def _try_cookie_auth(context, page) -> bool:
    li_at = _load_env_value("LI_AT")
    jsession = _load_env_value("JSESSIONID")
    if not li_at and not jsession:
        return False
    cookies = []
    if li_at:
        cookies.append(
            {
                "name": "li_at",
                "value": li_at,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }
        )
    if jsession:
        cookies.append(
            {
                "name": "JSESSIONID",
                "value": jsession,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
            }
        )
    context.add_cookies(cookies)
    probe = context.new_page()
    try:
        probe.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=45000)
        current = str(probe.url).lower()
        return ("login" not in current) and ("checkpoint" not in current)
    finally:
        probe.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply selected jobs on LinkedIn via Easy Apply.")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--job-ids", required=True, help="Comma separated job ids")
    parser.add_argument("--cv-paths", required=True, help="Comma separated cv file paths")
    parser.add_argument("--profile-dir", default=".pw-profile")
    parser.add_argument("--cdp-url", default="")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-browser-open", action="store_true")
    parser.add_argument("--allow-playwright-launch", action="store_true")
    parser.add_argument("--skip-tracked-applied", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db_path).resolve()
    if not db_path.exists():
        raise ValueError(f"DB not found: {db_path}")

    job_ids = [int(x.strip()) for x in str(args.job_ids).split(",") if x.strip()]
    cv_paths = [_resolve_uploadable_cv_path(Path(x.strip()).resolve()) for x in str(args.cv_paths).split(",") if x.strip()]
    if not job_ids:
        raise ValueError("No job_ids")
    if not cv_paths:
        raise ValueError("No cv_paths")
    missing = [str(p) for p in cv_paths if not p.exists()]
    if missing:
        raise ValueError(f"Some CV files do not exist: {missing}")
    not_uploadable = [str(p) for p in cv_paths if not _is_uploadable_cv_path(p)]
    if not_uploadable:
        raise ValueError(f"Some CV files are not uploadable (.pdf/.doc/.docx/.rtf): {not_uploadable}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        _trace("start", db_path=str(db_path), job_ids=",".join(str(x) for x in job_ids), cv_count=len(cv_paths))
        rows = _load_jobs(conn, job_ids)
        if not rows:
            raise ValueError("No jobs found for provided job_ids")
        skip_tracked_applied = True
        if bool(args.skip_tracked_applied):
            skip_tracked_applied = True
        skip_env = str(_load_env_value("LINKEDIN_SKIP_TRACKED_APPLIED") or "").strip().lower()
        if skip_env in {"0", "false", "no", "off"}:
            skip_tracked_applied = False
        tracked_applied_ids = _load_tracked_applied_job_ids(conn, job_ids) if skip_tracked_applied else set()
        _trace(
            "tracked_applied_loaded",
            enabled=skip_tracked_applied,
            tracked_count=len(tracked_applied_ids),
        )

        results: list[dict[str, Any]] = []
        if args.dry_run:
            for idx, row in enumerate(rows):
                cv_path = cv_paths[idx % len(cv_paths)]
                results.append(
                    {
                        "job_id": int(row["id"]),
                        "title": str(row["title"] or ""),
                        "company": str(row["company"] or ""),
                        "job_url": str(row["job_url"] or ""),
                        "cv_path": str(cv_path),
                        "ok": True,
                        "status": "dry_run",
                    }
                )
            print({"ok": True, "dry_run": True, "results": results})
            return

        cdp_url = str(args.cdp_url or "").strip()
        if not cdp_url:
            cdp_url = _load_env_value("CHROME_CDP_URL") or _load_env_value("LINKEDIN_CDP_URL") or "http://127.0.0.1:9222"
        keep_browser_open = True
        if bool(args.keep_browser_open):
            keep_browser_open = True
        keep_open_env = str(_load_env_value("LINKEDIN_KEEP_BROWSER_OPEN") or "").strip().lower()
        if keep_open_env in {"0", "false", "no", "off"}:
            keep_browser_open = False
        keep_open_seconds = 900
        keep_open_seconds_env = str(_load_env_value("LINKEDIN_KEEP_BROWSER_OPEN_SECONDS") or "").strip()
        if keep_open_seconds_env:
            try:
                keep_open_seconds = max(0, int(keep_open_seconds_env))
            except Exception:
                keep_open_seconds = 900
        allow_playwright_launch = bool(args.allow_playwright_launch) or (
            str(_load_env_value("LINKEDIN_ALLOW_PLAYWRIGHT_LAUNCH") or "").strip().lower() in {"1", "true", "yes", "on"}
        )
        load_extension = str(_load_env_value("LINKEDIN_LOAD_EXTENSION") or "1").strip().lower() not in {"0", "false", "no", "off"}
        extension_path = str(_load_env_value("LINKEDIN_EXTENSION_PATH") or "").strip()
        if not extension_path:
            default_extension_path = (PROJECT_ROOT / "chrome-collected-extension").resolve()
            if default_extension_path.exists():
                extension_path = str(default_extension_path)

        profile_dir = Path(args.profile_dir).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            context = None
            using_cdp = False
            runtime_mode = "persistent"
            if cdp_url:
                try:
                    _trace("cdp_connect_attempt", cdp_url=cdp_url)
                    browser = p.chromium.connect_over_cdp(cdp_url)
                    if browser.contexts:
                        context = browser.contexts[0]
                    else:
                        context = browser.new_context(viewport={"width": 1460, "height": 960})
                    using_cdp = True
                    runtime_mode = "cdp_existing_browser"
                    _trace("cdp_connect_ok", runtime_mode=runtime_mode)
                except Exception:
                    _trace("cdp_connect_failed", cdp_url=cdp_url)
                    context = None
            if context is None:
                if not allow_playwright_launch:
                    raise ValueError(
                        "Cannot connect to existing Chrome via CDP. Start Chrome with "
                        "'--remote-debugging-port=9222' and set CHROME_CDP_URL if needed."
                    )
                launch_kwargs: dict[str, Any] = {
                    "user_data_dir": str(profile_dir),
                    "headless": bool(args.headless),
                    "channel": "chrome",
                    "viewport": {"width": 1460, "height": 960},
                }
                if load_extension and extension_path and Path(extension_path).exists():
                    launch_kwargs["channel"] = "chromium"
                    launch_kwargs["args"] = [
                        f"--disable-extensions-except={extension_path}",
                        f"--load-extension={extension_path}",
                    ]
                    _trace("fallback_extension_enabled", extension_path=extension_path)
                context = p.chromium.launch_persistent_context(**launch_kwargs)
                runtime_mode = "playwright_persistent"
                _trace("playwright_launch_fallback", runtime_mode=runtime_mode)
            context.on("page", lambda popup: _attach_page_debug_listeners(popup, runtime_mode=runtime_mode))
            page = context.new_page()
            _attach_page_debug_listeners(page, runtime_mode=runtime_mode)
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
            if "login" in page.url or "checkpoint" in page.url:
                if _try_cookie_auth(context, page):
                    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=45000)
                current = str(page.url).lower()
                if "login" in current or "checkpoint" in current:
                    if args.headless:
                        raise ValueError("LinkedIn login required in .pw-profile (run once non-headless and login).")
                    print("LinkedIn login required. Complete login in opened Chrome window (waiting up to 180s)...")
                    deadline = time.time() + 180
                    logged_in = False
                    while time.time() < deadline:
                        try:
                            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            time.sleep(2)
                            continue
                        current = str(page.url).lower()
                        if ("login" not in current) and ("checkpoint" not in current):
                            logged_in = True
                            break
                        time.sleep(2)
                    if not logged_in:
                        raise ValueError("LinkedIn login required in .pw-profile (run once non-headless and login).")

            for idx, row in enumerate(rows):
                job_id = int(row["id"])
                job_url = str(row["job_url"] or "").strip()
                cv_path = cv_paths[idx % len(cv_paths)]
                _attach_page_debug_listeners(page, runtime_mode=runtime_mode, job_id=job_id)
                _trace("job_start", job_id=job_id, runtime_mode=runtime_mode)
                if job_id in tracked_applied_ids:
                    result = {
                        "job_id": job_id,
                        "title": str(row["title"] or ""),
                        "company": str(row["company"] or ""),
                        "job_url": job_url,
                        "cv_path": str(cv_path),
                        "ok": True,
                        "status": "already_applied_tracked",
                        "runtime_mode": runtime_mode,
                        "trace_log_path": str(TRACE_LOG_PATH),
                    }
                    results.append(result)
                    _trace("job_skip_already_applied", job_id=job_id)
                    continue
                if not job_url:
                    results.append({"job_id": job_id, "ok": False, "status": "missing_job_url", "cv_path": str(cv_path)})
                    _trace("job_missing_url", job_id=job_id)
                    continue
                try:
                    ok, status = False, "job_open_failed"
                    meta: dict[str, Any] = {}
                    for candidate_url in _job_url_variants(job_url):
                        _trace("job_open_try", job_id=job_id, url=candidate_url)
                        page.goto(candidate_url, wait_until="domcontentloaded", timeout=45000)
                        time.sleep(1.0)
                        ok, status, meta = _run_easy_apply(page, cv_path=cv_path)
                        _trace("job_apply_status", job_id=job_id, status=status, ok=ok)
                        if status != "easy_apply_button_not_found":
                            break
                    diag = _diagnose_apply_state(page)
                except Exception:
                    ok, status = False, "job_open_failed"
                    meta = {}
                    diag = {"url": job_url, "title": "", "has_easy_apply_button": False, "has_apply_button": False, "login_wall": False}
                    _trace("job_exception", job_id=job_id, status=status)
                debug_artifacts: dict[str, str] = {}
                if not ok:
                    try:
                        debug_artifacts = _capture_debug_artifacts(page, job_id=job_id)
                    except Exception:
                        debug_artifacts = {}
                _trace("job_done", job_id=job_id, status=status, ok=ok)
                result = {
                    "job_id": job_id,
                    "title": str(row["title"] or ""),
                    "company": str(row["company"] or ""),
                    "job_url": job_url,
                    "cv_path": str(cv_path),
                    "ok": bool(ok),
                    "status": status,
                    "diagnostic": diag,
                    "runtime_mode": runtime_mode,
                    "trace_log_path": str(TRACE_LOG_PATH),
                }
                external_apply_url = str(meta.get("external_apply_url") or "").strip() if isinstance(meta, dict) else ""
                if external_apply_url:
                    result["external_apply_url"] = external_apply_url
                if debug_artifacts:
                    result["debug_artifacts"] = debug_artifacts
                results.append(result)
                if ok:
                    _upsert_applied(conn, job_post_id=job_id, payload=result)
                    conn.commit()

            if not keep_browser_open and not using_cdp:
                context.close()
                _trace("context_closed", using_cdp=using_cdp)
            else:
                _trace("context_kept_open", using_cdp=using_cdp, keep_browser_open=keep_browser_open)
                if not using_cdp and keep_open_seconds > 0:
                    _trace("keep_browser_wait_start", seconds=keep_open_seconds)
                    time.sleep(keep_open_seconds)
                    _trace("keep_browser_wait_end", seconds=keep_open_seconds)

        ok_count = sum(1 for x in results if x.get("ok"))
        acceptable_non_submit_statuses = {"already_applied_tracked"}
        accepted_count = sum(
            1
            for x in results
            if x.get("ok") or str(x.get("status") or "") in acceptable_non_submit_statuses
        )
        failed_count = len(results) - accepted_count
        print({"ok": failed_count == 0, "results": results, "ok_count": ok_count, "failed_count": failed_count})
        _trace("end", ok=(failed_count == 0), ok_count=ok_count, failed_count=failed_count)
        if failed_count > 0:
            raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
