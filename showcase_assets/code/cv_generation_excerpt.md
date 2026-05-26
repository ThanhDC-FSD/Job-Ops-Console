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


## How To Explain "Improvement" Claims

When a CV bullet says `improved`, `reduced`, `cut`, or `stabilized`, the explanation should always follow the same structure:

1. define the metric
2. state the baseline
3. state the change made
4. state the new result
5. show the formula used

This keeps the claim operational instead of sounding subjective.

### Core formulas

- reduction percent:
  - `(baseline - new_value) / baseline * 100`
- improvement percent for throughput or success rate:
  - `(new_value - baseline) / baseline * 100`
- failed-run reduction:
  - `(baseline_failed_runs - new_failed_runs) / baseline_failed_runs * 100`
- manual-time reduction:
  - `(baseline_minutes - new_minutes) / baseline_minutes * 100`

### 1. Stability On CPU-Only Hardware

Example CV wording:

- `Added reliability gates and deterministic fallbacks ... improving stability on CPU-only hardware and reducing failed runs by ~40%.`

How to define it:

- `stability` means the pipeline completes with a usable output under the same local CPU-only environment
- `failed run` means a run that times out, returns unusable output, violates validation constraints, or misses a required artifact such as the cover letter

What changed:

- no-op rewrite detection
- coverage delta checks
- constraint filters
- mandatory artifact enforcement
- deterministic fallback path instead of full abort

How to calculate:

- baseline example:
  - `25 failed runs out of 100`
- after the reliability changes:
  - `15 failed runs out of 100`
- formula:
  - `(25 - 15) / 25 * 100 = 40%`

How to defend it:

- `I defined failure first, then measured before and after on the same CPU-only setup. The main gain was not raw speed; it was fewer broken runs and less batch interruption.`

What to mention if asked about hardware:

- CPU-only local inference has tighter latency and timeout limits than GPU-backed inference
- because of that, reliability controls matter more than peak throughput
- the optimization target was successful completion rate, not benchmark speed alone

### 2. Manual Formatting Time Reduced By ~80%

Example CV wording:

- `Automated document workflows ... reducing manual formatting time by ~80% and improving consistency across versions.`

How to define it:

- `formatting time` means the operator time required to transform generated text into clean DOCX/PDF artifacts with correct headings, spacing, bullet alignment, and section ordering
- `consistency` means repeated outputs follow the same layout rules instead of drifting between versions due to manual editing

What changed:

- tagged plain-text intermediate format
- dedicated rendering script for DOCX/PDF
- deterministic artifact naming and versioning
- reusable layout rules instead of ad hoc manual edits

How to calculate:

- baseline example:
  - `15 minutes manual formatting per artifact set`
- after automation:
  - `3 minutes review and minor touch-up`
- formula:
  - `(15 - 3) / 15 * 100 = 80%`

How to defend it:

- `I compared operator time before and after the renderer was in place. The improvement came from moving formatting work into a deterministic pipeline, so the operator mostly reviews instead of rebuilding the document manually.`

How to explain consistency:

- fewer spacing differences
- fewer heading-style mismatches
- fewer version-to-version layout deviations
- lower chance of one artifact format drifting away from another

### 3. Release Steps Reduced By ~60%

Example CV wording:

- `... reducing manual release steps by ~60% while improving traceability.`

How to define it:

- count the operator-managed release actions that had to be performed manually
- examples:
  - export
  - rename
  - copy
  - validate
  - upload
  - map metadata
  - verify linkage

How to calculate:

- baseline example:
  - `10 manual steps`
- after automation:
  - `4 manual steps`
- formula:
  - `(10 - 4) / 10 * 100 = 60%`

How to defend it:

- `The number was based on workflow-step reduction, not CPU time. The value came from removing repeated operator actions while preserving auditability and metadata traceability.`

### 4. Deployment Turnaround Time Cut By ~30%

Example CV wording:

- `... cutting deployment turnaround time by ~30% and reducing repeatable release errors.`

How to define it:

- `deployment turnaround time` means elapsed time from release-start to deploy-complete for a normal release path

How to calculate:

- baseline example:
  - `20 minutes`
- after CI/CD improvement:
  - `14 minutes`
- formula:
  - `(20 - 14) / 20 * 100 = 30%`

How to defend it:

- `I measured end-to-end release duration for the same class of deployment before and after workflow automation.`

### 5. Time-To-Diagnose Reduced By ~25%

Example CV wording:

- `... reducing time-to-diagnose for runtime issues by ~25%.`

How to define it:

- `time-to-diagnose` means the time from observing the issue to identifying the responsible failing stage, component, or payload

What changed:

- real-time event feedback
- structured logging
- better stage markers and runtime visibility

How to calculate:

- baseline example:
  - `20 minutes average issue diagnosis`
- after observability changes:
  - `15 minutes`
- formula:
  - `(20 - 15) / 20 * 100 = 25%`

How to defend it:

- `The gain came from observability. I reduced search time and ambiguity during incident analysis rather than changing the business logic itself.`

### 6. Turnaround Time For Localization Improved By ~50%

Example CV wording:

- `... improving turnaround time for content localization by ~50%.`

How to define it:

- measure elapsed time to produce subtitle extraction, translation, and speech-processing outputs for the same content class

How to calculate:

- baseline example:
  - `40 minutes`
- after automation:
  - `20 minutes`
- formula:
  - `(40 - 20) / 40 * 100 = 50%`

How to defend it:

- `I measured the total processing path for similar media inputs before and after automation, including the manual handoff work that the pipeline removed.`

## Quick Interview Rule

If asked where the number came from, answer like this:

- `It is a before/after operational measurement on the same workflow, not a marketing guess. I first defined the metric, then compared the baseline and the post-change result under comparable conditions.`

## Performance And Reliability Lens

For technical interviews, classify every improvement into one of these buckets:

- `latency`: total wall-clock time, p50, p95, max
- `compute`: duplicate work removed, number of expensive steps reduced
- `prompt efficiency`: prompt size, selected context, token budget
- `stability`: retry count, fallback rate, failed-run rate, completion rate
- `operator efficiency`: manual steps or review time removed

For this CV-generation pipeline, the strongest story is:

- deterministic artifact handling reduced operator work
- validation and fallback logic reduced failed runs
- dedicated rendering scripts improved consistency without changing business behavior
