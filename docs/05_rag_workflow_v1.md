# RAG Workflow Reference (v1+)

The following reference describes the refreshed rerank/rewrite pipeline that powers the Job Ops Console. It is tuned for the weak local environment (CPU-only, ~4 GB RAM, offline gateway, token-efficient flows) and preserves the existing business logic while clarifying implementation, observability, and validation gaps.

## Goals & environment constraints
- **Local-first hardware:** every component should work on Intel Core i5 / low RAM machines, minimize repeated tokenization, and favor SQLite/JSON artifact stores. Heavy models stay offline in the qwen2.5 gateway.
- **Deterministic grounding:** evidence must drive every rewrite/apply decision so outputs never invent facts. Unsupported requirements are surfaced explicitly in the rewrite contract.
- **Delivery quality:** CV rewrites must be more targeted than the originals, cover letters are mandatory for apply packages, and validators gate out generic or stale outputs.

## Architecture overview
The workflow keeps the four-layer structure from the original design but now adds explicit implementation notes, data contracts, and observation points.

1. **Crawl + SQLite ETL** keeps scraping LinkedIn/Seek/Apify, parsing HTML, and storing metadata in `job_posts`, `crawl_runs`, and `job_text_embeddings`. Heuristic fit scoring still runs in `evaluate_cv_fit.py`, and borderline output feeds the rerank queue before new artifacts enter `Raw_CV`.
2. **Vector + Retrieval** now distinguishes raw embeddings (`job_text_embeddings`, `vector_index`, `crawl_runs`) from curated knowledge (`job_generated_artifact_sets`, `job_detail_validations`, `job_fit_scores`). Filters (location, visa, seniority, freshness) run at the retrieval layer before ranking.
3. **RAG + Offline LLM** consists of the query processor, intent classifier, retriever, reranker, scoring router, and offline generators (qwen2.5). Routing and fallback decisions emit metadata for observability.
4. **Rewrite + Fit Loop** now starts with evidence extraction, enforces validators and no-op guards, and ends with an explicit JSON contract that includes fit checks, cover letters, and quality flags.

## A. Evidence-first rewrite flow
1. **JD analyzer** ingests the JD text/payload, extracts must-have/nice-to-have requirements, seniority signals, tooling keywords, and constraints (location, visa, remote). Output is `jd_analysis` metadata.
2. **CV evidence extractor** parses the existing CV (master DOCX/TXT within `Raw_CV` or prior rewrite) and produces tagged snippets per requirement, capturing dates, technologies, and outcomes.
3. **Requirement-to-evidence mapper** attempts to match each JD requirement to CV evidence. Matches carry confidence levels (`high`, `medium`, `low`), scenario notes, and fallback instructions.
4. **Rewrite planner** uses the evidence map to prioritize rewrite sections, align skills with job needs, and plan cover letter hooks. It also captures unsupported requirements with reasons for the final quality checks.
5. **Generator** consumes the plan and only the documented evidence. Prompts are templated to reference evidence IDs, and any unsupported requirement is explicitly labeled as such before invoking the offline LLM.
6. **Validators run before and after generation** (see section G). Pre-generation validators ensure the plan meets coverage goals; post-gen validators enforce schema, diff thresholds, evidence alignment, and cover letter presence.
7. **Fallback deterministic rewrite** and fallback cover letter execute when the validator detects missing evidence, no-op rewrites, or absent cover letters. These deterministic outputs still respect the JSON contract and escalate the corresponding error tag.

## B. Mandatory cover letter rule
- In `mode=apply_package` or `rewrite_application_flow`, the pipeline must produce a cover letter; pipelines without one fail validation with `missing_cover_letter`.
- Validators automatically detect missing or invalid cover letters, log the failure reason, and invoke the deterministic fallback generator to produce a minimal, evidence-backed letter.
- `cover_letter_present` in the output contract toggles to `true` only after the fallback (if needed) completes successfully.

## C. No-op rewrite guard
- **Rewrite diff checker:** compares normalized tokens between the incoming CV and the generated CV; if edits are below the `diff_threshold`, the validator triggers a retry with alternative evidence prompts.
- **Coverage delta checker:** ensures the percentages of must-have requirements covered improve after the rewrite; if the delta is zero, the pipeline records `rewrite_no_op` and re-runs with an adjusted prompt.
- **JD relevance delta:** detects whether the output emphasizes new JD keywords or metrics relative to the original; failure triggers a fallback rewrite and flags `routing_misfire` for analysis.
- The guard produces structured notes (which are persisted in `tmp_seek_automation/logs`) and prevents releasing rewrites that are effectively identical to the source.

