import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import (  # noqa: E402
    PROJECT_ROOT as APP_PROJECT_ROOT,
    TUNING_BENCH_REPEAT,
    TUNING_LOG_DIR,
    TUNING_LOG_DIR_WIN,
)
from app.services.cv_rewrite_service import CvRewriteService  # noqa: E402


def _resolve_log_root() -> Path:
    # English: Resolve log root for current OS.
    if os.name == "nt":
        return Path(TUNING_LOG_DIR_WIN or (Path.home() / "tuning_logs"))
    return Path(TUNING_LOG_DIR or "/home/user/tuning_logs")


def _create_run_dir(tag: str) -> Path:
    # English: Create a new run folder for this benchmark invocation.
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = _resolve_log_root() / "etl_cv_rewrite" / f"{stamp}_{tag}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _read_fixture(name: str) -> str:
    # English: Read a fixture file for deterministic benchmarks.
    fixture = PROJECT_ROOT / "scripts" / "fixtures" / name
    return fixture.read_text(encoding="utf-8")


def _percentile(values: list[float], pct: float) -> float:
    # English: Compute percentile with nearest-rank for small N.
    if not values:
        return 0.0
    xs = sorted(values)
    idx = int(round((pct / 100.0) * (len(xs) - 1)))
    return float(xs[min(max(idx, 0), len(xs) - 1)])


def _aggregate(events: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    # English: Aggregate metrics by scenario for CSV/MD summary.
    by_scenario: dict[str, list[dict[str, object]]] = {}
    for event in events:
        scenario = str(event.get("scenario") or "unknown")
        by_scenario.setdefault(scenario, []).append(event)

    summary: dict[str, dict[str, float]] = {}
    for scenario, items in by_scenario.items():
        totals = [float(item.get("total_ms") or 0.0) for item in items]
        prompt_tokens = [int(item.get("prompt_tokens") or 0) for item in items]
        selected_ctx = [int(item.get("selected_context_count") or 0) for item in items]
        fallback_rate = 0.0
        if items:
            fallback_rate = sum(1 for item in items if str(item.get("fallback_reason") or "").strip()) / len(items)
        summary[scenario] = {
            "sample_n": float(len(items)),
            "avg_ms": float(sum(totals) / max(1, len(totals))),
            "p50_ms": _percentile(totals, 50),
            "p95_ms": _percentile(totals, 95),
            "max_ms": float(max(totals) if totals else 0.0),
            "avg_prompt_tokens": float(sum(prompt_tokens) / max(1, len(prompt_tokens))),
            "avg_selected_ctx": float(sum(selected_ctx) / max(1, len(selected_ctx))),
            "fallback_rate": float(fallback_rate),
        }
    return summary


def _write_summary_csv(path: Path, tag: str, summary: dict[str, dict[str, float]]) -> None:
    # English: Write summary CSV for this run.
    lines = [
        "Scenario,PatchTag,sample_n,avg_ms,p50_ms,p95_ms,max_ms,avg_prompt_tokens,avg_selected_ctx,fallback_rate"
    ]
    for scenario, row in summary.items():
        lines.append(
            ",".join(
                [
                    scenario,
                    tag,
                    str(int(row["sample_n"])),
                    f"{row['avg_ms']:.3f}",
                    f"{row['p50_ms']:.3f}",
                    f"{row['p95_ms']:.3f}",
                    f"{row['max_ms']:.3f}",
                    f"{row['avg_prompt_tokens']:.2f}",
                    f"{row['avg_selected_ctx']:.2f}",
                    f"{row['fallback_rate']:.3f}",
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_summary_md(path: Path, tag: str, summary: dict[str, dict[str, float]], flags: dict[str, str]) -> None:
    # English: Write summary markdown for doc upsert.
    lines = [
        f"PatchTag: `{tag}`",
        "",
        "Flags effective:",
    ]
    for key, value in flags.items():
        lines.append(f"- `{key}`={value}")
    lines.extend(
        [
            "",
            "| Scenario | PatchTag | sample_n | avg_ms | p50_ms | p95_ms | max_ms | avg_prompt_tokens | avg_selected_ctx | fallback_rate |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario, row in summary.items():
        lines.append(
            f"| {scenario} | {tag} | {int(row['sample_n'])} | {row['avg_ms']:.3f} | {row['p50_ms']:.3f} | {row['p95_ms']:.3f} | {row['max_ms']:.3f} | {row['avg_prompt_tokens']:.2f} | {row['avg_selected_ctx']:.2f} | {row['fallback_rate']:.3f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(tag: str, repeat: int) -> tuple[Path, dict[str, dict[str, float]]]:
    # English: Run a repeated CV rewrite benchmark and emit JSONL events.
    run_dir = _create_run_dir(tag)
    events_path = run_dir / "events.jsonl"
    os.environ["TUNING_JSONL_PATH"] = str(events_path)

    jd_text = _read_fixture("sample_jd.txt")
    cv_text = _read_fixture("sample_cv.txt")
    guide_text = (PROJECT_ROOT / "CV_REWRITE_STRICT_GUIDE.md").read_text(encoding="utf-8")

    service = CvRewriteService(project_root=APP_PROJECT_ROOT)

    for idx in range(max(1, repeat)):
        service.run_with_text(
            cv_master=cv_text,
            jd_text=jd_text,
            guide_text=guide_text,
            jd_source_name="sample_jd.txt",
            user_prompt=f"Benchmark run {idx + 1}: tailor CV for JD",
            output_slug="bench",
            llm_model="qwen2.5:1.5b-instruct",
            temperature=0.2,
            render_docx=False,
            render_pdf=False,
            run_fit_report=False,
            job_context={
                "job_id": 0,
                "title": "Backend Engineer",
                "company": "SampleCo",
                "location": "Remote",
            },
        )

    events: list[dict[str, object]] = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except Exception:
                continue

    summary = _aggregate(events)
    _write_summary_csv(run_dir / "summary_by_scenario.csv", tag, summary)
    flags = {
        "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": os.getenv("TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE", "0"),
        "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": os.getenv("TUNING_ENABLE_RERANK_FOR_CV_REWRITE", "0"),
        "TUNING_ENABLE_CONTEXT_PACK": os.getenv("TUNING_ENABLE_CONTEXT_PACK", "0"),
        "TUNING_ENABLE_PERSISTED_CACHE": os.getenv("TUNING_ENABLE_PERSISTED_CACHE", "0"),
        "TUNING_TOKENIZER_BACKEND": os.getenv("TUNING_TOKENIZER_BACKEND", "auto"),
        "TUNING_PROMPT_MAX_TOKENS": os.getenv("TUNING_PROMPT_MAX_TOKENS", ""),
    }
    _write_summary_md(run_dir / "summary.md", tag, summary, flags)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "tag": tag,
                "repeat": repeat,
                "flags": flags,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--repeat", type=int, default=TUNING_BENCH_REPEAT)
    args = parser.parse_args()

    run_benchmark(tag=args.tag, repeat=args.repeat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
