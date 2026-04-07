from pathlib import Path
path = Path('docs/rag_workflow_v1.md')
append = """
## AF. Consistency cleanup
- **Modes:** `rewrite`, `apply_package`, `feedback`, `manual_review`. All controllers, validators, and watchers must use this enum; any old label should map to one of these four.
- **Intents:** use canonical names such as `apply_linkedin`, `revise_cv`, `collect_feedback`, and `start_manual_review`. Keep them lower-case and dash-separated (matching section Y).
- **Fallback reasons:** the unified enum is `none`, `missing_cover_letter`, `unsupported_claim`, `rewrite_no_op`, `token_budget`, `validator_schema_fail`. Section F, K, O, R, and AI now reference this set, so avoid alternative labels like “coverage_failure.”
- **Validator failure reasons:** standardize on `none`, `validator_schema_fail`, `validator_evidence_fail`, `constraint_violation`, `coverage_low` (section R, G, H).
- **State names:** `received`, `analyzed`, `evidence_mapped`, `planned`, `generated`, `validated`, `retrying`, `fallback_generated`, `manual_review`, `persisted`, `failed` (section S). Logging, persistence, and orchestration layers must log transitions using these exact identifiers.
- **Error taxonomy:** use `parse_error`, `retrieval_low_confidence`, `routing_misfire`, `rewrite_no_op`, `missing_cover_letter`, `unsupported_claim`, `validator_schema_fail`, `validator_evidence_fail` (section H). Any derived metrics or alerts must translate synonyms to these canonical tags.
After this cleanup the document consistently refers to the same enums and names across every section.

## AG. Global config / constants registry
| Constant | Default | Usage | Configurable? |
|---|---|---|---|
| `RETRIEVAL_WEIGHT_SEMANTIC` | `0.55` | Hybrid score formula (section D) | yes |
| `RETRIEVAL_WEIGHT_KEYWORD` | `0.30` | Hybrid formula | yes |
| `RETRIEVAL_WEIGHT_METADATA` | `0.15` | Hybrid formula | yes |
| `TOP_K` | `12` | Retriever output size | yes |
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
Log these values on startup and expose via `/debug/routes` or diagnostics endpoints for operators.

## AH. Canonical normalization spec
- **Lowercasing:** apply NFC lowercase (Python `.casefold()`) before hashing or text comparisons.
- **Whitespace:** collapse all whitespace sequences into a single space and trim ends.
- **Punctuation stripping:** remove most punctuation except evidence IDs (e.g., `cv_snip_12`) and hyphenated technical terms; keep punctuation around numeric metrics for clarity.
- **Bullet normalization:** normalize bullet text to start with `- `; sort bullet lists alphabetically for diff hashing; deduplicate repeated bullets before comparing.
- **Evidence IDs:** preserve evidence IDs verbatim, include them in hash/diff calculations but exclude them from semantic similarity by temporarily masking them during token scoring.
- **Markdown/JSON cleanup:** remove markdown tables, code fences, and JSON braces; convert inline code (`` `code` ``) to plain text and treat braces as separators.
- **Document rendering exclusion:** ignore docx/pdf metadata (headers/footers) when computing diffs/hashes; only the normalized CV body is hashed.
- **Token comparison:** tokens inherit the normalization rules, ensuring repeated runs produce identical budgets regardless of formatting noise.
Apply these rules before computing `cv_hash`, `diff_ratio`, `token_budget_used`, or dedup checks.

## AI. Document rendering contract
- CV JSON (`cv_rewrite`) maps to DOCX/PDF sections as summary ? experience ? skills ? fit metrics; each bullet mentions the technologies/outcomes and includes the evidence ID parenthetically.
- Cover letters map to heading (`cover_letter.title`) and body paragraphs (split on double newline). Each paragraph cites at least one evidence ID in a footer; paragraphs lacking evidence are omitted.
- Filenames follow `documents/{request_id}/cv_{request_id}.docx`/`.pdf` and `cover_letter_{request_id}.docx`/`.pdf`; JSON contract stored as `artifacts/{request_id}/rewrite_contract.json`.
- Fallback outputs (`fallback_reason != none`) add a warning header “Fallback output: evidence limited” to rendered files; metadata embeds `fallback_reason`, `validator_failure_reason`, and `generation_timestamp`.
- If cover_letter is missing before fallback, validators block rendering until fallback supply one; if fallback still lacks evidence, a placeholder page notes the missing requirement but still saves the contract.
- Rendered files include YAML front matter with `schema_version`, `prompt_version`, `retrieval_version`, `validator_version`, and `threshold_version` so offline consumers know which config produced them.

## AJ. Reprocessing / migration policy
- Prompt version bumps keep existing artifacts readable but tag them `legacy_prompt=true`; re-running is optional unless manual review requests it.
- Schema version upgrades require revalidation; artifacts with older `schema_version` set `needs_revalidate=true` but remain accessible.
- Retrieval version increments log both the old and new values in `job_fit_scores`; reranking-only changes do not force regeneration.
- Validator version changes trigger lightweight revalidation on the next scheduler run; mismatches queue the artifact for manual review by setting `validator_version_mismatch=true`.
- Threshold version updates (diff, coverage, token budgets) mark artifacts with `threshold_version_mismatch=true`; regeneration is optional unless the delta is critical.
All legacy artifacts retain their original version tags plus a `legacy=true` flag to filter decisions.

## AK. Expanded worked examples
1. **Happy-path JSON** (concrete snippet)
   ```json
   {
     "quality_checks": {
       "cv_enhanced": true,
       "cover_letter_present": true,
       "unsupported_claims_found": [],
       "generic_phrases_found": [],
       "fallback_reason": "none",
       "validator_failure_reason": "none"
     },
     "cv_rewrite": {
       "summary": "Senior React engineer building offline experiences.",
       "experience_bullets": [
         "Designed React offline-sync architecture and IndexedDB caching (evidence: cv_snip_12).",
         "Implemented NodeJS APIs for PWA telemetry with TypeScript (evidence: cv_snip_25)."
       ],
       "skills_focus": ["React", "TypeScript", "NodeJS"]
     },
     "cover_letter": {
       "title": "Application for Senior React Engineer",
       "body": "Paragraph 1... Paragraph 2..."
     }
   }
   ```
2. **Unsupported-claim JSON**
   ```json
   {
     "quality_checks": {
       "cv_enhanced": false,
       "fallback_reason": "unsupported_claim",
       "validator_failure_reason": "validator_evidence_fail",
       "unsupported_claims_found": ["PWA resiliency"]
     }
   }
   ```
3. **State transition trace**
   ```
   received ? analyzed ? evidence_mapped ? planned ? generated ? retrying ? planned ? generated ? validated ? persisted
   ```
4. **Persistence record snapshot**
   - `job_generated_artifact_sets`: JSON contract, `cv_hash`, `idempotency_key`.
   - `job_generated_documents`: `documents/req123/cv_req123.docx`, cover letter path, render timestamps.
   - `job_detail_validations`: validation row with `validator_version=v1.3`, error taxonomy `unsupported_claim`.
   - `job_fit_scores`: row storing `score_semantic=0.82`, `token_budget_used=2150`, `latency_ms=10900`, `retrieval_version=v2.0`.
   - `job_state_transitions`: entries recording `received?analyzed` (intent classification) etc.
5. **Deterministic fallback cover letter**
   Title: "Fallback: React PWA Application"
   Body:
     Paragraph 1 cites `cv_snip_12` (offline resilience).
     Paragraph 2 references `cv_snip_19` (tooling requirement), paragraph 3 closes with `cv_snip_7` (company fit).\n   Omit any paragraph lacking evidence; keep total length =600 tokens.

## AL. Final closing review
- Consistency: terminology now unified (AF).
- Centralized constants: AG registry covers every threshold.
- Deterministic hashing/diff: AH normalization ensures reproducible hashes.
- Rendering: AI explains JSON?Doc/PDF and fallback handling.
- Versioning: AJ details prompt/schema/retrieval/validator/threshold migrations.
- Examples: AK provides happy-path, unsupported claim, state trace, persistence snapshot, fallback letter.

Remaining minor risks: fallback cover-letter tone may need refinement, and evidence ID normalization must stay consistent to avoid hash collisions.
"""
path.write_text(path.read_text(encoding='utf-8',errors='replace') + append, encoding='utf-8')
