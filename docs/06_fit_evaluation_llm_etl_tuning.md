# Fit Evaluation LLM + ETL Tuning Plan

## Goal

Rebuild fit evaluation so it is:

- more accurate than the current keyword-only heuristic
- fast enough to run continuously inside ETL
- incremental, so unchanged jobs are not recomputed
- cheap enough that LLM is used only where it adds value
- structured enough to support SQLite-first storage and downstream CV generation

This document is intentionally high level. It is a working design note for implementation review.

## Current Bottlenecks

The current flow does several expensive things repeatedly:

1. Rebuilds JD text every time fit is evaluated.
2. Re-tokenizes JD and CV every time.
3. Computes fit directly from raw text without a canonical intermediate representation.
4. Uses separate logic for crawl, detail cleanup, fit scoring, CV generation, and preview.
5. Cannot clearly distinguish:
   - source changed
   - logic changed
   - prompt changed
   - model changed
6. Has no strong incremental cache boundary for fit evaluation.
7. If LLM is added naively to every JD/CV pair, runtime will explode.

## Core Idea

Turn the pipeline into a shared-data system:

1. Crawl raw payload once.
2. Normalize details once.
3. Build a compact feature cache once.
4. Compute a fast heuristic fit from cached features.
5. Call LLM only for selected cases.
6. Persist every stage into SQLite with source hashes and logic versions.

This makes ETL the primary place for expensive work, while UI becomes mostly read-only and on-demand materialization.

## Proposed Data Model

### 1. Raw Source Layer

Already present:

- `job_posts`
- `job_observations`
- `job_jd_contents`

These remain the truth for crawl history.

### 2. Canonical Detail Layer

Already moving in this direction:

- `job_detail_validations`

This layer should hold normalized values such as:

- posted time
- posted date
- applicant insight
- compensation
- work model
- employment type
- application status
- response note
- programming language

This is the cleaned job details layer used by all downstream steps.

### 3. Feature Cache Layer

Add two cache tables.

#### `job_fit_feature_cache`

One row per job.

Suggested fields:

- `job_post_id`
- `source_hash`
- `logic_version`
- `jd_summary`
- `jd_keywords_json`
- `matched_constraints_json`
- `programming_languages_json`
- `domain_terms_json`
- `technical_terms_json`
- `embedding_json`
- `updated_at`

Purpose:

- convert raw JD into compact reusable features
- avoid repeated tokenization and parsing
- provide a stable input for both heuristic and LLM fit scoring

#### `cv_profile_feature_cache`

One row per CV profile.

Suggested fields:

- `cv_profile`
- `cv_source_path`
- `source_hash`
- `logic_version`
- `cv_summary`
- `skills_json`
- `domain_terms_json`
- `technical_terms_json`
- `evidence_score`
- `embedding_json`
- `updated_at`

Purpose:

- reuse the same CV-derived features for all jobs
- avoid re-reading and re-tokenizing master CV files on every ETL run

Example SQLite table DDL for `cv_profile_feature_cache`:
```sql
CREATE TABLE IF NOT EXISTS cv_profile_feature_cache (
  cv_profile TEXT PRIMARY KEY,
  cv_source_path TEXT,
  source_hash TEXT NOT NULL,
  logic_version TEXT NOT NULL,
  cv_summary TEXT,
  skills_json TEXT,
  domain_terms_json TEXT,
  technical_terms_json TEXT,
  evidence_score REAL,
  embedding_json TEXT,
  updated_at TEXT NOT NULL
);
```

Example SQLite table DDL for `job_fit_feature_cache`:
```sql
CREATE TABLE IF NOT EXISTS job_fit_feature_cache (
  job_post_id INTEGER PRIMARY KEY,
  source_hash TEXT NOT NULL,
  logic_version TEXT NOT NULL,
  jd_summary TEXT,
  jd_keywords_json TEXT,
  matched_constraints_json TEXT,
  programming_languages_json TEXT,
  domain_terms_json TEXT,
  technical_terms_json TEXT,
  embedding_json TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_job_fit_feature_cache_hash ON job_fit_feature_cache(source_hash);
```

### 4. Scoring Layer

Extend `job_fit_scores` or add a second table for LLM-assisted results.

Recommended extra fields:

