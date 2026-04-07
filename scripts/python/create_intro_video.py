from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:5182"
DEFAULT_OUTPUT = ROOT / "showcase_assets" / "video" / "job_ops_project_showcase.mp4"
DEFAULT_SCREENSHOT_DIR = ROOT / "showcase_assets" / "images"
VIEWPORT = {"width": 1280, "height": 720}
CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def resolve_browser_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
        raise FileNotFoundError(f"Browser executable not found: {path}")
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No Chrome/Edge executable found on this machine.")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def set_caption(page, title: str, subtitle: str = "") -> None:
    page.evaluate(
        """
        ([title, subtitle]) => {
          let box = document.getElementById('intro-video-caption');
          if (!box) {
            box = document.createElement('div');
            box.id = 'intro-video-caption';
            box.style.position = 'fixed';
            box.style.right = '18px';
            box.style.top = '18px';
            box.style.zIndex = '999999';
            box.style.maxWidth = '380px';
            box.style.padding = '12px 14px';
            box.style.borderRadius = '14px';
            box.style.background = 'rgba(12, 18, 28, 0.70)';
            box.style.color = '#f8fafc';
            box.style.backdropFilter = 'blur(8px)';
            box.style.boxShadow = '0 12px 32px rgba(15, 23, 42, 0.22)';
            box.style.fontFamily = 'Segoe UI, Arial, sans-serif';
            box.style.transition = 'opacity 250ms ease';
            document.body.appendChild(box);
          }
          const safeTitle = String(title || '');
          const safeSubtitle = String(subtitle || '');
          box.innerHTML = `
            <div style="font-size: 22px; font-weight: 700; line-height: 1.15; margin-bottom: 6px;">${safeTitle}</div>
            <div style="font-size: 13px; line-height: 1.35; opacity: 0.95;">${safeSubtitle}</div>
          `;
          box.style.opacity = '1';
        }
        """,
        [title, subtitle],
    )


def clear_caption(page) -> None:
    page.evaluate(
        """
        () => {
          const box = document.getElementById('intro-video-caption');
          if (box) box.style.opacity = '0';
        }
        """
    )


def smooth_scroll_into_view(page, selector: str, delay: float = 1.4) -> None:
    locator = page.locator(selector).first
    locator.wait_for(timeout=15000)
    locator.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'start' })")
    sleep(delay)


def scroll_to_top(page, delay: float = 0.8) -> None:
    page.evaluate("() => window.scrollTo({ top: 0, behavior: 'smooth' })")
    sleep(delay)


def hover_trend_points(page) -> None:
    points = page.locator("circle.chart-point-daily")
    count = points.count()
    if count == 0:
        return
    indices: list[int] = []
    if count >= 5:
        indices = [0, count // 4, count // 2, max(0, count - 3), count - 1]
    else:
        indices = list(range(count))
    for idx in indices:
        point = points.nth(idx)
        point.scroll_into_view_if_needed(timeout=5000)
        box = point.bounding_box()
        if not box:
            continue
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
        sleep(0.7)


def interact_with_map(page) -> None:
    shell = page.locator(".world-map-shell").first
    shell.wait_for(timeout=15000)
    box = shell.bounding_box()
    if not box:
        return
    center_x = box["x"] + box["width"] * 0.58
    center_y = box["y"] + box["height"] * 0.48
    page.mouse.move(center_x, center_y, steps=25)
    sleep(0.4)
    page.mouse.wheel(0, -900)
    sleep(1.2)
    page.mouse.wheel(0, 650)
    sleep(1.2)


def open_tab(page, label: str) -> None:
    page.get_by_role("button", name=label, exact=True).click()
    sleep(2.5)


def wait_for_jobs_table(page) -> None:
    page.locator(".jobs-table").first.wait_for(timeout=45000)
    sleep(1.0)


def wait_for_dashboard(page) -> None:
    page.locator("h3", has_text="Jobs Density Map").first.wait_for(timeout=20000)
    sleep(1.0)


def wait_for_analytics(page) -> None:
    page.locator("table").first.wait_for(timeout=20000)
    sleep(0.8)


def wait_for_learning(page) -> None:
    page.locator(".learning-toolbar").first.wait_for(timeout=20000)
    sleep(0.8)


def wait_for_automation(page) -> None:
    page.locator("h3", has_text="Schedules").first.wait_for(timeout=20000)
    sleep(0.8)


def wait_for_modal(page) -> bool:
    try:
        page.locator(".modal-panel").first.wait_for(timeout=5000)
        sleep(0.5)
        return True
    except Exception:
        return False


def close_modal(page) -> None:
    try:
        close_btn = page.get_by_role("button", name="Close", exact=True)
        if close_btn.count() > 0:
            close_btn.first.click()
        else:
            page.keyboard.press("Escape")
        page.locator(".modal-backdrop").first.wait_for(state="hidden", timeout=5000)
        sleep(0.4)
    except Exception:
        pass


def maybe_open_first_job_detail(page) -> bool:
    rows = page.locator("tbody tr")
    if rows.count() == 0:
        return False
    detail_btn = rows.first.locator("button.link-btn").first
    if detail_btn.count() == 0:
        return False
    detail_btn.click()
    return wait_for_modal(page)


def maybe_open_cv_preview(page) -> bool:
    rows = page.locator("tbody tr")
    if rows.count() == 0:
        return False
    cv_btn = rows.first.get_by_role("button", name="CV", exact=True)
    if cv_btn.count() == 0:
        return False
    cv_btn.click()
    return wait_for_modal(page)


def capture_page(page, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output_path), full_page=False)