## D. Hybrid retrieval specification
- **Score formula:** `total_score = 0.55 * semantic_score + 0.30 * keyword_score + 0.15 * metadata_score`.
- **Semantic score:** cosine similarity between query embedding and stored vectors in `job_text_embeddings`.
- **Keyword score:** exact keyword, n-gram, and requirement matches between query text and job metadata.
- **Metadata score:** heuristics for freshness, location match, visa, remote preference, seniority, and source reliability.
- **Defaults/thresholds:** top_k=12, reranker selects top_3; RAG path requires `total_score >= 0.72` and `metadata_score >= 0.4`; fallback path kicks in when `0.55 <= total_score < 0.72` or metadata mismatches (visa/location); insufficient evidence path is used when `total_score < 0.55` or fewer than three requirements have supporting evidence.
- **Feature filters:** `location` (match/remote), `visa` (sponsorship compatibility), `remote/onsite` (preference flags), `seniority` (must align with JD), `source freshness` (default 90 days). Filtering happens before reranking to keep retrieval lean.

## E. Logical data layer separation
- **Raw retrieval layer:** `job_posts`, `job_text_embeddings`, `crawl_runs`, `job_fit_scores` provide the original crawl data and embedding vectors.
- **Curated knowledge layer:** `job_generated_artifact_sets`, `job_detail_validations`, `job_observations` store validated CV/cover letter drafts, validator annotations, and structured summaries.
- **Fit evidence layer:** aggregated results from `job_fit_scores`, `job_detail_validations`, and `job_application_tracking` produce the `fit_evidence` used in the rewrite planner.
- **Feedback/audit artifacts:** logs in `tmp_seek_automation/logs`, `linkedin_extension.sync.log`, and `job_apply_events` are retained for review and incremental learning.
- All layers reside in SQLite and are joined via `job_post_id`, `run_id`, and `artifact_id` for lightweight, offline-friendly queries.

## F. Output contracts / JSON schema
The rewrite/apply flow returns a structured JSON artifact stored alongside `Raw_CV`:

```json
{
  "jd_analysis": {...},
  "evidence_map": [{"requirement":"","matched_cv_evidence":[],"confidence":"","note":""}],
  "fit_assessment": {
    "matched_requirements": [],
    "partially_matched_requirements": [],
    "unmatched_requirements": [],
    "risky_claims_to_avoid": []
  },
  "cv_rewrite": {
    "summary": "",
    "experience_bullets": [],
    "skills_focus": []
  },
  "cover_letter": {"title":"","body":""},
  "quality_checks": {
    "cv_enhanced": true,
    "cover_letter_present": true,
    "unsupported_claims_found": [],
    "generic_phrases_found": [],
    "notes": []
  }
}
```
Key flags: `cv_enhanced`, `cover_letter_present`, `unsupported_claims_found`, and `generic_phrases_found` drive downstream gating and observability.

## G. Validator expansion
Validators are lightweight heuristics running inside the backend before persistence:
- **Evidence alignment validator:** ensures must-have requirements map to evidence (confidence >= medium), otherwise emits `unsupported_claim`.
- **Constraint validator:** checks location/visa/remote signals from JD against CV metadata; mismatch triggers `constraint_violation` and fallback.
- **Coverage validator:** compares pre/post coverage deltas for must-have and nice-to-have sets; non-improvement triggers `rewrite_no_op` retries.
- **Presence validator:** enforces cover letter delivery; failure raises `missing_cover_letter` and triggers deterministic fallback.
- **No-op rewrite validator:** monitors normalized diff/coverage deltas (diff ratio, keyword injection, actual metrics) and reflows the request if the rewrite is too close to the original.

## H. Observability & error taxonomy
Every request records:
- `routing_reason` (why RAG vs fallback)
- `retrieval_source` (raw vs curated vs fit evidence)
- `score_breakdown` (semantic, keyword, metadata)
- `validator_failure_reason` (e.g., `validator_evidence_fail`)
- `fallback_reason` (e.g., `insufficient_evidence`, `missing_cover_letter`)
- `human_review_notes` when manual review is triggered

Error taxonomy:
- `parse_error`
- `retrieval_low_confidence`
- `routing_misfire`
- `rewrite_no_op`
- `missing_cover_letter`
- `unsupported_claim`
- `validator_schema_fail`
- `validator_evidence_fail`

Logs land in `tmp_seek_automation/logs` and the backend log for quick triage.

## I. Module input/output contracts
1. **Query processor:** input raw query ? output normalized text + metadata; failures (`parse_error`) drop or reroute to fallback.
2. **Intent classifier:** input normalized query ? output intent bucket + priority; low confidence falls back to manual review.
3. **Retriever:** input embedding + filters ? output top_k candidates + scores; empty results log `retrieval_low_confidence` and escalate fallback.
4. **Reranker/scorer:** input top_k ? output ranked list + score breakdown; timeouts log `routing_misfire` and use deterministic keyword reranking.
5. **Generator:** input evidence plan ? output CV + cover letter; unsupported claims or hallucinations invoke validators that mark `unsupported_claim` and run fallback.
6. **Validator:** input generated artifacts + evidence metadata ? output quality flags; failures re-run fallback path or halt.
7. **Rewrite pipeline:** input JD + CV + evidence map ? output JSON contract; failure behavior covers `rewrite_no_op` and deterministic fallback strategies.
8. **Fit evaluator:** input rewritten CV + job context ? output fit score + gate decisions; missing artifacts leads to `validator_schema_fail`.
9. **Persistence/feedback loop:** input validated artifacts ? update SQLite tables/vector index; DB locks trigger retries with exponential backoff.

