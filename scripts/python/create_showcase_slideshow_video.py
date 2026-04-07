from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIO = ROOT / "artifacts" / "intro_video" / "job_ops_project_showcase_voice_2026-03-23-75s.wav"
DEFAULT_IMAGES_DIR = ROOT / "showcase_assets" / "images"
DEFAULT_OUTPUT = ROOT / "showcase_assets" / "video" / "job_ops_project_showcase.mp4"
FPS = 25
FRAME_SIZE = "1280x720"
DEFAULT_DURATION = 6.28


@dataclass(frozen=True)
class Slide:
    image: str
    title: str
    subtitle: str
    duration: float


SLIDES: list[Slide] = [
    Slide(
        "dashboard_overview.png",
        "Dashboard Overview",
        "Backend health, quick KPIs, and recent activity in one local-first operator console.",
        DEFAULT_DURATION,
    ),
    Slide(
        "jobs_density_map.png",
        "Coverage Map",
        "Country-level density highlights where the crawl and apply pipeline is finding demand.",
        DEFAULT_DURATION,
    ),
    Slide(
        "jobs_workspace.png",
        "Jobs Workspace",
        "Filtering, fit evaluation, batch actions, and CV generation start from this working queue.",
        DEFAULT_DURATION,
    ),
    Slide(
        "jobs_detail_modal.png",
        "Job Detail + Rewrite",
        "A single job view surfaces JD evidence, fit reasons, rule overrides, and rewrite-ready context.",
        DEFAULT_DURATION,
    ),
    Slide(
        "applied_jobs_workspace.png",
        "Applied Jobs",
        "Applied work stays separated so manual follow-up and automation outcomes remain easy to review.",
        DEFAULT_DURATION,
    ),
    Slide(
        "applied_jobs_trend.png",
        "Applied Trend",
        "The trend view shows throughput over time and helps confirm whether the pipeline is moving.",
        DEFAULT_DURATION,
    ),
    Slide(
        "analytics_reposts.png",
        "Repost Analytics",
        "Recurring openings and repeated companies are visible before spending time on another pass.",
        DEFAULT_DURATION,
    ),
    Slide(
        "automation_schedules.png",
        "Schedules",
        "Filtered jobs, applied jobs, and learning ETL can run on repeat with simple schedule controls.",
        DEFAULT_DURATION,
    ),
    Slide(
        "automation_runs.png",
        "Runs + Logs",
        "Run history exposes progress, latest step, and log locations when a crawl or rewrite batch needs inspection.",
        DEFAULT_DURATION,
    ),
    Slide(
        "learning_quiz.png",
        "Learning Quiz",
        "A built-in quiz loop keeps theory review close to daily operations instead of living in another tool.",
        DEFAULT_DURATION,
    ),
    Slide(
        "learning_knowledge.png",
        "Knowledge Review",
        "Reference answers and explanations help verify concepts before another automation or rewrite pass.",
        DEFAULT_DURATION,
    ),
    Slide(
        "automation_console.png",
        "Built For Low-Spec Local Machines",
        "Playwright, FastAPI, SQLite, and guarded rewrite flows keep the system practical on CPU-only hardware.",
        DEFAULT_DURATION,
    ),
]


def ffmpeg_escape_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")


def ensure_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)


def resolve_font() -> Path:
    candidates = [
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find a usable Windows font for ffmpeg drawtext.")


def build_segment(
    image_path: Path,
    title: str,
    subtitle: str,
    duration: float,
    segment_path: Path,
    temp_dir: Path,
    font_path: Path,
) -> None:
    title_file = temp_dir / f"{segment_path.stem}_title.txt"
    subtitle_file = temp_dir / f"{segment_path.stem}_subtitle.txt"
    title_file.write_text(title, encoding="utf-8")
    subtitle_file.write_text(subtitle, encoding="utf-8")

    safe_font = ffmpeg_escape_path(font_path)
    safe_title = ffmpeg_escape_path(title_file)
    safe_subtitle = ffmpeg_escape_path(subtitle_file)
    fade_out_start = max(0.2, duration - 0.35)

    vf = (
        f"scale=1280:720:force_original_aspect_ratio=decrease,"
        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x0b1020,"
        f"fade=t=in:st=0:d=0.30,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.30,"
        f"drawbox=x=28:y=608:w=1224:h=84:color=black@0.34:t=fill,"
        f"drawtext=fontfile='{safe_font}':textfile='{safe_title}':fontcolor=white:fontsize=24:"
        f"x=44:y=618,"
        f"drawtext=fontfile='{safe_font}':textfile='{safe_subtitle}':fontcolor=white@0.92:fontsize=15:"
        f"line_spacing=4:x=44:y=652"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{duration:.2f}",
        "-i",
        str(image_path),
        "-vf",
        vf,
        "-r",
        str(FPS),
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "22",
        str(segment_path),
    ]
    subprocess.run(cmd, check=True)


def render_video(audio_path: Path, images_dir: Path, output_path: Path) -> Path:
    ensure_exists(audio_path)
    ensure_exists(images_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_dir = output_path.parent / "_tmp_showcase_slideshow"
    if temp_dir.exists():
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(temp_dir)], check=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    font_path = resolve_font()
    segment_paths: list[Path] = []

    for idx, slide in enumerate(SLIDES, start=1):
        image_path = images_dir / slide.image
        ensure_exists(image_path)
        segment_path = temp_dir / f"segment_{idx:02d}.mp4"
        build_segment(
            image_path=image_path,
            title=slide.title,
            subtitle=slide.subtitle,
            duration=slide.duration,
            segment_path=segment_path,
            temp_dir=temp_dir,
            font_path=font_path,
        )
        segment_paths.append(segment_path)

    concat_file = temp_dir / "segments.txt"
    concat_file.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segment_paths),
        encoding="utf-8",
    )

    merged_video = temp_dir / "merged_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(merged_video),
        ],
        check=True,
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(merged_video),
            "-i",
            str(audio_path),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a slideshow-based showcase video from captured screenshots.")
    parser.add_argument("--audio", default=str(DEFAULT_AUDIO), help="Narration WAV path.")
    parser.add_argument("--images-dir", default=str(DEFAULT_IMAGES_DIR), help="Directory containing showcase screenshots.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output MP4 path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    final_video = render_video(
        audio_path=Path(args.audio).resolve(),
        images_dir=Path(args.images_dir).resolve(),
        output_path=Path(args.output).resolve(),
    )
    print(final_video)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