def open_learning_knowledge(page) -> None:
    page.get_by_role("button", name="Knowledge", exact=True).click()
    sleep(1.0)


def start_learning_quiz(page) -> None:
    page.get_by_role("button", name="Start Quiz", exact=True).click()
    sleep(1.5)


def show_focus_slide(page, title: str, bullets: list[str], footer: str = "") -> None:
    page.evaluate(
        """
        ([title, bullets, footer]) => {
          let layer = document.getElementById('intro-video-focus-slide');
          if (!layer) {
            layer = document.createElement('div');
            layer.id = 'intro-video-focus-slide';
            layer.style.position = 'fixed';
            layer.style.inset = '0';
            layer.style.zIndex = '999998';
            layer.style.display = 'flex';
            layer.style.alignItems = 'center';
            layer.style.justifyContent = 'center';
            layer.style.background = 'linear-gradient(160deg, rgba(8,15,26,0.86), rgba(15,23,42,0.90))';
            layer.style.backdropFilter = 'blur(6px)';
            layer.style.padding = '40px';
            document.body.appendChild(layer);
          }
          const safeTitle = String(title || '');
          const safeFooter = String(footer || '');
          const items = Array.isArray(bullets) ? bullets : [];
          const bulletHtml = items
            .map((item) => `<li style="margin: 0 0 12px 0; line-height: 1.45;">${String(item || '')}</li>`)
            .join('');
          layer.innerHTML = `
            <div style="width: min(900px, 92vw); border-radius: 26px; padding: 30px 34px; background: rgba(15, 23, 42, 0.92); color: #f8fafc; box-shadow: 0 24px 60px rgba(0,0,0,0.35); font-family: 'Segoe UI', Arial, sans-serif;">
              <div style="font-size: 34px; font-weight: 700; margin-bottom: 16px;">${safeTitle}</div>
              <ul style="font-size: 21px; margin: 0 0 18px 22px; padding: 0;">${bulletHtml}</ul>
              <div style="font-size: 15px; opacity: 0.88;">${safeFooter}</div>
            </div>
          `;
        }
        """,
        [title, bullets, footer],
    )


def hide_focus_slide(page) -> None:
    page.evaluate(
        """
        () => {
          const layer = document.getElementById('intro-video-focus-slide');
          if (layer) layer.remove();
        }
        """
    )


def capture_showcase_screenshots(browser, url: str, screenshot_dir: Path) -> None:
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    page.goto(url, wait_until="networkidle")
    wait_for_dashboard(page)
    clear_caption(page)

    scroll_to_top(page)
    capture_page(page, screenshot_dir / "dashboard_overview.png")

    smooth_scroll_into_view(page, "h3:has-text('Jobs Density Map')", delay=1.0)
    capture_page(page, screenshot_dir / "jobs_density_map.png")

    smooth_scroll_into_view(page, "h3:has-text('Applied Jobs Trend')", delay=0.8)
    capture_page(page, screenshot_dir / "applied_jobs_trend.png")

    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    capture_page(page, screenshot_dir / "jobs_workspace.png")
    if maybe_open_first_job_detail(page):
        capture_page(page, screenshot_dir / "jobs_detail_modal.png")
        close_modal(page)
    if maybe_open_cv_preview(page):
        capture_page(page, screenshot_dir / "cv_preview_modal.png")
        close_modal(page)

    open_tab(page, "Applied Jobs")
    wait_for_jobs_table(page)
    capture_page(page, screenshot_dir / "applied_jobs_workspace.png")

    open_tab(page, "Reposts Analytics")
    wait_for_analytics(page)
    capture_page(page, screenshot_dir / "analytics_reposts.png")

    open_tab(page, "Learning Quiz")
    wait_for_learning(page)
    start_learning_quiz(page)
    capture_page(page, screenshot_dir / "learning_quiz.png")
    open_learning_knowledge(page)
    capture_page(page, screenshot_dir / "learning_knowledge.png")

    open_tab(page, "Automation")
    wait_for_automation(page)
    scroll_to_top(page, delay=0.6)
    capture_page(page, screenshot_dir / "automation_summary.png")
    smooth_scroll_into_view(page, "h3:has-text('Schedules')", delay=0.8)
    capture_page(page, screenshot_dir / "automation_schedules.png")
    smooth_scroll_into_view(page, "h3:has-text('Runs')", delay=0.8)
    capture_page(page, screenshot_dir / "automation_runs.png")
    scroll_to_top(page, delay=0.6)
    capture_page(page, screenshot_dir / "automation_console.png")

    context.close()