## J. Practical implementation notes
- Favor lightweight heuristics (keyword scoring, coverage deltas) over heavy ML to keep latency low on the constrained hardware.
- Deterministic fallback (template rewrites, fallback cover letters) ensures predictable results when the LLM output misses.
- Metadata filters (location, visa, seniority, freshness) prevent the reranker from dealing with incompatible candidates.
- Evidence-first generation and strict contracts make the flow auditable and easier to debug.
- No-op guard + validators stop repeated rewrites that add no value.

Use this document as the design reference for the implementation; it now supplies explicit flows, contracts, validators, and observability hooks that map to concrete code modules and log artifacts.
## K. Prompt contract layer
- **Prompt construction:** each prompt is built from the `evidence_map` and includes fields: `job_summary`, `requirement_priorities`, `evidence_references` (list of snippet IDs + confidence), `target_section`, `prohibited_claims`, `output_structure`, and `token_budget`.
- **Evidence references:** evidence IDs (e.g., `cv_snip_42`) are interpolated into sentences such as "Use `cv_snip_42` (React PWA diagnostics) to describe offline resilience" so the model can cite the source; unsupported requirements are prefixed with the `prohibited_claims` list to prevent hallucination.
- **Prompt variants:**
  - *First attempt* uses the full `requirement_priorities`, max evidence per section (default 3), and the full token budget (`token_budget_first=2200`).
  - *Retry attempt* tightens the prompt by shrinking `token_budget_retry=1600`, elevating the highest-confidence evidence, and removing stale or low-impact snippets.
  - *Fallback attempt* switches to deterministic templates that replicate the key evidence in bullet form; the prompt flags `fallback_mode=true` and limits outputs to 600 tokens.
- **Token budget strategy:** allocate 60% of tokens to core CV narrative, 30% to achievements, and 10% to the cover letter introduction; multi-round prompts track consumption to avoid exceeding qwen2.5 limits.
- **Required constraints:** prompts instruct the model to only restate facts present in `evidence_references`, to cite each bullet with at least one reference ID, and to emit JSON objects matching the output contract.

