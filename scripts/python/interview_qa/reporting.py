from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_job_result(output_dir: Path, result: dict[str, Any]) -> Path:
    """Persist one job result as JSON."""
    out_path = output_dir / f"job_{int(result['job_id'])}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    """Persist summary outputs in JSON and Markdown for quick review."""
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Interview Q&A Prediction Summary",
        "",
        f"- Mode: {summary.get('mode', '')}",
        f"- Backend: {summary.get('backend', '')}",
        f"- Model: {summary.get('model', '')}",
        f"- Jobs: {summary.get('job_count', 0)}",
        f"- Custom jobs: {summary.get('custom_job_count', 0)}",
        "",
        "## Files",
    ]
    for name in summary.get("generated_files", []) or []:
        lines.append(f"- {name}")
    (output_dir / "summary.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
