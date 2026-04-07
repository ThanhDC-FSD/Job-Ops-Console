import argparse
from pathlib import Path


MARKER_START = "<!-- BEGIN PC_TUNING_RUN_RESULT -->"
MARKER_END = "<!-- END PC_TUNING_RUN_RESULT -->"


def _upsert_block(content: str, block: str) -> str:
    # English: Replace the block between markers or append if missing.
    if MARKER_START in content and MARKER_END in content:
        before, rest = content.split(MARKER_START, 1)
        _, after = rest.split(MARKER_END, 1)
        return before + MARKER_START + "\n" + block + "\n" + MARKER_END + after
    suffix = "" if content.endswith("\n") else "\n"
    return content + suffix + MARKER_START + "\n" + block + "\n" + MARKER_END + "\n"


def _render_block_for_file(path: Path, block: str) -> str:
    # English: Keep Mermaid files parseable by commenting every inserted marker line.
    if path.suffix.lower() != ".mmd":
        return block
    rendered_lines: list[str] = []
    for line in str(block or "").splitlines():
        rendered_lines.append(f"%% {line}".rstrip())
    return "\n".join(rendered_lines)


def _update_file(path: Path, block: str) -> None:
    # English: Update a single file using the marker block.
    raw = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    rendered_block = _render_block_for_file(path, block)
    updated = _upsert_block(raw, rendered_block)
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", required=True, help="Path to summary.md block")
    parser.add_argument("--files", nargs="+", required=True)
    args = parser.parse_args()

    block_path = Path(args.block)
    block = block_path.read_text(encoding="utf-8")
    for file_path in args.files:
        _update_file(Path(file_path), block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