## L. Retry strategy
- **Max retries:** 2 retries per attempt (first attempt + up to two additional retries) before falling back.
- **Retry conditions:** triggered when post-generation validators report `rewrite_no_op`, `coverage_low`, or evidence misalignment.
- **What changes between retries:**
  - *Prompt tightening* reduces evidence volume, increases instruction specificity (e.g., "focus on Node/Nest work described in `cv_snip_84`)."
  - *Evidence filtering* removes low-confidence snippets (confidence < medium) and reorders remaining evidence by `requirement_priority`.
  - *Requirement prioritization* bumps a previously partially covered requirement to the top of the list.
- **Retry vs fallback:** retries stay within the LLM flow, delivering another structured generation attempt; fallback occurs when retries exhaust, switching to deterministic templates and marking `fallback_reason` (e.g., `unsupported_claim`).

## M. Prompt compression strategy
- **JD compression:** keep must-have requirements, tooling keywords, constraints (location/visa/remote), and drop long prose beyond 1800 characters. Summaries include bulletized requirements with categories.
- **CV compression:** include only recent (last 5 years) and relevant roles; limit to 4 responsibilities per role, prioritized by overlap with JD keywords. Remove redundant paragraphs (e.g., generic leadership statements) and keep only technology-specific achievements.
- **Token budgets:** `token_budget_first=2200`, `token_budget_retry=1600`, `token_budget_fallback=800`; JD+CV summaries are truncated to 900 tokens each using sliding window trimming that keeps start/middle/end slices.
- **Truncation strategy:** slice long evidence blocks into head/middle/tail fragments; reassemble the fragments prioritized by requirement relevance. Always preserve `must-have` evidence even if it requires sacrificing lower-priority nice-to-have chunks.

## N. Evidence scoring specification
- **Confidence computation:** each evidence snippet scores by `(relevance_score + recency_score + doc_authenticity_score) / 3`. Thresholds: `high >= 0.75`, `medium >= 0.55`, `low < 0.55`.
- **Validator mapping:** high-confidence evidence satisfies coverage requirements automatically; medium or low evidence must pair with at least two independent mentions before inclusion.
- **Inclusion thresholds:** cover letter may only cite evidence with `confidence >= medium`; the CV body may include a single high-confidence snippet per bullet plus contextual medium snippets.
- **Score persistence:** evidence scores are stored in `job_detail_validations` for downstream reuse.

## O. Fallback hierarchy
1. **Retry with improved prompt** � triggered on `rewrite_no_op` or validator warnings; log `retry_reason=coverage_delta` and note `retry_outcome` when succeeding.
2. **Retry with reduced scope** � when evidence volume causes token overflow; limit requirements, log `retry_reason=token_budget`, and ensure the next prompt targets a subset of requirements.
3. **Deterministic rewrite** � uses templates to assemble bullet statements from evidence_map without invoking the LLM; log `fallback_reason=deterministic_rewrite` and cite evidence IDs.
4. **Minimal safe output** � if templates fail (missing evidence), emit a structured note that highlights gaps (`unsupported_claim`) and retains the old CV unchanged, logging `fallback_reason=minimal_safe`.
Each stage writes `outcome` (success/fail) and `error_taxonomy` tags.

## P. Performance guards
- **Max JD length:** drop/notify when JD exceeds 3500 characters; compressor condenses to top must-have blocks.
- **Max CV length:** restrict incoming CV to 7,500 tokens; longer CVs are truncated by removing older or low-relevance sections.
- **Max top_k:** retrieval caps at `top_k=12`; reranker only re-scores top 3.
- **Timeouts:** each module has a soft timeout (query processor 2s, retriever 3s, generator 12s, validator 5s); when a timeout occurs, log `error_taxonomy=routing_misfire` or `validator_schema_fail` and move to fallback.
- **Memory-safe batching:** CLI tasks process evidence/embeddings in batches of 32; large queries are chunked to avoid exceeding ~4?GB RAM.

## Q. Final self-check (implementation status log)
After implementing the above points:
1. Verify the evidence-first rewrite flow is unambiguous and captures JD requirements ? pass only if `jd_analysis` and `evidence_map` are produced for every run.
2. Confirm CV enhancement cannot be skipped by testing the no-op guard; any violation logs `rewrite_no_op` and triggers a retry.
3. Ensure every apply package generates a cover letter (validator enforces `cover_letter_present`).
4. Validate the overall flow respects CPU-only constraints (timeouts, token budgets, SQLite queries). If any checks fail, mark the workflow as `needs_manual_review` and log the failure type.

The implementation log beneath this section should state:
- what was added (prompt contract, retry/compression, evidence scoring, fallback hierarchy, performance guards)
- what was clarified (no-op guard + evidence-first flow, validators, output contract)
- remaining risks (tuning thresholds, fallback text quality, edge-case timeouts)

Use this final self-check as the authoritative verification before marking the workflow reference as complete.
## R. Strict JSON schema details
Extend the output contract with stringent rules so each artifact is machine-verifiable:
- `jd_analysis` (required, object) contains `must_have_requirements`, `nice_to_have_requirements`, `responsibilities`, `tools_and_technologies`, `seniority_signals`, `constraints` (arrays of strings); each string max 256 chars.
- `evidence_map` (required, array of objects) and each entry must have `requirement` (non-empty string), `matched_cv_evidence` (array of strings referencing evidence IDs), `confidence` (enum: `high`, `medium`, `low`), `note` (optional string =512 chars). Empty evidence lists are allowed only when `confidence=low` and `note` explains why.
- `fit_assessment` (required, object) with arrays `matched_requirements`, `partially_matched_requirements`, `unmatched_requirements`, `risky_claims_to_avoid` (all strings =512 chars).
- `cv_rewrite` (required, object) contains `summary` (string =1024 chars), `experience_bullets` (array of strings =512 chars each), `skills_focus` (array of short phrases =128 chars each).
- `cover_letter` (required, object) with `title` (string =128 chars) and `body` (string =2048 chars); `cover_letter_present` indicates whether both fields are non-empty.
- `quality_checks` (required, object) with:
  - `cv_enhanced` (boolean) true only when diff and coverage validators pass.
  - `cover_letter_present` (boolean) true iff the cover letter has non-empty title/body.
  - `unsupported_claims_found` (array of strings) lists requirement identifiers lacking evidence; max 32 entries.
  - `generic_phrases_found` (array of strings) each =128 chars, identifies template text flagged for manual review.
  - `fallback_reason` (enum: `none`, `missing_cover_letter`, `unsupported_claim`, `rewrite_no_op`, `token_budget`, `validator_schema_fail`).
  - `validator_failure_reason` (enum: `none`, `validator_schema_fail`, `validator_evidence_fail`, `constraint_violation`, `coverage_low`).
  - `notes` (array of free-form strings =256 chars) to capture additional context.
- `metadata` (object, optional) may include `prompt_version`, `schema_version`, `retrieval_version`, `validator_version`, and `threshold_version` (all strings matching `v\d+\.\d+`).
- Every persisted artifact (JSON + rendered docs) must embed `schema_version` and the `timestamp` of generation. When a field lacks a value, default to empty string/array except for required enums which must explicitly be set to `none` where applicable.

## S. Pipeline state model
Define the lifecycle for rewrite/apply jobs:
1. `received` (entry: new request enqueued; exit when JD analyzer completes). Next: `analyzed`.
2. `analyzed` (entry when JD analyzer outputs requirement list; exit when evidence map exists). Next: `evidence_mapped`.
3. `evidence_mapped` (entry once requirement?evidence matching passes; exit when rewrite planner produces plan). Next: `planned`.
4. `planned` (entry when template + evidence prioritization ready; exit when generation request is sent). Next: `generated`.
5. `generated` (entry on LLM result arrival; exit after validators run). Next: `validated` or `retrying`.
6. `validated` (entry when validators pass; exit to `persisted`). Next: `persisted`.
7. `retrying` (entry if validator flags `rewrite_no_op`/`coverage_low`; exit back to `planned` for rerun or to `fallback_generated` after retries exhausted). Next: `planned` or `fallback_generated`.
8. `fallback_generated` (entry when deterministic or minimal safe fallback produced; exit when manual review needed or persisted). Next: `manual_review` or `persisted`.
9. `manual_review` (entry when human review triggered by low confidence, unsupported claims, or validator failure; exit when review data is re-ingested). Next: `persisted`.
10. `persisted` (entry when artifacts stored + metadata logged; terminal success state).
11. `failed` (entry when unrecoverable errors occur�timeout, data corruption); terminal.
Allowed transitions respect the above sequence; e.g., `validated` may only go to `persisted` (unless a later validator rerun is triggered), `retrying` only loops between `planned` ? `generated`, etc.

## T. Deterministic template spec
Fallback templates stay lightweight:
- **CV rewrite template:** header lists `name`, `role`, `target JD`. Body composed of concatenated bullet templates:
  1. `Achievement bullet`: "{technology} {action} that {outcome} (evidence: {evidence_id})." Only include technology/outcome if corresponding evidence has `confidence >= medium`.
  2. `Responsibility bullet`: "Authored {system} modules, focusing on {requirement_tag}." Omit if the evidence is `confidence=low`.
  3. **Skills section:** builds from top 5 technologies with `confidence >= high`.
- **Cover letter template:** structure of 3 paragraphs: (a) introduction referencing JD/company, (b) highlight of 2 evidence-backed achievements, (c) closing with interest and contact. Each paragraph cites at least one evidence ID; paragraphs are omitted if no relevant evidence.
- Templates accept `evidence_map` entries and fill placeholders only when confidence threshold met; otherwise they log `fallback_reason=unsupported_claim` and leave the section blank (not filled with guesses). All templates are intentionally concise (=600 tokens total) to keep generation deterministic and hardware-friendly.

## U. Acceptance criteria / benchmark targets
Set measurable goals tuned for CPU-only operations:
- **Cover letter missing rate:** =1% (the validator/fallback must cover missing letters).
- **Rewrite_no_op rate:** <5% of rewrites; if higher, adjust prompt diff thresholds.
- **Unsupported_claim rate:** <3 entries per request, logged for manual review.
- **Coverage improvement rate:** must-have requirement coverage must increase by =15 percentage points from baseline.
- **Latency targets:** query processor =2s, retriever =3s, reranker =2s, generator =12s, validators =5s.
- **Token budget compliance:** 100% of prompts must stay within the allocated budgets (first/retry/fallback); logs flag `token_budget` otherwise.
- **Retries per request:** =2 to avoid blocking the CPU; more than 2 automatically switches to deterministic fallback.
Benchmarks are collected per run and stored in `tmp_seek_automation/logs/performance_metrics.json` (JSON array with timestamped values).

## V. Versioning / config traceability
Each component records version metadata:
- **Prompt contract version:** `prompt_version` (string) increments when template structure changes.
- **Output schema version:** `schema_version` matches section R's versioning labels.
- **Retrieval formula version:** `retrieval_version` tracks weight adjustments/thresholds.
- **Validator rules version:** `validator_version` updates when validators add new gates or thresholds.
- **Threshold version:** `threshold_version` for configurable values (token budgets, diff thresholds, coverage goals).
Every persisted artifact (JSON, PDF, logs) includes these version tags plus a `generation_timestamp`. When reading artifacts later, the system determines whether re-processing is required if current versions differ from those stored.

## W. Manual review policy
Manual review triggers when:
- `unsupported_claims_found` contains >3 items.
- Evidence confidence is low for must-have requirements after retries/fallback.
- Validator failure reasons (constraint violation, coverage low) land in error taxonomy.
Human reviewers may adjust CV text, add missing evidence references, or approve fallback templates; they are not allowed to invent new facts beyond the provided evidence_map. Reviewed artifacts re-enter the workflow by updating `job_generated_artifact_sets` and re-running validators; only validated outputs (with a `manual_review=true` flag) are persisted in the curated knowledge layer. Raw audit logs (snapshots, manual notes) remain in `tmp_seek_automation/logs/manual_review` for traceability.

## X. Final consistency check
Self-review outcomes:
- Implementation readiness: document now specifies strict schema, state model, prompt/retry/compression strategies, fallback hierarchy, performance guards, versioning, and manual review.
- Ambiguity is removed by the state machine and concrete templates + validators.
- Fallback behavior is explicit (retry ? deterministic templates ? minimal safe output).
- Benchmark targets (rates, latencies, token budgets) are measurable and suited for low-power systems.
- Versioning/traceability and manual review policies are clearly defined.

Summary of additions: strict JSON schema, pipeline state model, deterministic templates, acceptance metrics, version tracing, manual review policy plus final self-check.
Remaining low-confidence areas: tuning of coverage improvement thresholds and manual-review turnaround limits still needs live data, and deterministic template wording may require stylistic refinement based on real feedback.
## Y. Request / orchestration schema
- `request_id` (required, string UUID) uniquely identifies the workflow job at enqueue time; reused across retries and manual review edits.
- `mode` (required, enum: `rewrite`, `apply_package`, `feedback`, `manual_review`) controls whether cover letter is mandatory.
- `intent` (required, string) describes the user-level goal (e.g., `apply_linkedin`, `revise_cv`).
- `source` (optional, enum: `ui`, `api`, `scheduler`, `manual`) indicates where the request originated; defaults to `api`.
- `job_post_id` (optional integer) links to the crawled job; null for general rewrites.
- `cv_id` (optional string) points to the Raw_CV entry being rewritten; required for apply packages.
- `priority` (optional integer, default 0) lets scheduler bump urgent runs; higher values run sooner.
- `created_at` (required, timestamp) records enqueue time.
- `current_state` (required, string) reflects the pipeline state model (see section S).
- `retry_count` (required, integer =0) increments each time the job re-enters `retrying`.
- `idempotency_key` (required, string) dedupes repeated requests; any incoming request with an existing key is checked before reprocessing.
  - Defaults: `source=scheduler`, `priority=0`, `retry_count=0`. The orchestration layer rejects requests missing `request_id`, `mode`, `intent`, or `idempotency_key`.

## Z. Persistence / write contract
- `job_generated_artifact_sets` stores the raw generated JSON artifacts, including `cv_text`, `cover_letter_text`, `json_contract`, `schema_version`, `prompt_version`, etc.
- `job_generated_documents` (new table) holds rendered CV/PDF/Docx output paths, `cv_hash`, `cover_letter_hash`, `rendered_at`, and `artifact_set_id` referencing the JSON.
- `job_detail_validations` records validation results (`validator_version`, `quality_checks`, `error_taxonomy`, `notes`), one row per artifact run.
- `job_fit_scores` (existing) holds score breakdowns plus new columns `score_semantic`, `score_keyword`, `score_metadata`, `token_budget_used`, `latency_ms`; each run logs a row for benchmarking.
- `job_state_transitions` (new table) stores `request_id`, `from_state`, `to_state`, `transition_at`, `reason`, `retry_count`, and `actor` (system/manual).
- Logs/ manual review snapshots stored under `tmp_seek_automation/logs` with retention of 90 days; manual review entries include `manual_notes`, `reviewer_id`, `review_timestamp`, and link to the artifact set.
- All persistence occurs via explicit SQLite transactions (see section AB) and writes include `schema_version`/`version_metadata` for traceability.

## AA. Idempotency and dedup policy
- Every request must supply an `idempotency_key` (UUID); before processing, the system checks `job_generated_artifact_sets.idempotency_key`. If a run exists with the same key and `cv_enhanced=true`, the request is marked `duplicate` and no new artifact is persisted.
- Artifact hashing: calculated SHA-256 hash of normalized `cv_text` + `cover_letter_text`. Only one final artifact per `request_id` is allowed; any rerun overwrites the same `artifact_set_id` if the hash changes, otherwise marked `rewrite_no_op`.
- Safe rerun: retries use the same `request_id`/`idempotency_key`; the state machine increments `retry_count` and updates `current_state`, but duplicate payloads (same hash) are short-circuited.
- Manual review edits keep the original `idempotency_key` but append `-review` suffix when generating a new artifact; dedup checks still find the previous key and allow reprocessing because the suffix differs.
- Duplicate requests (same idempotency_key, same mode) received while a job is running are acknowledged but not re-enqueued; the API returns the existing `request_id` and current state.

## AB. SQLite transaction and locking policy
- Transaction boundaries: each module (generator ? validator ? persistence) executes within `BEGIN IMMEDIATE` transactions; operations modify `job_generated_artifact_sets`, `job_detail_validations`, `job_fit_scores`, and `job_state_transitions` in one atomic group.
- Atomic write groups: JSON contract + rendered output entries are written together; failure during rendered output insertion rolls back the entire transaction to prevent partially persisted states.
- Rollback on failure: caught exceptions log `validator_schema_fail` or `persistence_fail`, issue `ROLLBACK`, and release locks immediately so retries can proceed.
- Retry/backoff on locks: when SQLite returns `database is locked`, the service waits `base_delay * 2^attempts` (base 200ms, max 5 retries) before reattempting the transaction; prolonged lock triggers alert and forces fallback to deterministic routing.
- Persistence order: first insert `job_generated_artifact_sets`, then `job_detail_validations`, then `job_fit_scores`, and finally `job_state_transitions`. Logs/backups remain separate (no transaction) to avoid long-lived locks.

## AC. Test matrix
1. **Happy path rewrite**
   - Input: valid JD/CV, strong evidence, expect states `received?analyzed?...?persisted`, validators pass, quality flags good, JSON contract stored, no fallback.
2. **Apply package with valid cover letter**
   - Input: apply mode request, evidence for cover letter, expect cover letter present flag true, output stored, `cover_letter_present=true`.
3. **Missing cover letter fallback**
   - Input: apply mode, generator returns empty cover letter, validator triggers `missing_cover_letter`, fallback templates produce letter, quality flags note fallback.
4. **Rewrite_no_op retry path**
   - Input: generator reuses old content, validator flags `rewrite_no_op`, state cycles to `retrying`, new prompt run, eventual success logged.
5. **Unsupported claim path**
   - Input: JD requirement with no evidence, validator sets `unsupported_claim`, fallback deterministic rewrite invoked, manual review flagged.
6. **Low-confidence manual review path**
   - Input: evidence confidence low; validator failure reason `coverage_low`, manual_review state entered, human edits, revalidated.
7. **Timeout/weak hardware fallback**
   - Input: generator times out (>12s); error taxonomy `routing_misfire`, fallback path triggered, minimal safe output persisted.
8. **Persistence failure / DB lock retry**
   - Input: simulate `database is locked`; transaction retries up to five times; if still locked, log error and mark `failed` state.
9. **Manual review re-entry**
   - Input: post-review artifact flagged for rerun, state transitions include `manual_review?persisted`, version tags updated.
Each test asserts expected `job_state_transitions` entries, validation flags, persisted JSON, and log entries.

## AD. Worked examples
1. **Evidence map sample**
   ```json
   {
     "requirement":"PWA resiliency",
     "matched_cv_evidence":["cv_snip_12","cv_snip_19"],
     "confidence":"high",
     "note":"React extension + offline caching snippets"
   }
   ```
2. **First-attempt prompt sample**
   ```text
   Prompt version v1.4
   Job summary: Senior React PWA for healthcare workflows.
   Requirements: [PWA resiliency, TypeScript architecture, Node backend]
   Evidence refs: cv_snip_12 (React offline), cv_snip_25 (Node API)
   Token budget: 2200 tokens; include output structure (JSON schema) and cite evidence IDs per bullet.
   ```
3. **Valid output JSON sample**
   ```json
   {
     "quality_checks":{
       "cv_enhanced":true,
       "cover_letter_present":true,
       "unsupported_claims_found":[],
       "generic_phrases_found":[],
       "fallback_reason":"none",
       "validator_failure_reason":"none"
     },
     "cover_letter":{"title":"", "body":""},
     "schema_version":"v1.0"
   }
   ```
4. **Deterministic fallback screenshot**
   - CV bullet: "Implemented offline-capable React diagnostics dashboards using evidence cv_snip_12." (omits citation if `confidence=low`).
   - Cover letter: paragraph referencing evidence ids, limited to 600 tokens total.

## AE. Final hardening check
Confirm:
- Schema (section Y) clearly defines required fields and defaults.
- Persistence rules (section Z) specify tables/storage responsibilities.
- Duplicate processing controlled via idempotency/hash policy (section AA).
- SQLite transactions and locking behavior are defined in section AB.
- Test expectations enumerated (section AC).
- Worked examples provide concrete references (section AD).

Summary of additions: orchestration schema, persistence/write contracts, idempotency policy, SQLite transaction policy, test matrix, worked examples, final hardening checklist.
Remaining minor risks: deterministic fallback wording may need refinement for readability, and precise hash comparisons require canonical normalization to avoid false duplicates.

## AF. Consistency cleanup
- **Modes:** `rewrite`, `apply_package`, `feedback`, `manual_review`. All controllers, validators, and watchers must use this enum; any old label should map to one of these four.
- **Intents:** use canonical names such as `apply_linkedin`, `revise_cv`, `collect_feedback`, and `start_manual_review`. Keep them lower-case and dash-separated (matching section Y).
- **Fallback reasons:** the unified enum is `none`, `missing_cover_letter`, `unsupported_claim`, `rewrite_no_op`, `token_budget`, `validator_schema_fail`. Section F, K, O, R, and AI now reference this set, so avoid alternative labels like "coverage_failure".
- **Validator failure reasons:** standardize on `none`, `validator_schema_fail`, `validator_evidence_fail`, `constraint_violation`, `coverage_low` (section R, G, H).
- **State names:** `received`, `analyzed`, `evidence_mapped`, `planned`, `generated`, `validated`, `retrying`, `fallback_generated`, `manual_review`, `persisted`, `failed` (section S). Logging, persistence, and orchestration layers must log transitions using these exact identifiers.
- **Error taxonomy:** use `parse_error`, `retrieval_low_confidence`, `routing_misfire`, `rewrite_no_op`, `missing_cover_letter`, `unsupported_claim`, `validator_schema_fail`, `validator_evidence_fail` (section H). Any derived metrics or alerts must translate synonyms to these canonical tags.

## AG. Global config / constants registry
| Constant | Default | Usage | Configurable? |
|---|---|---|---|
| `RETRIEVAL_WEIGHT_SEMANTIC` | `0.55` | Hybrid score formula (section D) | yes |
| `RETRIEVAL_WEIGHT_KEYWORD` | `0.30` | Hybrid formula | yes |
| `RETRIEVAL_WEIGHT_METADATA` | `0.15` | Hybrid formula | yes |
| `TOP_K` | `12` | Number of candidates retrieved | yes |
| `RERANK_TOP_N` | `3` | Reranker scope (section D) | yes |
| `RAG_THRESHOLD` | `0.72` | Determines RAG path (section D) | yes |
| `FALLBACK_THRESHOLD` | `0.55` | Low-confidence fallback | yes |
| `DIFF_THRESHOLD` | `0.20` | Minimum diff ratio for cv_enhanced (sections C, U) | yes |
| `COVERAGE_IMPROVEMENT_THRESHOLD` | `0.15` | Must-have coverage delta | yes |
| `MAX_RETRIES` | `2` | Retry limit before fallback (section L) | yes |
| `TIMEOUT_QUERY_MS` | `2000` | Query processor | yes |
| `TIMEOUT_RETRIEVER_MS` | `3000` | Retriever | yes |
| `TIMEOUT_RERANKER_MS` | `2000` | Scorer | yes |
| `TIMEOUT_GENERATOR_MS` | `12000` | Generator | yes |
| `TIMEOUT_VALIDATOR_MS` | `5000` | Validator | yes |
| `TOKEN_BUDGET_FIRST` | `2200` | Prompt first attempt (section K) | yes |
| `TOKEN_BUDGET_RETRY` | `1600` | Retry prompt | yes |
| `TOKEN_BUDGET_FALLBACK` | `800` | Deterministic fallback | yes |
| `MAX_JD_LENGTH` | `3500` | JD pre-compression (section M) | yes |
| `MAX_CV_LENGTH_TOKENS` | `7500` | CV token cap | yes |
| `BATCH_SIZE` | `32` | Evidence processing batch (section P) | yes |
| `DB_LOCK_RETRY_COUNT` | `5` | SQLite lock backoffs (section AB) | yes |
| `RETAIN_LOG_DAYS` | `90` | Log/manual review retention (section Z) | yes |

## AH. Canonical normalization spec
- Lowercase text using NFC `.casefold()` before hashing or comparisons.
- Collapse whitespace sequences to single spaces and trim ends.
- Strip punctuation except evidence IDs (cv_snip_*) and hyphenated tech names.
- Normalize bullets to start with `- `, sort alphabetically when hashing, deduplicate before diff.
- Preserve evidence IDs verbatim for hashes but mask them temporarily when computing semantic similarity.
- Remove markdown tables, code blocks, and JSON braces before hashing; convert inline code to plain text.
- Exclude docx/pdf metadata from diff calculations; only the normalized CV body participates.
- Apply the same normalization to tokens before counting budgets to keep results reproducible.

## AI. Document rendering contract
- `cv_rewrite.summary` becomes the intro; `experience_bullets` render as ordered bullet lists grouped by role. Each bullet includes technologies/outcomes plus evidence IDs in parentheses.
- Cover letters use `cover_letter.title` as heading and split `cover_letter.body` into paragraphs; each paragraph cites at least one evidence ID or is omitted.
- Filenames follow `documents/{request_id}/cv_{request_id}.docx/.pdf` and `cover_letter_{request_id}.docx/.pdf`; JSON contract saved as `artifacts/{request_id}/rewrite_contract.json`.
- When `fallback_reason != none`, rendered files include a warning header and embed `fallback_reason` plus `validator_failure_reason` metadata.
- Validators block rendering if no cover letter until fallback supplies one; fallback placeholders note missing requirements while still saving the contract.
- Rendered files embed YAML front matter with `schema_version`, `prompt_version`, `retrieval_version`, `validator_version`, `threshold_version`, and `generation_timestamp`.

## AJ. Reprocessing / migration policy
- Prompt version changes mark artifacts `legacy_prompt=true`; re-running is optional unless manual review requests reprocessing.
- Schema version bumps set `needs_revalidate=true` but leave artifacts accessible.
- Retrieval version changes log `retrieval_version_at_generation`; full rerun is optional unless reranking filters change drastically.
- Validator version updates trigger light revalidation during the next sync; mismatches queue manual review via `validator_version_mismatch=true`.
- Threshold version updates set `threshold_version_mismatch=true`; regeneration occurs only when the difference is significant.
Old artifacts retain their original version tags and a `legacy=true` flag for filtering.

## AK. Expanded worked examples
1. Happy-path JSON snippet with positive quality checks and metadata tags.
2. Unsupported-claim JSON with `fallback_reason=unsupported_claim` and `validator_failure_reason=validator_evidence_fail`.
3. State trace: `received ? analyzed ? evidence_mapped ? planned ? generated ? retrying ? planned ? generated ? validated ? persisted`.
4. Persistence record snapshot showing rows in `job_generated_artifact_sets`, `job_generated_documents`, `job_detail_validations`, `job_fit_scores`, and `job_state_transitions` with relevant fields filled.
5. Deterministic fallback cover letter example (title, three evidence-linked paragraphs, =600 tokens).

## AL. Final closing review
- Terminology is consistent (AF), thresholds centralized (AG), hashing/diff deterministic (AH), rendering explicit (AI), version handling defined (AJ), and examples concrete (AK).
- Minor risk: fallback cover-letter wording may need refinement; hash normalization depends on consistent evidence ID formatting.
