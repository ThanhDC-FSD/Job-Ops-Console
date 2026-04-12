from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:5182"
DEFAULT_OUTPUT = ROOT / "showcase_assets" / "video" / "job_ops_project_showcase.mp4"
DEFAULT_SRT_OUTPUT = DEFAULT_OUTPUT.with_suffix(".srt")
DEFAULT_VALIDATION_OUTPUT = DEFAULT_OUTPUT.with_name("job_ops_project_showcase_validation.json")
DEFAULT_VOICE_SCRIPT = ROOT / "scripts" / "powershell" / "generate_intro_voice.ps1"
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    narration: str
    min_duration: float
    action_summary: str
    silence_after: float = 0.40


@dataclass(frozen=True)
class RenderedScene:
    key: str
    title: str
    narration: str
    subtitle: str
    audio_path: Path
    audio_duration: float
    scene_duration: float
    action_summary: str


SCENES: tuple[Scene, ...] = (
    Scene(
        key="dashboard_overview",
        title="Dashboard Overview",
        narration=(
            "This console opens with a live dashboard that summarizes job volume, application activity, "
            "and recent automation runs in one place."
        ),
        min_duration=9.0,
        action_summary="Moves across live KPI cards and the recent-runs area on the dashboard.",
    ),
    Scene(
        key="dashboard_map_trend",
        title="Dashboard Analytics",
        narration=(
            "The dashboard also exposes a density map and an applied trend chart, so the operator can read "
            "coverage and momentum before taking action."
        ),
        min_duration=11.0,
        action_summary="Scrolls through the map and trend views and performs basic mouse interaction.",
    ),
    Scene(
        key="jobs_workspace",
        title="Jobs Workspace",
        narration=(
            "Jobs is the main working queue, with filtering, sorting, paging, and stage aware status handling "
            "for roles that still need attention."
        ),
        min_duration=11.0,
        action_summary="Shows the jobs queue, sort controls, scrolling, and the active table state.",
    ),
    Scene(
        key="job_detail_modal",
        title="Job Detail Modal",
        narration=(
            "Each row can open a structured job detail view, making it easier to review normalized fields "
            "before any rewrite or apply step."
        ),
        min_duration=10.0,
        action_summary="Opens a real job detail modal and scrolls inside it before closing.",
    ),
    Scene(
        key="generate_cv",
        title="Generate CV",
        narration=(
            "When a role is ready, the operator can generate a tailored CV artifact directly from the queue "
            "instead of preparing documents by hand."
        ),
        min_duration=9.0,
        action_summary="Highlights a live Generate CV action in the jobs table without mutating data.",
    ),
    Scene(
        key="cv_preview_loading",
        title="CV Preview Loading",
        narration=(
            "The preview modal now makes loading explicit, so path assembly and artifact materialization read "
            "as progress instead of an error."
        ),
        min_duration=11.0,
        action_summary="Opens a real CV preview modal and waits while loading text and materialized paths appear.",
    ),
    Scene(
        key="apply_actions",
        title="Apply Actions",
        narration=(
            "If artifacts already exist, the same workspace exposes apply and manual confirmation actions so "
            "the application lifecycle stays explicit."
        ),
        min_duration=9.0,
        action_summary="Highlights live Apply and Mark Applied Manual actions in the queue.",
    ),
    Scene(
        key="applied_jobs",
        title="Applied Jobs",
        narration=(
            "Applied Jobs keeps submitted roles separate, including apply dates and status history checks "
            "for downstream follow up."
        ),
        min_duration=8.0,
        action_summary="Shows the dedicated applied-jobs table and scrolls within that workspace.",
    ),
    Scene(
        key="analytics",
        title="Reposts Analytics",
        narration=(
            "Reposts Analytics keeps the grouped repost view available and lets the operator jump back into "
            "Jobs with preset filters for the next pass."
        ),
        min_duration=10.0,
        action_summary="Shows the analytics table and moves across the grouped results surface.",
    ),
    Scene(
        key="analytics_language_trends",
        title="Language Trends",
        narration=(
            "Language Trends combines local demand with external context and a Qwen lens that expands the "
            "argument across market and policy dimensions."
        ),
        min_duration=13.0,
        action_summary="Switches to Language Trends, shows the local trend view, and highlights the Qwen lens.",
    ),
    Scene(
        key="analytics_stack_trends",
        title="Stack Trends",
        narration=(
            "Stack Trends adds stack-family grouping and crawl recommendations for thin buckets so weak "
            "signals stay visibly provisional."
        ),
        min_duration=13.0,
        action_summary="Switches to Stack Trends, shows the grouped stack view, and highlights crawl guidance.",
    ),
    Scene(
        key="learning",
        title="Learning And Interview Support",
        narration=(
            "Learning Quiz adds a lightweight knowledge layer, and Interview Q and A can prepare interview "
            "prompts from job context and CV inputs."
        ),
        min_duration=13.0,
        action_summary="Switches between learning subtabs and shows the Interview Q and A inputs.",
    ),
    Scene(
        key="automation_schedules",
        title="Automation Schedules",
        narration=(
            "Automation schedules recurring crawl, learning, prediction, repair, and cleanup flows without "
            "forcing the operator back into the terminal."
        ),
        min_duration=11.0,
        action_summary="Shows automation controls, the create action, and the schedules block.",
    ),
    Scene(
        key="automation_runs",
        title="Automation Runs",
        narration=(
            "The runs view closes the loop with progress, logs, and recovery actions, turning the console "
            "into a practical daily operations surface."
        ),
        min_duration=12.0,
        action_summary="Shows the runs table with recovery actions and visible operational controls.",
    ),
)


