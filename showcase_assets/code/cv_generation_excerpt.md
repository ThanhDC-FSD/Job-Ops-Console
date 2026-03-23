# CV Generation And Artifact Workflow Excerpt

This excerpt shows the **rewrite -> validate -> render -> publish** path used to create tailored CV outputs and related portfolio assets.

## Tailored Rewrite Pipeline

The rewrite service starts by creating deterministic folders and version numbers before any model call happens.

```python
def run_with_text(
    self,
    *,
    cv_master: str,
    jd_text: str,
    guide_text: str,
    jd_source_name: str,
    job_context: dict[str, Any] | None = None,
    user_prompt: str,
    output_slug: str,
    llm_model: str,
    temperature: float,
    render_docx: bool,
    render_pdf: bool,
    run_fit_report: bool,
) -> CvRewriteResult:
    jd_slug = self._slugify(output_slug.strip() or Path(jd_source_name).stem)
    run_folder = self._next_run_folder(jd_slug)
    output_basename = self._build_output_basename(
        cv_master=cv_master,
        job_context=job_context or {},
        run_folder=run_folder,
    )
    documents_date_folder = self._documents_date_folder()
    company_folder = self._build_company_folder_name(company_name)
    version_number = int((job_context or {}).get("_artifact_version_number") or 1)

    llm_payload = self._call_llm(...)
    headline = str(llm_payload.get("headline", "")).strip()
    summary = str(llm_payload.get("summary", "")).strip()
    cv_text = str(llm_payload.get("cv_text", "")).strip()
```

Why this matters:

- artifact folders stay predictable across runs
- rewrite output can still be traced back to job, company, and version
- file naming does not depend on whether the LLM succeeds or fails

## Guarded Fallbacks

The pipeline does not assume a model response is complete. It fills missing sections locally when needed.

```python
if not summary:
    summary = self._compose_local_summary(
        title=str((job_context or {}).get("title") or "").strip(),
        jd_text=jd_text,
        cv_master=cv_master,
    )
if not headline:
    headline = str((job_context or {}).get("title") or "").strip() or self._build_local_headline(jd_text=jd_text)
if not cv_text:
    cv_text = self._apply_cv_patch(
        cv_master=cv_master,
        headline=headline,
        summary=summary,
    )

cover_letter = str(llm_payload.get("cover_letter", "")).strip()
if not cover_letter:
    cover_letter = self._compose_local_cover_letter(
        title=job_title or headline,
        company=company_name,
        summary=summary,
        jd_text=jd_text,
    )
```

Why this matters:

- local deterministic fallbacks keep the operator unblocked on a weak machine or flaky gateway
- output quality degrades gracefully instead of failing the whole run
- generation remains explainable because fallback behavior is explicit in code

## Rendering And Reporting

After text generation, the pipeline delegates rendering and fit analysis to dedicated scripts.

```python
if run_fit_report:
    self._run_subprocess(
        [
            str(self._venv_python()),
            str(self.project_root / "scripts" / "python" / "evaluate_cv_fit.py"),
            "--jd", str(jd_temp_path),
            "--cv", str(cv_temp_path),
            "--report", str(fit_report_out),
        ]
    )

self._run_subprocess([... render_cv_docx.py ..., str(cv_out), ...])
self._run_subprocess([... render_cv_docx.py ..., str(portfolio_txt_out), ...])
```

Why this matters:

- fit reporting is isolated from rewrite logic
- document rendering is reusable from batch scripts and the UI
- subprocess boundaries keep each stage easy to rerun or debug independently

## Portfolio Publishing

The portfolio output also embeds stable references to the public showcase and selected code snippets.

```python
lines.extend(
    [
        "<green><bold>Project Showcase Video</bold></green>",
        SHOWCASE_VIDEO_URL,
        "",
        "<green><bold>Public Showcase Repository</bold></green>",
        "https://github.com/ThanhDC-FSD/Job-Ops-Console/tree/showcase",
        "",
        "<green><bold>Selected Code Snippets</bold></green>",
        "Backend API: showcase_assets/code/backend_api_excerpt.md",
        "CV workflow: showcase_assets/code/cv_generation_excerpt.md",
        "Frontend analytics: showcase_assets/code/frontend_analytics_excerpt.md",
        "Learning quiz: showcase_assets/code/learning_quiz_excerpt.md",
    ]
)
```

Why this matters:

- generated artifacts point back to a public, reviewable showcase
- the portfolio stays linked to the same code excerpts used in the repo presentation
- recruiters and reviewers can move from document output to source-level evidence quickly

Design patterns showcased:

- staged pipeline orchestration
- fallback-first generation
- versioned artifact management
- separation of generation, validation, and rendering