def record_showcase_flow(page) -> None:
    wait_for_dashboard(page)
    set_caption(page, "Job Ops Console", "A local-first workflow for crawl, fit review, artifact generation, and apply tracking")
    sleep(2.2)

    clear_caption(page)
    scroll_to_top(page, delay=0.6)
    set_caption(page, "Dashboard Overview", "Metrics, geo coverage, and execution visibility in one operator workspace")
    sleep(1.8)

    smooth_scroll_into_view(page, "h3:has-text('Jobs Density Map')", delay=1.0)
    set_caption(page, "Geo Analytics", "Country-level job density map with pan and zoom interactions")
    interact_with_map(page)

    smooth_scroll_into_view(page, "h3:has-text('Applied Jobs Trend')", delay=0.9)
    set_caption(page, "Applied Trend Tracking", "Daily and cumulative progress views for application operations")
    hover_trend_points(page)
    sleep(0.7)

    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    set_caption(page, "Jobs Workspace", "Search, filter, evaluate fit, and trigger CV or apply actions from a single queue")
    page.locator("tbody tr").nth(0).hover()
    sleep(1.6)

    open_tab(page, "Applied Jobs")
    wait_for_jobs_table(page)
    set_caption(page, "Applied Jobs View", "The applied pipeline stays separate so follow-up and status review stay focused")
    page.locator("tbody tr").nth(0).hover()
    sleep(1.5)

    open_tab(page, "Reposts Analytics")
    wait_for_analytics(page)
    set_caption(page, "Analytics", "Repost patterns and operational history help prioritize repeated opportunities")
    sleep(1.7)

    open_tab(page, "Learning Quiz")
    wait_for_learning(page)
    open_learning_knowledge(page)
    set_caption(page, "Learning + Knowledge", "The console also includes structured theory review and quiz flows")
    sleep(1.7)

    start_learning_quiz(page)
    set_caption(page, "Interactive Quiz Flow", "Knowledge review and quiz history live in the same operator experience")
    sleep(1.6)

    open_tab(page, "Automation")
    wait_for_automation(page)
    set_caption(page, "Automation Control", "Manual actions, schedules, and run history make the workflow observable and repeatable")
    sleep(1.6)

    smooth_scroll_into_view(page, "h3:has-text('Schedules')", delay=0.8)
    sleep(1.4)

    clear_caption(page)
    show_focus_slide(
        page,
        "Architecture Snapshot",
        [
            "Playwright + parsers collect job data and normalize it into SQLite.",
            "FastAPI services handle fit evaluation, artifact generation, schedules, and file delivery.",
            "React operator console keeps dashboard, jobs, analytics, learning, and automation in one workspace.",
            "RAG and offline LLM steps are guarded by validators and deterministic fallbacks.",
        ],
        "Designed to stay practical on a local, CPU-only machine with low RAM and lightweight persistence.",
    )
    sleep(5.2)
    hide_focus_slide(page)

    clear_caption(page)
    sleep(0.6)


def record_video(url: str, output_path: Path, browser_path: Path, audio_path: Path, screenshot_dir: Path | None = None) -> Path:
    output_dir = output_path.parent
    ensure_dir(output_dir)
    temp_dir = output_dir / "_tmp_intro_video"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    ensure_dir(temp_dir)

    raw_video_path: Path | None = None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(browser_path), headless=True)
        if screenshot_dir is not None:
            try:
                capture_showcase_screenshots(browser, url, screenshot_dir)
            except Exception as exc:
                print(f"Warning: screenshot refresh skipped due to error: {exc}", file=sys.stderr)
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(temp_dir),
            record_video_size=VIEWPORT,
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        record_showcase_flow(page)

        video = page.video
        context.close()
        browser.close()
        if video is None:
            raise RuntimeError("Playwright did not produce a video artifact.")
        raw_video_path = Path(video.path())

    if raw_video_path is None or not raw_video_path.exists():
        raise FileNotFoundError("Raw Playwright video was not found after recording.")

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(ffmpeg_cmd, check=True)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a short intro video for the Job Ops application.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Application URL to record.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Final MP4 output path.")
    parser.add_argument("--screenshots-dir", default=str(DEFAULT_SCREENSHOT_DIR), help="Directory for refreshed showcase screenshots.")
    parser.add_argument("--audio", required=True, help="Narration WAV path.")
    parser.add_argument("--browser", default=None, help="Optional browser executable path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).resolve()
    screenshot_dir = Path(args.screenshots_dir).resolve() if args.screenshots_dir else None
    audio_path = Path(args.audio).resolve()
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    browser_path = resolve_browser_path(args.browser)
    final_video = record_video(args.url, output_path, browser_path, audio_path, screenshot_dir=screenshot_dir)
    print(final_video)
    return 0


if __name__ == "__main__":
    sys.exit(main())