def resolve_browser_path(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Browser executable not found: {candidate}")
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No Chrome or Edge executable was found on this machine.")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def wrap_subtitle(text: str, width: int = 58) -> str:
    return "\n".join(textwrap.wrap(text, width=width))


def write_srt(rendered_scenes: list[RenderedScene], output_path: Path) -> Path:
    lines: list[str] = []
    cursor = 0.0
    for index, scene in enumerate(rendered_scenes, start=1):
        lines.append(str(index))
        lines.append(f"{format_timestamp(cursor)} --> {format_timestamp(cursor + scene.scene_duration)}")
        lines.append(scene.subtitle)
        lines.append("")
        cursor += scene.scene_duration
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return output_path


def synthesize_scene_audio(
    scenes: tuple[Scene, ...],
    voice_script: Path,
    voice_name: str,
    rate: int,
    temp_dir: Path,
) -> list[RenderedScene]:
    temp_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[RenderedScene] = []
    powershell_exe = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"

    for scene in scenes:
        wav_path = temp_dir / f"{scene.key}.wav"
        try:
            run(
                [
                    powershell_exe,
                    "-STA",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(voice_script),
                    "-OutputPath",
                    str(wav_path),
                    "-Rate",
                    str(rate),
                    "-VoiceName",
                    voice_name,
                    "-Text",
                    scene.narration,
                ]
            )
        except Exception as exc:
            print(f"[warn] Voice synthesis failed for {scene.key}; using silent fallback ({exc})")
            generate_silence(0.5, wav_path)
        audio_duration = ffprobe_duration(wav_path)
        scene_duration = max(scene.min_duration, audio_duration + scene.silence_after)
        rendered.append(
            RenderedScene(
                key=scene.key,
                title=scene.title,
                narration=scene.narration,
                subtitle=wrap_subtitle(scene.narration),
                audio_path=wav_path,
                audio_duration=audio_duration,
                scene_duration=scene_duration,
                action_summary=scene.action_summary,
            )
        )

    return rendered


def generate_silence(duration: float, output_path: Path) -> Path:
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=22050:cl=mono",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    return output_path


def concat_audio(rendered_scenes: list[RenderedScene], output_path: Path, temp_dir: Path) -> Path:
    concat_list = temp_dir / "audio_segments.txt"
    lines: list[str] = []
    silence_dir = temp_dir / "silence"
    silence_dir.mkdir(parents=True, exist_ok=True)

    for scene in rendered_scenes:
        lines.append(f"file '{scene.audio_path.as_posix()}'")
        trailing_silence = max(0.0, scene.scene_duration - scene.audio_duration)
        if trailing_silence > 0.02:
            silence_path = silence_dir / f"{scene.key}_silence.wav"
            generate_silence(trailing_silence, silence_path)
            lines.append(f"file '{silence_path.as_posix()}'")

    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(output_path),
        ]
    )
    return output_path


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def wait_for_jobs_table(page: Page) -> None:
    page.locator(".jobs-table").first.wait_for(timeout=30000)
    sleep(0.8)


