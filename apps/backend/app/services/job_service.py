from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from app.config import PROJECT_ROOT
from app.repositories.job_repository import JobRepository

SHOWCASE_VIDEO_URL = "https://github.com/ThanhDC-FSD/Job-Ops-Console/tree/showcase"


class JobService:
    def __init__(self, repo: JobRepository) -> None:
        self.repo = repo
        self.logger = logging.getLogger("job_ops.service.job")

    def dashboard(self) -> dict[str, Any]:
        self.logger.info("Dashboard requested")
        return self.repo.fetch_dashboard()

    @staticmethod
    def _resolve_existing_path(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        path = Path(raw)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        if path.exists() and path.is_file():
            return str(path)
        return ""

    @staticmethod
    def _derive_cv_artifact_from_cover_letter(value: str, *, suffix: str) -> str:
        source = Path(str(value or "").strip())
        if not source.name:
            return ""
        name = source.name
        if name.startswith("COVER_LETTER_"):
            candidate = source.with_name("CV_" + name[len("COVER_LETTER_"):]).with_suffix(suffix)
        else:
            candidate = source.with_suffix(suffix)
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
        return ""

    @staticmethod
    def _derive_sibling_cv_artifact(value: str, *, suffix: str) -> str:
        source = Path(str(value or "").strip())
        if not source.name:
            return ""
        stem = source.stem
        if stem.startswith("CV_"):
            candidate = source.with_suffix(suffix)
        elif stem.startswith("COVER_LETTER_"):
            candidate = source.with_name("CV_" + stem[len("COVER_LETTER_"):]).with_suffix(suffix)
        else:
            candidate = source.with_suffix(suffix)
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
        return ""

    @staticmethod
    def _normalize_for_compare(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            path = Path(raw)
            if path.is_absolute():
                return str(path.resolve())
        except Exception:
            pass
        return raw

    @staticmethod
    def _slug_tokenize(value: str) -> list[str]:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
        return [token for token in normalized.split("_") if token]

    def _find_generated_document_artifacts(self, row: dict[str, Any]) -> dict[str, str]:
        created_date = str(row.get("cv_created_date") or "").strip()
        company_tokens = self._slug_tokenize(str(row.get("company") or ""))
        title_tokens = [token for token in self._slug_tokenize(str(row.get("title") or "")) if len(token) >= 4]
        if not created_date or not company_tokens:
            return {}

        company_dir = PROJECT_ROOT / "documents" / created_date / company_tokens[0]
        if not company_dir.exists() or not company_dir.is_dir():
            return {}

        best: dict[str, Any] | None = None
        for version_dir in sorted(company_dir.glob("CV*")):
            if not version_dir.is_dir():
                continue
            for pdf_file in version_dir.glob("CV_*.pdf"):
                stem_tokens = set(self._slug_tokenize(pdf_file.stem))
                score = sum(1 for token in title_tokens if token in stem_tokens)
                score += sum(2 for token in company_tokens if token in stem_tokens)
                try:
                    version_score = int(re.sub(r"[^0-9]", "", version_dir.name) or "0")
                except Exception:
                    version_score = 0
                candidate = {
                    "score": score,
                    "version": version_score,
                    "pdf_path": str(pdf_file.resolve()),
                    "docx_path": self._resolve_existing_path(str(pdf_file.with_suffix(".docx"))),
                }
                cover_letter_pdf = pdf_file.with_name(pdf_file.name.replace("CV_", "COVER_LETTER_", 1))
                candidate["cover_letter_pdf_path"] = self._resolve_existing_path(str(cover_letter_pdf))
                candidate["cover_letter_docx_path"] = self._resolve_existing_path(str(cover_letter_pdf.with_suffix(".docx")))
                current_key = (candidate["score"], candidate["version"])
                best_key = ((best or {}).get("score", -1), (best or {}).get("version", -1))
                if best is None or current_key > best_key:
                    best = candidate

        if not best:
            return {}
        return {
            "pdf_path": str(best.get("pdf_path") or ""),
            "docx_path": str(best.get("docx_path") or ""),
            "cover_letter_pdf_path": str(best.get("cover_letter_pdf_path") or ""),
            "cover_letter_docx_path": str(best.get("cover_letter_docx_path") or ""),
        }

    @staticmethod
    def _resolve_portfolio_video_path() -> str:
        return SHOWCASE_VIDEO_URL

    @staticmethod
    def _build_portfolio_output_basename(output_basename: str) -> str:
        suffix = str(output_basename or "").strip()
        if suffix.startswith("CV_"):
            suffix = suffix[len("CV_"):]
        return f"PORTFOLIO_{suffix}" if suffix else "PORTFOLIO"

    @staticmethod
    def _build_cover_letter_output_basename(cv_output_basename: str) -> str:
        base = str(cv_output_basename or "").strip()
        if base.lower().startswith("cv_"):
            return f"COVER_LETTER_{base[3:]}"
        return f"COVER_LETTER_{base}"

    @staticmethod
    def _write_if_changed(path: Path, content: str) -> None:
        # Guard against Windows MAX_PATH issues by applying a long-path prefix when needed.
        path_str = str(path)
        if os.name == "nt" and not path_str.startswith("\\\\?\\") and len(path_str) >= 248:
            path = Path("\\\\?\\" + path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = str(content or "")
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8", errors="ignore")
                if existing == normalized:
                    return
            except OSError:
                pass
        path.write_text(normalized, encoding="utf-8")

    def _venv_python(self) -> Path:
        py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        return py if py.exists() else Path("python")

    def _run_subprocess(self, cmd: list[str]) -> None:
        env = os.environ.copy()
        env["PYTHONHOME"] = ""
        env["PYTHONPATH"] = ""
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if completed.returncode != 0:
            raise ValueError(
                "Command failed: "
                + " ".join(cmd)
                + f"\nstdout:\n{completed.stdout[-1000:]}\nstderr:\n{completed.stderr[-1200:]}"
            )

    def _render_docx_and_pdf(self, *, txt_path: Path, docx_path: Path, pdf_path: Path) -> None:
        cmd = [
            str(self._venv_python()),
            str(PROJECT_ROOT / "scripts" / "python" / "render_cv_docx.py"),
            "-i",
            str(txt_path),
            "-o",
            str(docx_path),
            "--pdf-output",
            str(pdf_path),
        ]
        try:
            self._run_subprocess(cmd)
            return
        except ValueError as exc:
            self.logger.warning(
                "Docx/PDF render failed, retrying without PDF | input=%s output=%s pdf=%s error=%s",
                txt_path,
                docx_path,
                pdf_path,
                exc,
            )
        try:
            self._run_subprocess(
                [
                    str(self._venv_python()),
                    str(PROJECT_ROOT / "scripts" / "python" / "render_cv_docx.py"),
                    "-i",
                    str(txt_path),
                    "-o",
                    str(docx_path),
                    "--skip-pdf",
                ]
            )
            return
        except ValueError as exc:
            self.logger.warning(
                "Docx-only render failed, falling back to basic writer | input=%s output=%s error=%s",
                txt_path,
                docx_path,
                exc,
            )
        try:
            text = txt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            text = ""
        self._write_basic_docx(docx_path=docx_path, text=text)
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except Exception:
                pass

    def _write_basic_docx(self, *, docx_path: Path, text: str) -> None:
        content = str(text or "")
        paragraphs: list[str] = []
        if not content:
            paragraphs.append("<w:p><w:r><w:t></w:t></w:r></w:p>")
        else:
            for line in content.splitlines():
                if not line.strip():
                    paragraphs.append("<w:p><w:r><w:br/></w:r></w:p>")
                else:
                    paragraphs.append(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>")
        seo_body = "".join(paragraphs)
        document_xml = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
            "<w:body>"
            f"{seo_body}"
            "<w:sectPr>"
            "<w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
            "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/>"
            "</w:sectPr>"
            "</w:body>"
            "</w:document>"
        )
        docx_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(docx_path), "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
                "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
                "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
                "</Types>",
            )
            archive.writestr(
                "_rels/.rels",
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
                "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
                "</Relationships>",
            )
            archive.writestr(
                "word/_rels/document.xml.rels",
                "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"></Relationships>",
            )
            archive.writestr("word/document.xml", document_xml)

    def _materialize_generated_artifact_set(self, row: dict[str, Any], artifact: dict[str, Any]) -> dict[str, str]:
        expected = self._artifact_expected_paths(artifact)
        run_folder = Path(expected["run_folder"])
        version_dir = Path(expected["version_dir"])
        version_dir.mkdir(parents=True, exist_ok=True)
        cv_txt = Path(expected["cv_txt"])
        portfolio_txt = Path(expected["portfolio_txt"])
        cover_txt = Path(expected["cover_txt"])
        fit_md = Path(expected["fit_md"])
        cv_docx = Path(expected["cv_docx"])
        cv_pdf = Path(expected["cv_pdf"])
        portfolio_docx = Path(expected["portfolio_docx"])
        portfolio_pdf = Path(expected["portfolio_pdf"])
        cover_docx = Path(expected["cover_docx"])
        cover_pdf = Path(expected["cover_pdf"])

        self._write_if_changed(cv_txt, str(artifact.get("cv_text") or "").rstrip() + "\n")
        if str(artifact.get("portfolio_text") or "").strip():
            self._write_if_changed(portfolio_txt, str(artifact.get("portfolio_text") or "").rstrip() + "\n")
        if str(artifact.get("cover_letter_text") or "").strip():
            self._write_if_changed(cover_txt, str(artifact.get("cover_letter_text") or "").rstrip() + "\n")
        if str(artifact.get("fit_report_text") or "").strip():
            self._write_if_changed(fit_md, str(artifact.get("fit_report_text") or "").rstrip() + "\n")

        if cv_txt.exists() and (not cv_docx.exists() or not cv_pdf.exists()):
            self._render_docx_and_pdf(txt_path=cv_txt, docx_path=cv_docx, pdf_path=cv_pdf)
        if portfolio_txt.exists() and (not portfolio_docx.exists() or not portfolio_pdf.exists()):
            self._render_docx_and_pdf(txt_path=portfolio_txt, docx_path=portfolio_docx, pdf_path=portfolio_pdf)
        if cover_txt.exists() and (not cover_docx.exists() or not cover_pdf.exists()):
            self._render_docx_and_pdf(txt_path=cover_txt, docx_path=cover_docx, pdf_path=cover_pdf)

        artifact_id = int(artifact.get("id") or 0)
        if artifact_id > 0:
            self.repo.mark_generated_artifact_materialized(artifact_id)

        self.repo.update_generated_cv_path(
            int(row.get("id") or row.get("job_post_id") or 0),
            str(cv_pdf if cv_pdf.exists() else cv_docx if cv_docx.exists() else cv_txt),
            portfolio_path=str(portfolio_pdf if portfolio_pdf.exists() else portfolio_docx if portfolio_docx.exists() else portfolio_txt),
            cover_letter_path=str(cover_txt if cover_txt.exists() else ""),
            cover_letter_docx_path=str(cover_docx if cover_docx.exists() else ""),
            cover_letter_pdf_path=str(cover_pdf if cover_pdf.exists() else ""),
            generated_headline=str(artifact.get("headline") or ""),
            generated_summary=str(artifact.get("summary") or ""),
            generated_experience_summary=str(artifact.get("experience_summary") or ""),
            generated_llm_model=str(artifact.get("llm_model") or ""),
            generated_llm_backend=str(artifact.get("llm_backend") or ""),
            generated_llm_usage_json=str(artifact.get("llm_usage_json") or ""),
        )
        return {
            "cv_path": str(cv_txt if cv_txt.exists() else ""),
            "docx_path": str(cv_docx if cv_docx.exists() else ""),
            "pdf_path": str(cv_pdf if cv_pdf.exists() else ""),
            "portfolio_path": str(portfolio_pdf if portfolio_pdf.exists() else portfolio_docx if portfolio_docx.exists() else portfolio_txt if portfolio_txt.exists() else ""),
            "cover_letter_path": str(cover_txt if cover_txt.exists() else ""),
            "cover_letter_docx_path": str(cover_docx if cover_docx.exists() else ""),
            "cover_letter_pdf_path": str(cover_pdf if cover_pdf.exists() else ""),
            "fit_report_path": str(fit_md if fit_md.exists() else ""),
        }

    def _artifact_expected_paths(self, artifact: dict[str, Any]) -> dict[str, str]:
        run_folder = (PROJECT_ROOT / "input" / "Raw_CV" / str(artifact.get("run_folder_name") or "").strip()).resolve()
        version_dir = (
            PROJECT_ROOT
            / "documents"
            / str(artifact.get("documents_date_folder") or "").strip()
            / str(artifact.get("company_folder_name") or "").strip()
            / f"CV{int(artifact.get('version_number') or 1)}"
        ).resolve()
        output_slug = str(artifact.get("output_slug") or "").strip()
        output_basename = str(artifact.get("output_basename") or "").strip()
        cv_docx = version_dir / f"{output_basename}.docx"
        portfolio_docx = version_dir / f"{self._build_portfolio_output_basename(output_basename)}.docx"
        cover_docx = version_dir / f"{self._build_cover_letter_output_basename(output_basename)}.docx"
        return {
            "run_folder": str(run_folder),
            "version_dir": str(version_dir),
            "cv_txt": str((run_folder / f"CV_{output_slug}.txt").resolve()),
            "portfolio_txt": str((run_folder / f"PORTFOLIO_{output_slug}.txt").resolve()),
            "cover_txt": str((run_folder / f"cover_letter_{output_slug}.txt").resolve()),
            "fit_md": str((run_folder / f"{output_slug}_fit_report.md").resolve()),
            "cv_docx": str(cv_docx.resolve()),
            "cv_pdf": str(cv_docx.with_suffix(".pdf").resolve()),
            "portfolio_docx": str(portfolio_docx.resolve()),
            "portfolio_pdf": str(portfolio_docx.with_suffix(".pdf").resolve()),
            "cover_docx": str(cover_docx.resolve()),
            "cover_pdf": str(cover_docx.with_suffix(".pdf").resolve()),
        }

    @staticmethod
    def _has_text_content(value: Any) -> bool:
        return bool(str(value or "").strip())

    @staticmethod
    def _nonempty_values(*values: Any) -> list[str]:
        return [str(value).strip() for value in values if str(value or "").strip()]

    @staticmethod
    def _apply_preview_path_aliases(row: dict[str, Any]) -> dict[str, Any]:
        pdf_path = str(row.get("generated_pdf_path") or row.get("pdf_path") or "").strip()
        docx_path = str(row.get("generated_docx_path") or row.get("docx_path") or "").strip()
        cv_path = str(row.get("generated_cv_text_path") or row.get("cv_path") or "").strip()
        if pdf_path:
            row["pdf_path"] = pdf_path
        if docx_path:
            row["docx_path"] = docx_path
        if cv_path:
            row["cv_path"] = cv_path
        return row

    def _build_generated_artifact_diagnostics(
        self,
        row: dict[str, Any],
        artifact: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cv_paths = self._nonempty_values(
            row.get("generated_pdf_path"),
            row.get("generated_docx_path"),
            row.get("generated_cv_text_path"),
            row.get("cv_source_path"),
        )
        portfolio_paths = self._nonempty_values(row.get("portfolio_path"))
        cover_letter_paths = self._nonempty_values(
            row.get("cover_letter_path"),
            row.get("generated_cover_letter_docx_path"),
            row.get("generated_cover_letter_pdf_path"),
        )
        fit_report_paths = self._nonempty_values(row.get("generated_fit_report_path"))

        artifact_present = artifact is not None
        cv_text_present = self._has_text_content((artifact or {}).get("cv_text"))
        portfolio_text_present = self._has_text_content((artifact or {}).get("portfolio_text"))
        cover_letter_text_present = self._has_text_content((artifact or {}).get("cover_letter_text"))
        fit_report_text_present = self._has_text_content((artifact or {}).get("fit_report_text"))

        missing_fields: list[str] = []
        notes: list[str] = []

        if not cv_paths:
            missing_fields.append("cv_artifacts")
            notes.append("CV artifacts are missing from both DB paths and materialized files.")
        elif cv_text_present and not str(row.get("generated_cv_text_path") or "").strip():
            missing_fields.append("cv_txt_path")
            notes.append("CV text exists in the artifact set but the TXT path could not be materialized.")

        if portfolio_text_present and not portfolio_paths:
            missing_fields.append("portfolio_pdf")
            notes.append("Portfolio text exists in the artifact set but no portfolio file was materialized yet.")
        elif artifact_present and not portfolio_text_present and not portfolio_paths:
            missing_fields.append("portfolio_pdf")
            notes.append("This artifact set does not contain portfolio content, so preview cannot show a portfolio file.")

        if cover_letter_text_present and not cover_letter_paths:
            missing_fields.append("cover_letter")
            notes.append("Cover letter text exists in the artifact set but no cover-letter file was materialized yet.")
        elif artifact_present and not cover_letter_text_present and not cover_letter_paths:
            missing_fields.append("cover_letter")
            notes.append("This artifact set does not contain cover-letter content, so preview cannot show one.")

        if fit_report_text_present and not fit_report_paths:
            missing_fields.append("fit_report")
            notes.append("Fit report text exists in the artifact set but no Markdown file was materialized yet.")

        return {
            "artifact_id": int((artifact or {}).get("id") or 0),
            "source_kind": str((artifact or {}).get("source_kind") or ""),
            "materialized_at": str((artifact or {}).get("materialized_at") or ""),
            "has_cv_artifacts": bool(cv_paths),
            "has_portfolio_artifact": bool(portfolio_paths),
            "has_cover_letter_artifact": bool(cover_letter_paths),
            "has_fit_report_artifact": bool(fit_report_paths),
            "missing_fields": missing_fields,
            "notes": notes,
            "repairable_fields": [
                name
                for name, can_repair in (
                    ("cv_txt_path", cv_text_present),
                    ("portfolio_pdf", portfolio_text_present),
                    ("cover_letter", cover_letter_text_present),
                    ("fit_report", fit_report_text_present),
                )
                if can_repair
            ],
        }

    @staticmethod
    def _derive_portfolio_path_from_cv_artifact(value: str) -> str:
        source = Path(str(value or "").strip())
        if not source.name:
            return ""
        stem = source.stem
        if stem.startswith("CV_"):
            target_stem = "PORTFOLIO_" + stem[len("CV_"):]
        elif stem.startswith("COVER_LETTER_"):
            target_stem = "PORTFOLIO_" + stem[len("COVER_LETTER_"):]
        else:
            target_stem = f"PORTFOLIO_{stem}"
        return str(source.with_name(target_stem).with_suffix(".pdf"))

    def _ensure_portfolio_artifact(
        self,
        row: dict[str, Any],
        *,
        docx_path: str,
        pdf_path: str,
    ) -> str:
        existing = self._resolve_existing_path(str(row.get("portfolio_path") or ""))
        if existing and Path(existing).suffix.lower() == ".pdf":
            return existing
        base_artifact = docx_path or pdf_path
        if not base_artifact:
            return ""
        candidate_raw = self._derive_portfolio_path_from_cv_artifact(base_artifact)
        candidate = self._resolve_existing_path(candidate_raw)
        return candidate or ""

    def _enrich_generated_cv_artifacts(self, row: dict[str, Any]) -> dict[str, Any]:
        original_source_path = str(row.get("cv_source_path") or "").strip()
        original_portfolio_path = str(row.get("portfolio_path") or "").strip()
        original_cover_letter_path = str(row.get("cover_letter_path") or "").strip()
        original_cover_letter_docx_path = str(row.get("cover_letter_docx_path") or "").strip()
        original_cover_letter_pdf_path = str(row.get("cover_letter_pdf_path") or "").strip()

        source_path = self._resolve_existing_path(original_source_path)
        cover_letter_path = self._resolve_existing_path(original_cover_letter_path)
        pdf_path = self._resolve_existing_path(str(row.get("generated_pdf_path") or ""))
        docx_path = self._resolve_existing_path(str(row.get("generated_docx_path") or ""))
        cv_text_path = self._resolve_existing_path(str(row.get("generated_cv_text_path") or ""))
        cover_letter_docx_path = self._resolve_existing_path(
            str(row.get("generated_cover_letter_docx_path") or original_cover_letter_docx_path or "")
        )
        cover_letter_pdf_path = self._resolve_existing_path(
            str(row.get("generated_cover_letter_pdf_path") or original_cover_letter_pdf_path or "")
        )
        fit_report_path = self._resolve_existing_path(str(row.get("generated_fit_report_path") or ""))

        if source_path:
            suffix = Path(source_path).suffix.lower()
            if suffix == ".pdf":
                pdf_path = pdf_path or source_path
                docx_candidate = Path(source_path).with_suffix(".docx")
                docx_path = docx_path or self._resolve_existing_path(str(docx_candidate))
            elif suffix == ".docx":
                docx_path = docx_path or source_path
                pdf_candidate = Path(source_path).with_suffix(".pdf")
                pdf_path = pdf_path or self._resolve_existing_path(str(pdf_candidate))
            elif suffix == ".txt":
                cv_text_path = cv_text_path or source_path
            if not pdf_path:
                pdf_path = self._derive_sibling_cv_artifact(source_path, suffix=".pdf")
            if not docx_path:
                docx_path = self._derive_sibling_cv_artifact(source_path, suffix=".docx")
            if not cv_text_path:
                cv_text_path = self._derive_sibling_cv_artifact(source_path, suffix=".txt")

        if cover_letter_path:
            folder = Path(cover_letter_path).parent
            if not cv_text_path:
                cv_candidates = sorted(folder.glob("CV_*.txt"))
                if cv_candidates:
                    cv_text_path = self._resolve_existing_path(str(cv_candidates[0]))
            cover_letter_txt = Path(cover_letter_path)
            cover_letter_docx_candidate = cover_letter_txt.with_suffix(".docx")
            cover_letter_pdf_candidate = cover_letter_txt.with_suffix(".pdf")
            cover_letter_docx_path = self._resolve_existing_path(str(cover_letter_docx_candidate))
            cover_letter_pdf_path = self._resolve_existing_path(str(cover_letter_pdf_candidate))

        if not docx_path and cover_letter_docx_path:
            docx_path = self._derive_cv_artifact_from_cover_letter(cover_letter_docx_path, suffix=".docx")
        if not pdf_path and cover_letter_pdf_path:
            pdf_path = self._derive_cv_artifact_from_cover_letter(cover_letter_pdf_path, suffix=".pdf")
        if not docx_path and cover_letter_path:
            docx_path = self._derive_cv_artifact_from_cover_letter(cover_letter_path, suffix=".docx")
        if not pdf_path and cover_letter_path:
            pdf_path = self._derive_cv_artifact_from_cover_letter(cover_letter_path, suffix=".pdf")
        if not cv_text_path and (pdf_path or docx_path):
            cv_text_path = self._derive_sibling_cv_artifact(docx_path or pdf_path, suffix=".txt")
        if not fit_report_path and cv_text_path:
            cv_text_file = Path(cv_text_path)
            base_name = cv_text_file.stem
            if base_name.startswith("CV_"):
                fit_report_candidate = cv_text_file.with_name(f"{base_name[3:]}_fit_report.md")
                fit_report_path = self._resolve_existing_path(str(fit_report_candidate))

        if not pdf_path and not docx_path:
            generated_docs = self._find_generated_document_artifacts(row)
            pdf_path = pdf_path or generated_docs.get("pdf_path", "")
            docx_path = docx_path or generated_docs.get("docx_path", "")
            cover_letter_pdf_path = cover_letter_pdf_path or generated_docs.get("cover_letter_pdf_path", "")
            cover_letter_docx_path = cover_letter_docx_path or generated_docs.get("cover_letter_docx_path", "")

        if (not cover_letter_docx_path or not cover_letter_pdf_path) and (docx_path or pdf_path):
            cv_artifact = Path(docx_path or pdf_path)
            suffix = cv_artifact.stem
            version_dir_match = re.match(r"^CV\d+$", cv_artifact.parent.name, flags=re.IGNORECASE)
            if version_dir_match and suffix.startswith("CV_"):
                suffix = suffix[3:]
                cover_letter_name = f"COVER_LETTER_{suffix}"
            elif suffix.startswith("CV_"):
                suffix = suffix[3:]
                cover_letter_name = f"COVER_LETTER_{suffix}"
            else:
                version_match = re.match(r"^CV(\d+)_(.+)$", suffix, flags=re.IGNORECASE)
                if version_match:
                    cover_letter_name = f"COVER_LETTER{version_match.group(1)}_{version_match.group(2)}"
                else:
                    cover_letter_name = f"COVER_LETTER_{suffix}"
            cover_letter_base = cv_artifact.with_name(cover_letter_name)
            if not cover_letter_docx_path:
                cover_letter_docx_path = self._resolve_existing_path(str(cover_letter_base.with_suffix(".docx")))
            if not cover_letter_pdf_path:
                cover_letter_pdf_path = self._resolve_existing_path(str(cover_letter_base.with_suffix(".pdf")))

        portfolio_path = self._ensure_portfolio_artifact(
            row,
            docx_path=docx_path,
            pdf_path=pdf_path,
        )

        persisted_source_path = pdf_path or docx_path or cv_text_path or source_path
        job_post_id = row.get("id") or row.get("job_post_id")
        if job_post_id and persisted_source_path:
            should_persist = any(
                [
                    self._normalize_for_compare(original_source_path) != self._normalize_for_compare(persisted_source_path),
                    self._normalize_for_compare(original_portfolio_path) != self._normalize_for_compare(portfolio_path),
                    self._normalize_for_compare(original_cover_letter_path) != self._normalize_for_compare(cover_letter_path),
                    self._normalize_for_compare(original_cover_letter_docx_path) != self._normalize_for_compare(cover_letter_docx_path),
                    self._normalize_for_compare(original_cover_letter_pdf_path) != self._normalize_for_compare(cover_letter_pdf_path),
                ]
            )
            if should_persist:
                self.update_generated_cv_path(
                    int(job_post_id),
                    persisted_source_path,
                    portfolio_path=portfolio_path,
                    cover_letter_path=cover_letter_path,
                    cover_letter_docx_path=cover_letter_docx_path,
                    cover_letter_pdf_path=cover_letter_pdf_path,
                    generated_headline=str(row.get("generated_headline") or ""),
                    generated_summary=str(row.get("generated_summary") or ""),
                    generated_experience_summary=str(row.get("generated_experience_summary") or ""),
                    generated_llm_model=str(row.get("generated_llm_model") or ""),
                    generated_llm_backend=str(row.get("generated_llm_backend") or ""),
                    generated_llm_usage_json=str(row.get("generated_llm_usage_json") or ""),
                )

        row["cv_source_path"] = persisted_source_path or source_path or original_source_path
        row["portfolio_path"] = portfolio_path or original_portfolio_path
        row["cover_letter_path"] = cover_letter_path or str(row.get("cover_letter_path") or "")
        try:
            row["generated_llm_usage"] = json.loads(str(row.get("generated_llm_usage_json") or "").strip() or "{}")
        except Exception:
            row["generated_llm_usage"] = {}
        row["generated_pdf_path"] = pdf_path
        row["generated_docx_path"] = docx_path
        row["generated_cv_text_path"] = cv_text_path
        row["generated_cover_letter_docx_path"] = cover_letter_docx_path
        row["generated_cover_letter_pdf_path"] = cover_letter_pdf_path
        row["generated_fit_report_path"] = fit_report_path
        row["generated_video_path"] = self._resolve_portfolio_video_path()
        return self._apply_preview_path_aliases(row)

    def _enrich_generated_cv_artifacts_light(self, row: dict[str, Any]) -> dict[str, Any]:
        source_path = str(row.get("cv_source_path") or "").strip()
        portfolio_path = str(row.get("portfolio_path") or "").strip()
        cover_letter_path = str(row.get("cover_letter_path") or "").strip()
        cover_letter_docx_path = str(row.get("cover_letter_docx_path") or "").strip()
        cover_letter_pdf_path = str(row.get("cover_letter_pdf_path") or "").strip()
        suffix = Path(source_path).suffix.lower() if source_path else ""
        pdf_path = source_path if suffix == ".pdf" else ""
        docx_path = source_path if suffix == ".docx" else ""
        cv_text_path = source_path if suffix == ".txt" else ""

        row["cv_source_path"] = source_path
        row["portfolio_path"] = portfolio_path
        row["cover_letter_path"] = cover_letter_path
        try:
            row["generated_llm_usage"] = json.loads(str(row.get("generated_llm_usage_json") or "").strip() or "{}")
        except Exception:
            row["generated_llm_usage"] = {}
        row["generated_pdf_path"] = pdf_path
        row["generated_docx_path"] = docx_path
        row["generated_cv_text_path"] = cv_text_path
        row["generated_cover_letter_docx_path"] = cover_letter_docx_path
        row["generated_cover_letter_pdf_path"] = cover_letter_pdf_path
        row["generated_fit_report_path"] = str(row.get("generated_fit_report_path") or "").strip()
        row["generated_video_path"] = self._resolve_portfolio_video_path()
        return self._apply_preview_path_aliases(row)

    def list_jobs(
        self,
        *,
        stage: str,
        country: str,
        countries: list[str],
        regions: list[str],
        exclude_countries: list[str],
        languages: list[str],
        programming_languages: list[str],
        work_models: list[str],
        employment_types: list[str],
        easy_apply: int,
        constraint_mode: str,
        has_cv: int,
        apply_error: int,
        priority_flag: int,
        sort_by: str,
        posted_within_days: int,
        company: str,
        search: str,
        summary_only: bool,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        filters = {
            "stage": stage,
            "country": country,
            "countries": countries,
            "regions": regions,
            "work_models": work_models,
            "employment_types": employment_types,
            "constraint_mode": constraint_mode,
            "search": search,
            "sort_by": sort_by,
            "has_cv": has_cv,
            "easy_apply": easy_apply,
            "priority_flag": priority_flag,
        }
        self.logger.info("List jobs | filters=%s limit=%s offset=%s", filters, limit, offset)
        started_at = time.perf_counter()
        result = self.repo.list_jobs(
            stage=stage,
            country=country,
            countries=countries,
            regions=regions,
            exclude_countries=exclude_countries,
            languages=languages,
            programming_languages=programming_languages,
            work_models=work_models,
            employment_types=employment_types,
            easy_apply=easy_apply,
            constraint_mode=constraint_mode,
            has_cv=has_cv,
            apply_error=apply_error,
            priority_flag=priority_flag,
            sort_by=sort_by,
            posted_within_days=posted_within_days,
            company=company,
            search=search,
            summary_only=summary_only,
            limit=limit,
            offset=offset,
        )
        repo_elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        enrich_started_at = time.perf_counter()
        raw_items = [dict(item) for item in (result.get("items") or [])]
        items = [self._enrich_generated_cv_artifacts_light(item) for item in raw_items]
        enrich_elapsed_ms = int((time.perf_counter() - enrich_started_at) * 1000)
        self.logger.info(
            "List jobs result | returned=%s total=%s repo_ms=%s enrich_ms=%s summary_only=%s",
            len(items),
            int(result.get("total") or 0),
            repo_elapsed_ms,
            enrich_elapsed_ms,
            bool(summary_only),
        )
        return {"total": int(result.get("total") or 0), "items": items}

    def job_detail(self, job_post_id: int, constraint_mode: str = "medium") -> dict[str, Any] | None:
        self.logger.info("Job detail requested | id=%s constraint=%s", job_post_id, constraint_mode)
        row = self.repo.get_job_detail(job_post_id, constraint_mode=constraint_mode)
        if row is None:
            self.logger.warning("Job detail missed | id=%s", job_post_id)
            return None
        payload = row.get("latest_payload_json") or "{}"
        try:
            row["latest_payload"] = json.loads(payload)
        except Exception:
            row["latest_payload"] = {}
        row["jd_text"] = self.repo._sanitize_jd_text(str(row.get("jd_text", "") or ""))
        payload_jd = self.repo._sanitize_jd_text(str(row.get("latest_payload", {}).get("jd", "") or ""))
        if payload_jd:
            row["latest_payload"]["jd"] = payload_jd
        else:
            row["latest_payload"].pop("jd", None)
        # Fallback for old records where latest_payload_json may miss JD text.
        if not str(row.get("latest_payload", {}).get("jd", "")).strip() and str(row.get("jd_text", "")).strip():
            row["latest_payload"]["jd"] = row["jd_text"]
        return self._enrich_generated_cv_artifacts_light(row)

    def cv_preview(self, job_post_id: int, constraint_mode: str = "medium") -> dict[str, Any] | None:
        self.logger.info("CV preview requested | id=%s constraint=%s", job_post_id, constraint_mode)
        started_at = time.perf_counter()
        row = self.job_detail(job_post_id, constraint_mode=constraint_mode)
        detail_elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if row is None:
            self.logger.warning("CV preview missing job | id=%s", job_post_id)
            return None
        artifact = self.repo.latest_generated_artifact_set(job_post_id)
        artifact_elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        materialization_error = ""
        if artifact:
            expected_paths = self._artifact_expected_paths(artifact)
            row.update(
                {
                    "generated_cv_text_path": self._resolve_existing_path(expected_paths.get("cv_txt", "")) or row.get("generated_cv_text_path"),
                    "generated_docx_path": self._resolve_existing_path(expected_paths.get("cv_docx", "")) or row.get("generated_docx_path"),
                    "generated_pdf_path": self._resolve_existing_path(expected_paths.get("cv_pdf", "")) or row.get("generated_pdf_path"),
                    "generated_fit_report_path": self._resolve_existing_path(expected_paths.get("fit_md", "")) or row.get("generated_fit_report_path"),
                    "portfolio_path": self._resolve_existing_path(expected_paths.get("portfolio_pdf", "")) or self._resolve_existing_path(expected_paths.get("portfolio_docx", "")) or row.get("portfolio_path"),
                    "cover_letter_path": self._resolve_existing_path(expected_paths.get("cover_txt", "")) or row.get("cover_letter_path"),
                    "cover_letter_docx_path": self._resolve_existing_path(expected_paths.get("cover_docx", "")) or row.get("cover_letter_docx_path"),
                    "cover_letter_pdf_path": self._resolve_existing_path(expected_paths.get("cover_pdf", "")) or row.get("cover_letter_pdf_path"),
                }
            )
            # Short-circuit materialization if artifacts already exist to reduce latency.
            has_cv_files = any(
                Path(str(p)).exists()
                for p in [
                    row.get("generated_cv_text_path"),
                    row.get("generated_docx_path"),
                    row.get("generated_pdf_path"),
                    row.get("cv_source_path"),
                ]
            )
            has_cover_files = any(
                Path(str(p)).exists()
                for p in [
                    row.get("cover_letter_path"),
                    row.get("cover_letter_docx_path"),
                    row.get("cover_letter_pdf_path"),
                ]
            )
            materialization_needed = not (has_cv_files and has_cover_files)
            if materialization_needed:
                try:
                    materialize_started_at = time.perf_counter()
                    materialized = self._materialize_generated_artifact_set(row, artifact)
                    materialize_elapsed_ms = int((time.perf_counter() - materialize_started_at) * 1000)
                    row.update(
                        {
                            "cv_source_path": materialized.get("pdf_path") or materialized.get("docx_path") or materialized.get("cv_path") or row.get("cv_source_path"),
                            "portfolio_path": materialized.get("portfolio_path") or row.get("portfolio_path"),
                            "cover_letter_path": materialized.get("cover_letter_path") or row.get("cover_letter_path"),
                            "cover_letter_docx_path": materialized.get("cover_letter_docx_path") or row.get("cover_letter_docx_path"),
                            "cover_letter_pdf_path": materialized.get("cover_letter_pdf_path") or row.get("cover_letter_pdf_path"),
                            "generated_pdf_path": materialized.get("pdf_path") or row.get("generated_pdf_path"),
                            "generated_docx_path": materialized.get("docx_path") or row.get("generated_docx_path"),
                            "generated_cv_text_path": materialized.get("cv_path") or row.get("generated_cv_text_path"),
                            "generated_cover_letter_docx_path": materialized.get("cover_letter_docx_path") or row.get("generated_cover_letter_docx_path"),
                            "generated_cover_letter_pdf_path": materialized.get("cover_letter_pdf_path") or row.get("generated_cover_letter_pdf_path"),
                            "generated_headline": str(artifact.get("headline") or row.get("generated_headline") or ""),
                            "generated_summary": str(artifact.get("summary") or row.get("generated_summary") or ""),
                            "generated_experience_summary": str(artifact.get("experience_summary") or row.get("generated_experience_summary") or ""),
                            "generated_llm_model": str(artifact.get("llm_model") or row.get("generated_llm_model") or ""),
                            "generated_llm_backend": str(artifact.get("llm_backend") or row.get("generated_llm_backend") or ""),
                        }
                    )
                    try:
                        row["generated_llm_usage"] = json.loads(str(artifact.get("llm_usage_json") or row.get("generated_llm_usage_json") or "").strip() or "{}")
                    except Exception:
                        row["generated_llm_usage"] = row.get("generated_llm_usage") or {}
                    self.logger.info(
                        "CV preview materialized | id=%s artifact_id=%s elapsed_ms=%s",
                        job_post_id,
                        artifact.get("id"),
                        materialize_elapsed_ms,
                    )
                except Exception as exc:
                    materialization_error = str(exc)
                    self.logger.exception("CV preview materialization failed | id=%s artifact_id=%s", job_post_id, artifact.get("id"))
        enrich_started_at = time.perf_counter()
        row = self._enrich_generated_cv_artifacts(row)
        enrich_elapsed_ms = int((time.perf_counter() - enrich_started_at) * 1000)
        total_elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        row["artifact_diagnostics"] = self._build_generated_artifact_diagnostics(row, artifact)
        if materialization_error:
            row["artifact_diagnostics"]["materialization_error"] = materialization_error
        self.logger.info(
            "CV preview timing | id=%s detail_ms=%s artifact_ms=%s enrich_ms=%s total_ms=%s materialize=%s",
            job_post_id,
            detail_elapsed_ms,
            artifact_elapsed_ms,
            enrich_elapsed_ms,
            total_elapsed_ms,
            "yes" if materialization_error == "" else "error",
        )
        return self._apply_preview_path_aliases(row)

    def repair_generated_artifacts(
        self,
        *,
        limit: int = 100,
        only_missing: bool = True,
        constraint_mode: str = "medium",
        recent_days: int = 0,
    ) -> dict[str, Any]:
        repaired_items: list[dict[str, Any]] = []
        missing_after_repair = 0
        for job_post_id in self.repo.list_generated_artifact_job_ids(
            limit=limit,
            only_missing=only_missing,
            recent_days=recent_days,
        ):
            preview = self.cv_preview(job_post_id, constraint_mode=constraint_mode)
            if not preview:
                continue
            diagnostics = dict(preview.get("artifact_diagnostics") or {})
            missing_fields = list(diagnostics.get("missing_fields") or [])
            if missing_fields:
                missing_after_repair += 1
            repaired_items.append(
                {
                    "job_post_id": int(preview.get("id") or preview.get("job_id") or 0),
                    "title": str(preview.get("title") or ""),
                    "company": str(preview.get("company") or ""),
                    "missing_fields": missing_fields,
                    "repairable_fields": list(diagnostics.get("repairable_fields") or []),
                    "artifact_id": int(diagnostics.get("artifact_id") or 0),
                }
            )
        return {
            "ok": True,
            "requested_limit": int(limit),
            "recent_days": int(recent_days),
            "processed": len(repaired_items),
            "jobs_still_missing_fields": missing_after_repair,
            "items": repaired_items,
        }

    def countries(self) -> list[str]:
        return self.repo.list_countries()

    def regions(self) -> list[str]:
        return self.repo.list_regions()

    def region_countries(self) -> list[dict[str, Any]]:
        return self.repo.list_region_countries()

    def programming_languages(self) -> list[str]:
        return self.repo.list_programming_languages()

    def programming_language_groups(self) -> list[dict[str, Any]]:
        return self.repo.list_programming_languages_grouped()

    def update_generated_cv_path(
        self,
        job_post_id: int,
        cv_source_path: str,
        *,
        portfolio_path: str = "",
        cover_letter_path: str = "",
        cover_letter_docx_path: str = "",
        cover_letter_pdf_path: str = "",
        generated_headline: str = "",
        generated_summary: str = "",
        generated_experience_summary: str = "",
        generated_llm_model: str = "",
        generated_llm_backend: str = "",
        generated_llm_usage_json: str = "",
    ) -> None:
        self.repo.update_generated_cv_path(
            job_post_id,
            cv_source_path,
            portfolio_path=portfolio_path,
            cover_letter_path=cover_letter_path,
            cover_letter_docx_path=cover_letter_docx_path,
            cover_letter_pdf_path=cover_letter_pdf_path,
            generated_headline=generated_headline,
            generated_summary=generated_summary,
            generated_experience_summary=generated_experience_summary,
            generated_llm_model=generated_llm_model,
            generated_llm_backend=generated_llm_backend,
            generated_llm_usage_json=generated_llm_usage_json,
        )

    def save_generated_artifact_set(
        self,
        *,
        job_post_id: int,
        documents_date_folder: str,
        company_folder_name: str,
        version_number: int,
        run_folder_name: str,
        output_slug: str,
        output_basename: str,
        cv_text: str,
        portfolio_text: str,
        cover_letter_text: str,
        fit_report_text: str,
        headline: str,
        summary: str,
        experience_summary: str,
        llm_model: str,
        llm_backend: str,
        llm_usage_json: str,
        source_kind: str = "rewrite",
    ) -> dict[str, Any]:
        return self.repo.save_generated_artifact_set(
            job_post_id=job_post_id,
            documents_date_folder=documents_date_folder,
            company_folder_name=company_folder_name,
            version_number=version_number,
            run_folder_name=run_folder_name,
            output_slug=output_slug,
            output_basename=output_basename,
            cv_text=cv_text,
            portfolio_text=portfolio_text,
            cover_letter_text=cover_letter_text,
            fit_report_text=fit_report_text,
            headline=headline,
            summary=summary,
            experience_summary=experience_summary,
            llm_model=llm_model,
            llm_backend=llm_backend,
            llm_usage_json=llm_usage_json,
            source_kind=source_kind,
        )

    def next_generated_artifact_version(self, *, documents_date_folder: str, company_folder_name: str) -> int:
        return self.repo.next_generated_artifact_version(
            documents_date_folder=documents_date_folder,
            company_folder_name=company_folder_name,
        )

    def update_manual_review_status(self, job_post_id: int, *, required: bool, note: str) -> None:
        self.logger.info(
            "Manual review update | job=%s required=%s note_present=%s", job_post_id, required, bool(note.strip())
        )
        self.repo.update_manual_review_status(job_post_id, required=required, note=note)

    def update_job_priority_status(self, job_post_id: int, *, priority_flag: str, note: str) -> None:
        self.logger.info("Job priority update | job=%s priority=%s note_present=%s", job_post_id, priority_flag, bool(note.strip()))
        self.repo.update_job_priority_status(job_post_id, priority_flag=priority_flag, note=note)

    def update_company_priority_status(self, company_name: str, *, priority_flag: str, note: str) -> None:
        self.logger.info("Company priority update | company=%s priority=%s note_present=%s", company_name, priority_flag, bool(note.strip()))
        self.repo.update_company_priority_status(company_name, priority_flag=priority_flag, note=note)

    def mark_job_applied_manual(self, job_post_id: int, *, note: str = "") -> None:
        self.logger.info("Mark job applied manually | job=%s note_present=%s", job_post_id, bool(note.strip()))
        self.repo.mark_job_applied_manual(job_post_id, note=note)

    def delete_jobs(self, job_post_ids: list[int]) -> int:
        self.logger.info("Delete jobs request | count=%s ids=%s", len(job_post_ids), job_post_ids[:5])
        return self.repo.delete_jobs(job_post_ids)
