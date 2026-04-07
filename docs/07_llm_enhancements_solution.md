**Goal**: Analyze ETL and CV Rewrite flows and propose non-invasive, prioritized enhancements focusing on LLM actions, robustness, observability, and concrete developer-ready artifacts. Do not implement — this document is a design and rollout plan.

**Scope**
- Two flows: ETL (job ingestion → artifacts) and CV Rewrite (master CV + JD → LLM → rewritten CV / cover letter / fit report).
- Use current codebase entry points (see files referenced below) and suggest changes limited to orchestration, prompts, validation logic, observability, and safe fallbacks.

**Key files / entry points (for reviewer)**
- ETL orchestration & persistence: [scripts/python/linkedin_jobs_jd.py](scripts/python/linkedin_jobs_jd.py)
- Fit evaluation rules: [scripts/python/evaluate_cv_fit.py](scripts/python/evaluate_cv_fit.py)
- CV rewrite guide: [CV_REWRITE_STRICT_GUIDE.md](CV_REWRITE_STRICT_GUIDE.md)
- Rewrite orchestration / agents: [tmp_seek_automation/integrations/agent.py](tmp_seek_automation/integrations/agent.py)
- Local LLM gateway controller: [apps/backend/app/controllers/local_llm_controller.py](apps/backend/app/controllers/local_llm_controller.py)
- CV rendering: [scripts/python/render_cv_docx.py](scripts/python/render_cv_docx.py)


## 1) Current flows summary (short)
- ETL: scrapers collect job posts → parsing & normalization → text chunking & embeddings → store in sqlite tables (`job_posts`, `job_text_embeddings`, `job_generated_artifact_sets`) → optional artifact generation/backfill scripts.
- CV Rewrite: user-provided master CV + JD + guide → build prompt payload → submit to LLM (OpenAI / MetaAI / local gateway) → parse response into `cv_text`, `cover_letter`, `fit_report` → render files and run `evaluate_cv_fit.py` → store artifacts in `input/Raw_CV/...`.


## 2) Problems & failure modes observed (analysis)
- LLM response schema varies across providers (raw text vs structured JSON). Parsing failures cause empty/missing cover letters or broken outputs.
- No strict contract/schema enforced between orchestrator and LLM: free-text responses are fragile.
- Little telemetry on the gateway outputs; diagnosing issues requires manually reproducing requests or reading logs.
- Token / context window risks for large master CV + JD combined prompts — may silently truncate or produce partial outputs.
- Insufficient verification step for hallucinations or fabricated claims (the guide mandates no fabrication but LLMs may still hallucinate).
- Fit evaluation uses a deterministic rule-based script; LLM evaluation was added but not standardized for schema or calibration.

Detailed failure example observed in repo:
- Local gateway returns a mixed response (text or JSON). The caller expected a `cover_letter` field but sometimes receives plain text, causing empty outputs and reliance on fallback heuristics. The fix path needs a validator + diagnostic collection to reproduce and patch parsing rules.


## 3) Design goals for LLM enhancements
- Introduce a strict, minimal response schema and validator for all LLM responses used in automation.
- Prefer structured outputs (JSON) with fields: `cv_text`, `cover_letter`, `headline`, `summary`, `fit_evaluation` (optional), `notes`.
- Add robust parsing & fallback to heuristic generators when schema is absent or invalid.
- Add observability: save raw LLM outputs, prompt payloads (redacted), and evaluation artifacts to a logs store to speed diagnostics.
- Add verification: automated checks to detect hallucinations and a reconciliation step against `master_cv` (e.g., assert every asserted skill appears in master CV). Fail fast if critical violations detected.
- Add orchestration rules for chunking / streaming when prompt size exceeds thresholds.
- Instrument scoring calibration to align LLM `total_score` with existing rule-based `weighted_total` outputs.


## 4) Proposed solution (prioritized, non-invasive)

Priority 1 — Safety & Schema (low-effort, high-impact)
- Define a minimal JSON schema for CV rewrite responses. Example schema quick spec:
  - `cv_text` (string, required)
  - `cover_letter` (string, optional)
  - `fit_evaluation` (object, optional) with `total_score` (0-100), `domain_score`, `tech_score`, `evidence` (array)
  - `notes` (array of strings)