- `fit_source_hash`
- `fit_logic_version`
- `fit_backend`
- `fit_model`
- `heuristic_total_score`
- `heuristic_reason`
- `llm_total_score`
- `llm_status`
- `llm_reason`
- `llm_usage_json`
- `final_total_score`
- `final_status`
- `final_reason`
- `evaluated_at`

## Recommended Algorithm

Use a two-stage scorer.

### Stage A: Fast Heuristic Gate

For every changed job:

1. Load canonical job details.
2. Build or refresh `job_fit_feature_cache`.
3. Load or refresh `cv_profile_feature_cache`.
4. Compute fast heuristic fit:
   - keyword coverage
   - technical overlap
   - domain overlap
   - evidence quality
   - constraint match
   - embedding similarity

This stage should be deterministic and cheap.

### Stage B: Selective LLM Rerank

Only call LLM when heuristic output is uncertain or high impact.

Examples:

- score in a middle band such as `45..85`
- strong keyword match but weak evidence
- employment/work model conflict
- compensation or response note changes materially
- a job was previously near threshold and now changed

Do not call LLM for:

- obviously bad jobs
- obviously strong jobs
- unchanged jobs

This is the main performance workaround.

Selection pseudocode (developer-ready):
```
def should_call_llm(job_row, cv_row, fast_score, thresholds=(45,85)):
  if fast_score < thresholds[0]:
    return False, 'low'
  if fast_score > thresholds[1]:
    return False, 'high'
  # if constraints conflict or missing evidence
  if job_row.get('constraint_flag') or cv_row.get('evidence_score', 0) < 40:
    return True, 'borderline-evidence'
  # if job changed since last llm eval
  if job_row.get('source_hash') != job_row.get('last_llm_job_hash'):
    return True, 'job_changed'
  return False, 'default'
```

## LLM Input Strategy

Never send full raw JD + full CV to the model during ETL.

Send compact structured inputs:

```json
{
  "job": {
    "title": "...",
    "company": "...",
    "location": "...",
    "work_model": "...",
    "employment_type": "...",
    "application_status": "...",
    "jd_summary": "...",
    "keywords": ["...", "..."],
    "programming_languages": ["...", "..."],
    "constraints": ["remote", "part-time"]
  },
  "cv": {
    "profile": "full_doc_stlye",
    "summary": "...",
    "skills": ["...", "..."],
    "strengths": ["...", "..."],
    "evidence_score": 84.0
  },
  "heuristic": {
    "keyword_score": 71.2,
    "domain_score": 65.0,
    "technical_score": 78.0,
    "constraint_score": 100.0,
    "embedding_similarity": 0.63
  }
}
```

Required model output:

```json
{
  "fit_score": 0,
  "status": "ready_to_apply|needs_review|not_compatible",
  "reason": "",
  "main_issue": "",
  "strengths": [],
  "gaps": []
}
```

This keeps latency and token usage much lower than full-text prompting.

## Shared Hash Strategy

Every stage should use a stable hash key.

### Job feature hash

Built from:

- latest JD text
- normalized detail values
- logic version

### CV feature hash

Built from:

- CV file content
- profile name
- logic version

### Fit source hash

Built from:

- job feature hash
- CV feature hash
- scoring logic version
- selected model name

This gives precise incremental invalidation.

Hash example (Python):
```
import hashlib
def make_hash(*parts: str) -> str:
  h = hashlib.sha256()
  for p in parts:
    h.update((p or '').encode('utf-8'))
    h.update(b'|')
  return h.hexdigest()

fit_source_hash = make_hash(job_feature_hash, cv_feature_hash, scoring_logic_version, selected_model)
```

## Performance-Oriented Data Structures

### 1. Feature Cache Tables

The main performance structure is not a complex tree or graph. It is a persistent cache keyed by source hash.

That is the right tradeoff for this project because:

- SQLite is already the central store
- the workload is incremental ETL, not online search at huge scale
- correctness and reproducibility matter more than theoretical asymptotic gains

### 2. Embedding Cache

Store embeddings once and reuse them.

Possible structures:

- one dense vector per job summary
- one dense vector per CV profile
- optional chunk embeddings for long JDs

Use cosine similarity for cheap reranking before LLM.

### 3. Work Queue