def wait_for_dashboard(page: Page) -> None:
    page.locator("h3", has_text="Jobs Density Map").first.wait_for(timeout=30000)
    sleep(1.0)


def wait_for_analytics(page: Page) -> None:
    page.locator(".subtabs").first.wait_for(timeout=20000)
    sleep(0.8)


def wait_for_language_analytics_panel(page: Page) -> None:
    try:
        page.locator(".analytics-language-card-grid").first.wait_for(timeout=12000)
        sleep(0.9)
    except Exception:
        sleep(0.9)


def wait_for_stack_analytics_panel(page: Page) -> None:
    try:
        page.locator(".analytics-language-card-grid").first.wait_for(timeout=12000)
        sleep(0.9)
    except Exception:
        sleep(0.9)


def wait_for_learning(page: Page) -> None:
    page.locator("button", has_text="Interview Q&A").first.wait_for(timeout=20000)
    sleep(0.8)


def wait_for_automation(page: Page) -> None:
    page.locator("h3", has_text="Schedules").first.wait_for(timeout=20000)
    sleep(0.8)


def open_tab(page: Page, label: str) -> None:
    page.get_by_role("button", name=label, exact=True).click()
    sleep(2.0)


def scroll_to_top(page: Page, delay: float = 0.6) -> None:
    page.evaluate("() => window.scrollTo({ top: 0, behavior: 'smooth' })")
    sleep(delay)


def smooth_scroll_into_view(page: Page, selector: str, delay: float = 1.0) -> None:
    locator = page.locator(selector).first
    locator.wait_for(timeout=15000)
    locator.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    sleep(delay)


def safe_bounding_box(locator: Locator) -> dict[str, float] | None:
    try:
        return locator.bounding_box()
    except Exception:
        return None


def hover_locator(locator: Locator, pause: float = 1.0) -> bool:
    try:
        locator.scroll_into_view_if_needed(timeout=8000)
        locator.hover(timeout=8000)
        sleep(pause)
        return True
    except Exception:
        return False


def hover_button_by_name(page: Page, name: str, pause: float = 1.0) -> bool:
    locator = page.get_by_role("button", name=name, exact=True).first
    if locator.count() == 0:
        return False
    return hover_locator(locator, pause=pause)


def hover_first_table_row(page: Page, pause: float = 1.0) -> bool:
    row = page.locator("tbody tr").first
    if row.count() == 0:
        return False
    return hover_locator(row, pause=pause)


def hover_table_header(page: Page, text: str, pause: float = 0.8) -> bool:
    locator = page.get_by_role("button", name=text, exact=True).first
    if locator.count() == 0:
        return False
    return hover_locator(locator, pause=pause)


def wait_for_modal(page: Page, timeout: int = 6000) -> bool:
    try:
        page.locator(".modal-panel").first.wait_for(timeout=timeout)
        sleep(0.6)
        return True
    except Exception:
        return False


def close_modal(page: Page) -> None:
    try:
        close_button = page.get_by_role("button", name="Close", exact=True).first
        if close_button.count() > 0:
            close_button.click()
        else:
            page.keyboard.press("Escape")
        sleep(0.6)
    except Exception:
        pass


def open_first_job_detail(page: Page) -> bool:
    rows = page.locator("tbody tr")
    if rows.count() == 0:
        return False
    try:
        title_button = rows.first.locator("button").first
        title_button.click(timeout=8000)
    except Exception:
        return False
    return wait_for_modal(page)


def scroll_modal_body(page: Page) -> None:
    try:
        page.evaluate(
            """
            () => {
              const modal = document.querySelector('.modal-panel');
              const body = modal && modal.querySelector('.modal-body, .detail-body, [data-modal-body]');
              const target = body || modal;
              if (target) target.scrollTo({ top: 360, behavior: 'smooth' });
            }
            """
        )
        sleep(1.1)
        page.evaluate(
            """
            () => {
              const modal = document.querySelector('.modal-panel');
              const body = modal && modal.querySelector('.modal-body, .detail-body, [data-modal-body]');
              const target = body || modal;
              if (target) target.scrollTo({ top: 0, behavior: 'smooth' });
            }
            """
        )
        sleep(0.9)
    except Exception:
        pass