- Implement a validator utility (pure Python function) that accepts raw LLM output and tries:
  1. JSON parse → validate fields and numeric ranges.
  2. If parse fails, use heuristics to extract sections (look for markers like `CV_TEXT:`, `COVER_LETTER:` or triple-backtick fenced outputs).
  3. If heuristics fail, mark as `fallback_text` and call the current `_compose_cover_letter` / `_compose_cv` fallback.
- Map this validator to `tmp_seek_automation/integrations/agent.py` parsing step and to `apps/backend/app/controllers/local_llm_controller.py` fallback builder.

Validator pseudocode (developer-ready)
```
def validate_llm_response(raw_text: str) -> dict:
    # Try JSON first
    try:
        obj = json.loads(raw_text)
        if is_valid_schema(obj):
            return { 'ok': True, 'parsed': obj, 'mode': 'json' }
    except Exception:
        pass

    # Heuristic extraction: look for fenced blocks or headings
    sections = heuristic_extract_sections(raw_text)
    if sections.get('cv_text') or sections.get('cover_letter'):
        return { 'ok': True, 'parsed': sections, 'mode': 'heuristic' }

    # Fallback: return raw_text for deterministic composer
    return { 'ok': False, 'parsed': { 'fallback_text': raw_text }, 'mode': 'fallback' }
```

Priority 2 — Observability & Diagnostics
- Persist redacted prompt and raw LLM responses to `tmp_seek_automation/logs/llm_prompts/` with timestamped filenames and a small manifest.
- Log meta: model id, resolved upstream URL, token usage (if available), response length, parsed vs fallback.
- Add a small `diagnose_llm_response.py` utility to quickly summarize differences between parsed JSON fields and fallback text.

Priority 3 — Verification & Anti-Hallucination
- Implement a `verify_against_master_cv(master_cv_text, generated_cv_text)` function that:
  - Extracts claimed skills and technologies from generated CV (very conservative regex/NER); cross-check against tokens in `master_cv_text`.
  - If high-risk fabricated claims (e.g., explicit years, job titles, certifications) are detected that don't exist in `master_cv_text`, mark the artifact as `needs_review` and move to a review queue (do not auto-apply).
- For claims that are `partially supported` (e.g., transferable skills), annotate `notes` explaining source evidence location in master CV (line/section). Keep the generated CV but flag for manual review.

Verification sketch (developer-ready)
```
def verify_against_master(master_text, generated_text):
  claims = extract_claims(generated_text)  # e.g., skills, certs, years
  evidence_index = build_inverted_index(master_text)
  issues = []
  for claim in claims:
    if not evidence_index.contains(claim.key_terms):
      issues.append({'claim': claim, 'reason': 'no evidence'})
  return issues
```

Priority 4 — Prompt & Context Engineering
- Standardize prompt assembly in a single helper so both ETL and rewrite flows reuse the same, tested prompt templates.
- Implement a prompt length check: if combined prompt tokens > X (configurable), then apply compression strategies:
  - Extract top-K keywords from JD and only include matched evidence snippets from master CV (e.g., relevant experience bullets), or
  - Use a two-stage LLM flow: a) extract rubric & top requirements; b) synthesize CV using condensed evidence.
- Add a short, strict system instruction enforcing the JSON schema and refusing to output non-JSON: e.g., "Return ONLY a single valid JSON object with fields: ...". Expect some noise from LLMs — rely on validator & fallback.

Priority 5 — Fit evaluation calibration
- Standardize the LLM `fit_evaluation` numeric range and mapping to existing `evaluate_cv_fit.py` outputs. Create a calibration routine to map LLM 0-1 scores to 0-100 rule-based scale, using a small seed dataset (10-30 examples) to align thresholds (
  e.g., LLM 0.85 -> rule 85).
- Keep both signals (rule-based weighted_total and LLM_eval). Use configurable combiner (weighted average) and surface both in `fit_report` for transparency.

Priority 6 — Retry / Backoff and Provider Fallback
- Add a 3-attempt retry with exponential backoff for transient gateway/network failures.
- If local gateway fails or returns invalid schema repeatedly, fallback to MetaAI/OpenAI if configured, or use heuristic fallback described in `local_llm_controller.py`.

