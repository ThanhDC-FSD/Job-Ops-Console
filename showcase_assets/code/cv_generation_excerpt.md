# CV Generation Pipeline Excerpt

This excerpt shows the **pipeline-style orchestration** behind tailored CV generation. The process mixes deterministic artifact handling with LLM-assisted content generation.

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

    version_number = self._next_artifact_version(company_documents_dir)
    version_dir = company_documents_dir / f"CV{version_number}"
    version_dir.mkdir(parents=True, exist_ok=True)

    llm_payload = self._call_llm(...)
    cv_text = str(llm_payload.get("cv_text", "")).strip()
    summary = str(llm_payload.get("summary", "")).strip()

    cv_out.write_text(cv_text + "\\n", encoding="utf-8")
    portfolio_txt_out.write_text(
        self._build_portfolio_tagged_text(..., summary=summary),
        encoding="utf-8",
    )

    self._run_subprocess([... render_cv_docx.py ..., str(cv_out), ...])
    self._run_subprocess([... render_cv_docx.py ..., str(portfolio_txt_out), ...])
```

Why this matters:

- generation is structured as a sequence of well-defined stages
- artifact versioning is deterministic
- rendering is delegated to dedicated scripts instead of mixing concerns

Design pattern showcased:

- pipeline / staged processing
- separation of generation vs rendering
- versioned artifact management