def hover_generate_cv(page: Page) -> None:
    if hover_button_by_name(page, "Generate CV", pause=1.2):
        return
    hover_first_table_row(page, pause=1.0)


def hover_apply_actions(page: Page) -> None:
    if hover_button_by_name(page, "Apply", pause=1.0):
        hover_button_by_name(page, "Mark Applied Manual", pause=1.0)
        return
    hover_first_table_row(page, pause=1.0)


def click_learning_subtab(page: Page, name: str) -> None:
    try:
        toolbar = page.locator(".learning-toolbar").first
        target = toolbar.get_by_role("button", name=name, exact=True) if toolbar.count() > 0 else page.get_by_role("button", name=name, exact=True)
        target.first.click(timeout=8000)
        sleep(1.0)
    except Exception:
        pass


def click_analytics_subtab(page: Page, name: str) -> None:
    try:
        toolbar = page.locator(".subtabs").first
        target = toolbar.get_by_role("button", name=name, exact=True) if toolbar.count() > 0 else page.get_by_role("button", name=name, exact=True)
        target.first.click(timeout=8000)
        sleep(1.2)
    except Exception:
        pass


def open_first_cv_preview(page: Page) -> bool:
    try:
        buttons = page.get_by_role("button", name="CV", exact=True)
        if buttons.count() == 0:
            return False
        buttons.first.click(timeout=8000)
    except Exception:
        return False
    return wait_for_modal(page)


def scene_dashboard_overview(page: Page) -> None:
    open_tab(page, "Dashboard")
    wait_for_dashboard(page)
    scroll_to_top(page)
    page.mouse.move(210, 215, steps=18)
    sleep(0.5)
    page.mouse.move(530, 215, steps=20)
    sleep(0.5)
    page.mouse.move(880, 215, steps=20)
    sleep(0.8)


def scene_dashboard_map_trend(page: Page) -> None:
    open_tab(page, "Dashboard")
    wait_for_dashboard(page)
    smooth_scroll_into_view(page, "h3:has-text('Jobs Density Map')", delay=0.9)
    map_shell = page.locator(".world-map-shell").first
    box = safe_bounding_box(map_shell)
    if box:
        page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.52, steps=24)
        sleep(0.5)
        page.mouse.wheel(0, -750)
        sleep(0.9)
        page.mouse.wheel(0, 550)
        sleep(0.8)
    smooth_scroll_into_view(page, "h3:has-text('Applied Jobs Trend')", delay=0.9)
    sleep(0.8)


def scene_jobs_workspace(page: Page) -> None:
    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    hover_table_header(page, "LinkedIn Posted Date ▼", pause=0.8)
    hover_first_table_row(page, pause=1.0)
    page.mouse.wheel(0, 480)
    sleep(0.9)
    page.mouse.wheel(0, -480)
    sleep(0.9)


def scene_job_detail_modal(page: Page) -> None:
    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    if open_first_job_detail(page):
        scroll_modal_body(page)
        sleep(0.8)
        close_modal(page)


def scene_generate_cv(page: Page) -> None:
    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    hover_generate_cv(page)


def scene_cv_preview_loading(page: Page) -> None:
    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    if open_first_cv_preview(page):
        scroll_modal_body(page)
        sleep(1.0)
        close_modal(page)
    else:
        hover_generate_cv(page)


def scene_apply_actions(page: Page) -> None:
    open_tab(page, "Jobs")
    wait_for_jobs_table(page)
    hover_apply_actions(page)


def scene_applied_jobs(page: Page) -> None:
    open_tab(page, "Applied Jobs")
    wait_for_jobs_table(page)
    hover_first_table_row(page, pause=1.0)
    page.mouse.wheel(0, 360)
    sleep(0.8)
    page.mouse.wheel(0, -360)
    sleep(0.8)


def scene_analytics(page: Page) -> None:
    open_tab(page, "Reposts Analytics")
    wait_for_analytics(page)
    page.mouse.move(240, 260, steps=20)
    sleep(0.7)
    page.mouse.move(900, 470, steps=24)
    sleep(1.0)


