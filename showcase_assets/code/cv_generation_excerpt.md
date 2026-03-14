# CV Generation and Artifact Workflow Excerpt

This excerpt shows part of the pipeline that generates tailored CV artifacts, versioned outputs, and related files such as PDF, DOCX, cover letter, and portfolio pages.

```python
def run_with_text(...):
    jd_slug = self._slugify(output_slug.strip() or Path(jd_source_name).stem)
    run_folder = self._next_run_folder(jd_slug)
    run_folder.mkdir(parents=True, exist_ok=True)

    output_basename = self._build_output_basename(
        cv_master=cv_master,
        job_context=job_context or {},
        run_folder=run_folder,
    )

    company_documents_dir = documents_day_dir / company_folder
    version_number = self._next_artifact_version(company_documents_dir)
    version_dir = company_documents_dir / f"CV{version_number}"
    version_dir.mkdir(parents=True, exist_ok=True)

    docx_out = self._reserve_output_path(version_dir / f"{output_basename}.docx")
    pdf_out = docx_out.with_suffix(".pdf")
    portfolio_out = self._reserve_output_path(version_dir / f"{self._build_portfolio_output_basename(output_basename)}.html")

    llm_payload = self._call_llm(...)
    cv_text = str(llm_payload.get("cv_text", "")).strip()
    summary = str(llm_payload.get("summary", "")).strip()

    cv_out.write_text(cv_text + "\\n", encoding="utf-8")
    portfolio_out.write_text(
        self._build_portfolio_html(..., summary=summary, cv_text=cv_text),
        encoding="utf-8",
    )
```

What this demonstrates:

- artifact versioning with `CV1`, `CV2`, `CV3`
- generated document lifecycle
- LLM-assisted CV tailoring plus deterministic file handling