Retry policy example (pseudocode):
```
for attempt in range(1,4):
  try:
    resp = call_gateway(payload)
    if validate_llm_response(resp)['ok']:
      break
  except transient_exc:
    sleep(2 ** attempt)
else:
  use_fallback()
```

Priority 7 — Monitoring & Ops
- Emit simple metrics (count of rewrite requests, success vs fallback, average total_score, parse_failures) to a CSV or a lightweight metrics file in `tmp_seek_automation/logs/metrics.csv`.
- Add an alert rule (simple script) to email or log when parse_failures exceed threshold in a day.


## 5) Implementation notes & mapping to repo (where to change — analysis only)
- Add validator utility: `tmp_seek_automation/common/llm_schema.py` (pure Python). Use in:
  - `tmp_seek_automation/integrations/agent.py` (LocalAgent & Meta/OpenAI adapters) — validate LLM responses before returning to pipeline.
  - `apps/backend/app/controllers/local_llm_controller.py` — validate upstream results and enrich fallback responses.
- Observability: create `tmp_seek_automation/logs/llm_prompts/` and small logger helper `tmp_seek_automation/common/llm_logging.py`.
- Verification: add `tmp_seek_automation/common/verification.py` with `verify_against_master_cv` and `extract_claims` helpers.
- Prompt helpers: `tmp_seek_automation/common/prompt_templates.py` that expose parameterized templates and compression helpers.
- Calibration: `scripts/python/llm_calibrate.py` (analysis utility) to produce a small mapping table.

Suggested manifest format for LLM logs (JSON lines):
```
{ "timestamp": "2026-03-15T12:00:00Z", "job_post_id": 12345, "model": "qwen2.5:1.5b-instruct", "payload_sha256": "...", "response_path": "logs/llm_prompts/resp_*.json", "parse_mode": "json|heuristic|fallback", "parse_ok": true }
```


## 6) Backwards compatibility & safety
- All changes should be additive: adopt validator & logs but keep current fallback heuristics intact.
- Default behavior should remain unchanged if no LLM gateway present: MetaAI path should still work.
- Only change orchestration to use validator outputs; never auto-apply when validator reports high-risk hallucination.


## 7) Rollout plan (3-phase)
- Phase 1 (days 0–2): Add validator + logging + minimal integration in `agent.py`. No behavior change — only record metrics and log parse failures.
- Phase 2 (days 3–7): Switch orchestrator to prefer validated JSON outputs; wire verification checks that mark artifacts `needs_review` rather than auto-apply. Add retries and backoff.
- Phase 3 (days 8–14): Calibration, gating thresholds, monitoring dashboards, and optional provider fallback logic.


## 8) Quick Risk Assessment
- False positives in verification (incorrectly flagging honest claims) — mitigate by conservative heuristics and manual review queue.
- LLM refusal to emit JSON when forced — mitigate with validator & graceful fallback to heuristic generator and human review.
- Increased latency — mitigated with async calls and caching frequently requested rubric extractions.


## 9) Example JSON response contract (suggested)
{
  "cv_text": "...",
  "cover_letter": "...",
  "headline": "...",
  "summary": "...",
  "fit_evaluation": {
    "total_score": 87.5,
    "domain_score": 82.0,
    "tech_score": 90.0,
    "evidence": ["Experience designing APIs using FastAPI (Project X)", "2+ years production Python"],
    "notes": ["Used heuristic mapping for .NET -> transferable backend skills"]
  },
  "notes": ["Generated by qwen2.5:1.5b-instruct via local gateway"] 
}


## 10) Next steps (if you want me to proceed)
- I can draft `tmp_seek_automation/common/llm_schema.py` and a small `diagnose_llm_response.py` for review (no runtime wiring) so we have the validator implementation ready.
- Or I can produce a small checklist/PR template documenting testing steps for Phase 1 rollout.

Recommendation: I will prepare the validator and diagnostics drafts as non-invasive files (no runtime wiring) so you can review the exact parsing and verification logic before we integrate.


---
Prepared by assistant — analysis only (no runtime changes applied beyond earlier diagnostic logging).