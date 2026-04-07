import argparse
import json
import os
import sys
import time
from pathlib import Path

from benchmark_etl_cv_rewrite_flow import run_benchmark, _resolve_log_root, PROJECT_ROOT, BACKEND_ROOT

sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "python"))

from app.config import PROJECT_ROOT as APP_PROJECT_ROOT  # noqa: E402
from app.services.cv_rewrite_service import CvRewriteService  # noqa: E402
from update_docs_by_marker import _update_file  # noqa: E402


def _set_env(flags: dict[str, str]) -> None:
    # English: Apply environment flags for the next patch run.
    for key, value in flags.items():
        os.environ[key] = str(value)


def _scenario_p95(summary: dict[str, dict[str, float]], scenario: str) -> float:
    # English: Read p95 for a specific scenario from summary.
    row = summary.get(scenario) or {}
    return float(row.get("p95_ms") or 0.0)


def _render_combined_summary(results: list[dict[str, object]]) -> str:
    # English: Render a combined summary table for doc upsert.
    lines = [
        f"Run timestamp: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        "",
        "| Scenario | PatchTag | sample_n | avg_ms | p50_ms | p95_ms | max_ms | avg_prompt_tokens | avg_selected_ctx | fallback_rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        tag = str(item["tag"])
        summary = item["summary"]
        for scenario, row in summary.items():
            lines.append(
                f"| {scenario} | {tag} | {int(row['sample_n'])} | {row['avg_ms']:.3f} | {row['p50_ms']:.3f} | {row['p95_ms']:.3f} | {row['max_ms']:.3f} | {row['avg_prompt_tokens']:.2f} | {row['avg_selected_ctx']:.2f} | {row['fallback_rate']:.3f} |"
            )
    return "\n".join(lines) + "\n"


def _maybe_build_context_pack() -> None:
    # English: Precompute a context pack before running context-pack patches.
    if os.getenv("TUNING_ENABLE_CONTEXT_PACK", "0").strip().lower() not in {"1", "true", "yes"}:
        return
    jd_text = (PROJECT_ROOT / "scripts" / "fixtures" / "sample_jd.txt").read_text(encoding="utf-8")
    service = CvRewriteService(project_root=APP_PROJECT_ROOT)
    service.build_context_pack_for_job(job_id=0, jd_text=jd_text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    run_root = _resolve_log_root() / "etl_cv_rewrite" / f"{time.strftime('%Y%m%d_%H%M%S')}_run_now"
    run_root.mkdir(parents=True, exist_ok=True)

    baseline_flags = {
        "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": "0",
        "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": "0",
        "TUNING_ENABLE_CONTEXT_PACK": "0",
        "TUNING_ENABLE_PERSISTED_CACHE": "0",
        "TUNING_TOKENIZER_BACKEND": "auto",
    }
    _set_env(baseline_flags)
    baseline_dir, baseline_summary = run_benchmark(tag="baseline", repeat=int(os.getenv("TUNING_BENCH_REPEAT", "30")))

    results: list[dict[str, object]] = [
        {"tag": "baseline", "summary": baseline_summary, "dir": str(baseline_dir), "flags": baseline_flags},
    ]
    baseline_p95 = _scenario_p95(baseline_summary, "cv_rewrite_preview")
    regression_pct = float(os.getenv("TUNING_REGRESSION_P95_PCT", "10"))
    fail_on_regression = args.fail_on_regression or (
        str(os.getenv("TUNING_BENCH_FAIL_ON_REGRESSION", "1")).strip().lower() in {"1", "true", "yes"}
    )

    patch_plan = [
        (
            "patch_1_retrieval",
            {
                "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": "0",
                "TUNING_ENABLE_CONTEXT_PACK": "0",
                "TUNING_ENABLE_PERSISTED_CACHE": "0",
                "TUNING_TOKENIZER_BACKEND": "auto",
            },
        ),
        (
            "patch_2_rerank_caps",
            {
                "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_CONTEXT_PACK": "0",
                "TUNING_ENABLE_PERSISTED_CACHE": "0",
                "TUNING_TOKENIZER_BACKEND": "auto",
            },
        ),
        (
            "patch_3_context_pack",
            {
                "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_CONTEXT_PACK": "1",
                "TUNING_ENABLE_PERSISTED_CACHE": "0",
                "TUNING_TOKENIZER_BACKEND": "auto",
            },
        ),
        (
            "patch_4_cache_wal",
            {
                "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_CONTEXT_PACK": "1",
                "TUNING_ENABLE_PERSISTED_CACHE": "1",
                "TUNING_TOKENIZER_BACKEND": "auto",
            },
        ),
        (
            "patch_5_token_budget",
            {
                "TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_RERANK_FOR_CV_REWRITE": "1",
                "TUNING_ENABLE_CONTEXT_PACK": "1",
                "TUNING_ENABLE_PERSISTED_CACHE": "1",
                "TUNING_TOKENIZER_BACKEND": "tiktoken",
            },
        ),
    ]

    for tag, flags in patch_plan:
        _set_env(flags)
        _maybe_build_context_pack()
        patch_dir, patch_summary = run_benchmark(tag=tag, repeat=int(os.getenv("TUNING_BENCH_REPEAT", "30")))
        results.append({"tag": tag, "summary": patch_summary, "dir": str(patch_dir), "flags": flags})
        patch_p95 = _scenario_p95(patch_summary, "cv_rewrite_preview")
        if baseline_p95 > 0:
            regression = ((patch_p95 - baseline_p95) / baseline_p95) * 100.0
        else:
            regression = 0.0
        if regression > regression_pct and fail_on_regression:
            results.append(
                {
                    "tag": f"{tag}_rollback",
                    "summary": patch_summary,
                    "dir": str(patch_dir),
                    "flags": {"rollback": "true", "reason": f"p95_regression_{regression:.1f}%"},
                }
            )
            break

    combined_summary = _render_combined_summary(results)
    combined_md = run_root / "summary.md"
    combined_md.write_text(combined_summary, encoding="utf-8")

    docs_dir = PROJECT_ROOT / "docs"
    for doc_name in [
        "10.1_current_system_explanation.md",
        "10.1_current_system_explanation.mmd",
        "10.1_current_system_workflow.mmd",
    ]:
        _update_file(docs_dir / doc_name, combined_summary)

    combined_csv = run_root / "summary_by_scenario.csv"
    csv_lines = [
        "Scenario,PatchTag,sample_n,avg_ms,p50_ms,p95_ms,max_ms,avg_prompt_tokens,avg_selected_ctx,fallback_rate"
    ]
    for item in results:
        tag = str(item["tag"])
        summary = item["summary"]
        for scenario, row in summary.items():
            csv_lines.append(
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
    combined_csv.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    best = None
    best_p95 = None
    for item in results:
        if str(item.get("tag")).endswith("_rollback"):
            continue
        scenario_summary = item["summary"].get("cv_rewrite_preview") or {}
        p95 = float(scenario_summary.get("p95_ms") or 0.0)
        if best_p95 is None or (p95 > 0 and p95 < best_p95):
            best_p95 = p95
            best = item

    (run_root / "state.json").write_text(
        json.dumps(
            {
                "baseline_dir": str(baseline_dir),
                "results": results,
                "best_tag": (best or {}).get("tag"),
                "best_flags": (best or {}).get("flags"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Run completed. Summary at {combined_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