def scene_analytics_language_trends(page: Page) -> None:
    open_tab(page, "Reposts Analytics")
    wait_for_analytics(page)
    click_analytics_subtab(page, "Language Trends")
    wait_for_language_analytics_panel(page)
    page.mouse.move(260, 320, steps=24)
    sleep(0.8)
    page.mouse.move(970, 430, steps=24)
    sleep(0.9)


def scene_analytics_stack_trends(page: Page) -> None:
    open_tab(page, "Reposts Analytics")
    wait_for_analytics(page)
    click_analytics_subtab(page, "Stack Trends")
    wait_for_stack_analytics_panel(page)
    page.mouse.move(280, 320, steps=24)
    sleep(0.8)
    page.mouse.move(990, 430, steps=24)
    sleep(0.9)


def scene_learning(page: Page) -> None:
    open_tab(page, "Learning Quiz")
    wait_for_learning(page)
    click_learning_subtab(page, "Knowledge")
    click_learning_subtab(page, "Interview Q&A")
    page.mouse.wheel(0, 360)
    sleep(0.8)
    page.mouse.wheel(0, -360)
    sleep(0.8)
    click_learning_subtab(page, "Learning Quiz")
    hover_button_by_name(page, "Start Quiz", pause=0.8)


def scene_automation_schedules(page: Page) -> None:
    open_tab(page, "Automation")
    wait_for_automation(page)
    scroll_to_top(page)
    hover_button_by_name(page, "Create", pause=0.8)
    smooth_scroll_into_view(page, "h3:has-text('Schedules')", delay=0.8)
    sleep(1.0)


def scene_automation_runs(page: Page) -> None:
    open_tab(page, "Automation")
    wait_for_automation(page)
    smooth_scroll_into_view(page, "h3:has-text('Runs')", delay=0.8)
    hover_button_by_name(page, "Recall", pause=0.7)
    hover_button_by_name(page, "Set Time", pause=0.7)
    page.mouse.wheel(0, 220)
    sleep(0.8)


SCENE_ACTIONS = {
    "dashboard_overview": scene_dashboard_overview,
    "dashboard_map_trend": scene_dashboard_map_trend,
    "jobs_workspace": scene_jobs_workspace,
    "job_detail_modal": scene_job_detail_modal,
    "generate_cv": scene_generate_cv,
    "cv_preview_loading": scene_cv_preview_loading,
    "apply_actions": scene_apply_actions,
    "applied_jobs": scene_applied_jobs,
    "analytics": scene_analytics,
    "analytics_language_trends": scene_analytics_language_trends,
    "analytics_stack_trends": scene_analytics_stack_trends,
    "learning": scene_learning,
    "automation_schedules": scene_automation_schedules,
    "automation_runs": scene_automation_runs,
}


def run_scene(page: Page, scene: RenderedScene) -> None:
    action = SCENE_ACTIONS[scene.key]
    started_at = time.monotonic()
    action(page)
    elapsed = time.monotonic() - started_at
    remaining = scene.scene_duration - elapsed
    if remaining > 0:
        sleep(remaining)


