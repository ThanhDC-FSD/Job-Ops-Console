# -*- coding: utf-8 -*-
from pathlib import Path
path = Path('docs/rag_workflow_v1.md')
append = """
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
"""
path.write_text(path.read_text(encoding='utf-8',errors='replace') + append, encoding='utf-8')