Add a lightweight queue table if ETL gets too large.

Example:

- `fit_evaluation_queue(job_post_id, priority, reason, enqueued_at, started_at, finished_at, status)`

This lets ETL enqueue work and a background worker process jobs in batches.

Suggested queue table DDL:
```sql
CREATE TABLE IF NOT EXISTS fit_evaluation_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_post_id INTEGER NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50,
  reason TEXT,
  enqueued_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'queued'
);
CREATE INDEX IF NOT EXISTS ix_fit_queue_job_post ON fit_evaluation_queue(job_post_id);
```

## ETL Flow After Redesign

Recommended ETL order:

1. `crawl raw payload`
2. `upsert job_posts / observations / jd_contents`
3. `normalize details -> job_detail_validations`
4. `build or refresh job_fit_feature_cache`
5. `build or refresh cv_profile_feature_cache`
6. `compute heuristic fit for changed jobs`
7. `enqueue borderline jobs for llm rerank`
8. `persist final fit into job_fit_scores`
9. `materialize files only on demand from UI`

This means ETL computes knowledge, while file generation remains lazy.

Lightweight worker loop (pseudo):
```
while True:
  item = dequeue_next()
  if not item:
    sleep(1)
    continue
  mark_started(item)
  job = load_job(item.job_post_id)
  compute_and_persist_llm_rerank(job)
  mark_finished(item)
```

## Model Strategy

### Fast path

- heuristics + embedding similarity only

### Slow path

- small local model via Ollama
- structured JSON output
- only for selected jobs

Recommended local model role split:

- detail validation: smallest instruct model available
- fit rerank: slightly larger instruct model, but only for borderline cases

Do not use the same full prompt flow for:

- detail validation
- fit evaluation
- CV rewrite

Each task should have its own compact prompt and its own cache boundary.

## SQLite Tuning

For batch ETL, use:

- WAL mode
- `busy_timeout`
- explicit chunk commits
- batched updates

Practical batch strategy:

- commit every `50` or `100` jobs
- keep a progress marker
- resume from the last unfinished batch

This reduces:

- long write locks
- all-or-nothing reruns
- risk from interrupted long jobs

## Suggested Scoring Formula

Use a blended score before LLM:

```text
fast_score =
  0.25 * keyword_score +
  0.20 * technical_score +
  0.15 * domain_score +
  0.15 * evidence_score +
  0.15 * constraint_score +
  0.10 * embedding_similarity_scaled
```

Then let LLM refine only if:

```text
45 <= fast_score <= 85
```

or if there is a contradiction between:

- heuristics
- normalized details
- prior fit result

Final score:

```text
final_score =
  fast_score                    if no llm rerank
  0.65 * fast_score + 0.35 * llm_score   if llm rerank used
```

This keeps the system stable and avoids LLM over-control.

## Implementation Plan

### Phase 1

- add `logic_version` hashing everywhere
- add `job_fit_feature_cache`
- add `cv_profile_feature_cache`
- keep current heuristic scorer but read from cache

### Phase 2

- add embedding similarity to the fast score
- store compact summaries and explicit feature lists in SQLite

### Phase 3

- add selective LLM rerank for borderline jobs only
- persist `fit_backend`, `fit_model`, `llm_reason`, `llm_usage_json`

### Phase 4

- move fit evaluation into queue-based ETL if runtime still grows

## Immediate Workaround

Before full redesign is complete, the practical workaround is:

1. keep heuristic fit as the default batch scorer
2. cache JD and CV features in SQLite
3. call LLM only for borderline jobs
4. recompute only when source hash or logic version changes

This gives most of the benefit without turning ETL into a slow all-LLM pipeline.

## Open Questions

- Should fit be per master CV profile only, or per generated CV version too?
- Should embeddings be stored as JSON arrays or compact hashed vectors only?
- Is the final UI threshold based on `final_score` only, or should we also expose `fast_score` and `llm_score` separately?
- Should the queue be synchronous inside ETL first, then moved to background worker later?

## Recommendation

Do not implement LLM fit evaluation as a direct replacement for the current heuristic scorer.

Implement it as:

- `heuristic first`
- `feature cache always`
- `embedding rerank second`
- `LLM only for selected cases`

That is the most realistic path to higher accuracy without breaking runtime.