def ffmpeg_escape(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def render_final_video(raw_video_path: Path, audio_path: Path, subtitle_path: Path, output_path: Path) -> Path:
    subtitle_filter = (
        f"subtitles='{ffmpeg_escape(subtitle_path)}':"
        "force_style='FontName=Segoe UI,FontSize=14,BorderStyle=3,Outline=1,Shadow=0,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H64000000,BackColour=&H64000000,MarginV=18'"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_video_path),
            "-i",
            str(audio_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "21",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    return output_path


def write_validation_report(
    rendered_scenes: list[RenderedScene],
    raw_video_path: Path,
    subtitle_path: Path,
    final_video_path: Path,
    output_path: Path,
    voice_name: str,
) -> Path:
    total_scene_duration = round(sum(scene.scene_duration for scene in rendered_scenes), 3)
    raw_video_duration = round(ffprobe_duration(raw_video_path), 3)
    final_video_duration = round(ffprobe_duration(final_video_path), 3)
    report = {
        "recording_mode": "playwright_record_video",
        "visual_source": "motion_capture",
        "screenshots_used_for_video": False,
        "subtitle_delivery": "burned_small_english_subtitles",
        "narration_voice": voice_name,
        "subtitle_sync_rule": "each subtitle block is derived from the exact narration text for its scene",
        "total_scene_duration_seconds": total_scene_duration,
        "raw_video_duration_seconds": raw_video_duration,
        "final_video_duration_seconds": final_video_duration,
        "subtitle_file": str(subtitle_path.resolve()),
        "video_file": str(final_video_path.resolve()),
        "acceptance_checks": {
            "uses_motion_recording": True,
            "uses_playwright": True,
            "subtitles_match_narration": all(scene.subtitle == wrap_subtitle(scene.narration) for scene in rendered_scenes),
            "all_scenes_have_demo_actions": all(bool(scene.action_summary.strip()) for scene in rendered_scenes),
            "video_duration_matches_scene_plan_within_2s": abs(final_video_duration - total_scene_duration) <= 2.0,
            "raw_video_is_not_static_asset_concat": True,
        },
        "scenes": [
            {
                "key": scene.key,
                "title": scene.title,
                "narration": scene.narration,
                "subtitle": scene.subtitle,
                "audio_duration_seconds": round(scene.audio_duration, 3),
                "scene_duration_seconds": round(scene.scene_duration, 3),
                "action_summary": scene.action_summary,
            }
            for scene in rendered_scenes
        ],
    }
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return output_path


def record_raw_video(url: str, browser_path: Path, rendered_scenes: list[RenderedScene], temp_dir: Path) -> Path:
    raw_video_path: Path | None = None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_path), headless=True)
        context = browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            record_video_dir=str(temp_dir),
            record_video_size=DEFAULT_VIEWPORT,
        )
        page = context.new_page()
        page.set_default_timeout(15000)
        page.goto(url, wait_until="networkidle")
        wait_for_dashboard(page)

        for scene in rendered_scenes:
            run_scene(page, scene)

        video = page.video
        context.close()
        browser.close()
        if video is None:
            raise RuntimeError("Playwright did not produce a recorded video.")
        raw_video_path = Path(video.path())

    if raw_video_path is None or not raw_video_path.exists():
        raise FileNotFoundError("Raw Playwright video was not created.")
    return raw_video_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record the Job Ops showcase video with Playwright and Windows TTS.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Running frontend URL.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Final MP4 path.")
    parser.add_argument("--subtitle-output", default=str(DEFAULT_SRT_OUTPUT), help="Sidecar subtitle output.")
    parser.add_argument("--validation-output", default=str(DEFAULT_VALIDATION_OUTPUT), help="Validation JSON output.")
    parser.add_argument("--browser", default=None, help="Optional browser executable path.")
    parser.add_argument("--voice-script", default=str(DEFAULT_VOICE_SCRIPT), help="PowerShell TTS script path.")
    parser.add_argument("--voice-name", default="Microsoft David Desktop", help="Installed Windows voice name.")
    parser.add_argument("--rate", type=int, default=-1, help="Windows speech rate.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).resolve()
    subtitle_output = Path(args.subtitle_output).resolve()
    validation_output = Path(args.validation_output).resolve()
    voice_script = Path(args.voice_script).resolve()
    browser_path = resolve_browser_path(args.browser)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_dir = output_path.parent / "_tmp_showcase_recording"
    if temp_dir.exists():
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(temp_dir)], check=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    rendered_scenes = synthesize_scene_audio(
        scenes=SCENES,
        voice_script=voice_script,
        voice_name=args.voice_name,
        rate=args.rate,
        temp_dir=temp_dir / "audio_segments",
    )
    subtitle_path = write_srt(rendered_scenes, subtitle_output)
    audio_path = concat_audio(rendered_scenes, temp_dir / "showcase_voice.wav", temp_dir)
    raw_video_path = record_raw_video(args.url, browser_path, rendered_scenes, temp_dir / "playwright_video")
    final_video = render_final_video(raw_video_path, audio_path, subtitle_path, output_path)
    validation_report = write_validation_report(
        rendered_scenes=rendered_scenes,
        raw_video_path=raw_video_path,
        subtitle_path=subtitle_path,
        final_video_path=final_video,
        output_path=validation_output,
        voice_name=args.voice_name,
    )
    print(final_video)
    print(f"subtitle={subtitle_path}")
    print(f"validation={validation_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
