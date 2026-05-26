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

### 7. Issue Triage And Context Gathering Reduced By ~35%

Example CV wording:

- `... reducing issue-triage and context-gathering time by ~35%.`

How to define it:

- `issue-triage and context-gathering time` means the operator time needed to collect relevant project context, identify likely risks, and form an actionable next-step view before starting execution

What changed:

- combined UI workflow instead of fragmented tools
- retrieval over existing project knowledge
- MCP-style tool access pattern for structured context fetches
- risk surfacing and mitigation hints in the same operator flow

How to calculate:

- baseline example:
  - `20 minutes average to gather context and produce a first triage view`
- after the workflow improvement:
  - `13 minutes`
- formula:
  - `(20 - 13) / 20 * 100 = 35%`

How to defend it:

- `The improvement was measured as operator time to reach a usable first triage view. The gain came from reducing context switching and consolidating retrieval, guidance, and workflow signals into one path.`

### 8. First-Draft Slide Preparation Reduced By ~70%

Example CV wording:

- `... reducing manual first-draft slide preparation time by ~70% while improving output consistency across iterations.`

How to define it:

- `first-draft slide preparation time` means the time required to turn prompts or structured notes into a usable initial slide outline with diagrams and editable content blocks

What changed:

- prompt-to-outline generation
- Mermaid-backed diagram generation
- editable content scaffolding
- one workflow that produces a reusable draft instead of starting each deck manually

How to calculate:

- baseline example:
  - `30 minutes to produce a usable first draft`
- after automation:
  - `9 minutes`
- formula:
  - `(30 - 9) / 30 * 100 = 70%`

How to defend it:

- `I measured the time to reach a usable first draft, not the final polished deck. The value came from automating the repetitive outline and diagram setup work while still leaving room for human editing.`

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
