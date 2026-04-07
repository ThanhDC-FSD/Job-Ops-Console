# Learning + Quiz Architecture

## System Fit Analysis

### Reused modules
- `learning_plan.md` as the initial bilingual seed source.
- `MetaRepository.ensure_app_tables()` for non-destructive schema extension.
- `Database` SQLite access layer and WAL settings.
- `text_vector_utils.py` for chunking and hashed embeddings.
- `ScheduleRepository` + `SchedulerRuntime` for scheduling and queue execution.
- Existing React app shell and API client for the new quiz page.

### Extended modules
- Backend app startup now seeds learning data from `learning_plan.md`.
- Scheduler runtime now supports queue-backed `learning_etl` jobs without changing existing automation schedules.
- Schedule repository now stores generic `schedule_jobs` and `schedule_queue`.
- Frontend now includes a quiz tab and queue/status visibility.

### Added modules
- `LearningRepository` for learning content, distractors, quiz attempts.
- `LearningService` for markdown parsing, ETL, dedup, distractor caching, quiz generation, queue processing.
- `learning_controller.py` for `/api/learning/*` and queue/schedule endpoints.
- `run_learning_etl.py` for scriptable ETL execution.

## Architecture Diagrams

### Data Flow
```text
learning_plan.md
  -> LearningService parser
  -> normalize bilingual Q&A
  -> dedup hash + optional similarity-ready embedding
  -> learning_* tables
  -> chunking + hashed embeddings
  -> distractor cache
  -> quiz API / future crawl merge
```

### Runtime Quiz Flow
```text
Frontend quiz tab
  -> GET /api/learning/topics
  -> GET /api/learning/quiz?topic_key=...
  -> LearningService fetches topic/questions
  -> cached distractors + shuffled choices
  -> user submits answers
  -> POST /api/learning/quiz/submit
  -> scoring + explanation + history persistence
  -> response to UI
```

### Scheduler Flow
```mermaid
flowchart TD
    A[User/API: schedule learning ETL] --> B[Insert schedule_jobs]
    B --> C[APScheduler cron]
    C --> D[Queue enqueue schedule_queue (pending)]
    D -->|claim one at a time| E[Queue processor learning_queue_processor]
    E --> F[LearningService.run_learning_etl]
    F --> G[Seed import from learning_plan.md]
    F --> H[Future daily crawl hook]
    G --> I[learning_* tables + embeddings + distractors]
    H --> I
    E --> J[Update schedule_queue status/logs]
    style E fill:#e3f2fd,stroke:#2196f3,stroke-width:1px
```

Queue processor runs one job type at a time; schedule_queue is generic (supports `learning_etl` and other crawl/ETL jobs). A default learning job is created and enqueued if none exist, so queue is never empty by mistake. This avoids overlapping ETL/crawl runs even when cron/manual triggers collide.

## Data Model

### Required tables
- `learning_topics`
  Stores bilingual topic labels and ordering.
- `learning_questions`
  Stores bilingual question/answer/explanation content, source link, dedup hash, base embedding.
- `learning_answers`
  Stores correct answers in structured form for quiz evaluation.
- `distractors`
  Stores cached wrong answers, generated once and reused.
- `learning_sources`
  Tracks content origin such as `seed_md`, future crawl sources, or generated sources.
- `quiz_attempts`
  Stores quiz summary per submission.
- `quiz_attempt_items`
  Stores per-question user choice, correctness, and explanation snapshot.
- `schedule_jobs`
  Stores queue-backed job definitions for learning ETL schedules.
- `schedule_queue`
  Stores queue instances with `pending`, `running`, `completed`, `failed`.

### Extra table
- `learning_question_chunks`
  Stores chunk text + hashed embedding per question for retrieval and similarity expansion.

## Deduplication Strategy

- Primary hash:
  `sha256(normalized(topic_id + question_en/question_vi))`
- Content hash:
  `sha256(question + answer + explanation bilingual payload)`
- Optional similarity layer:
  compare hashed embeddings from `text_vector_utils.cosine_similarity`.
- ETL behavior:
  skip exact duplicates by `question_hash`; update existing rows when content hash changes.

## API Design

- `GET /api/learning/topics`
- `GET /api/learning/quiz`
- `POST /api/learning/quiz`
- `POST /api/learning/quiz/submit`
- `GET /api/learning/quiz/history`
- `POST /api/automation/learning-etl/schedule`
- `GET /api/automation/queue`

## Frontend Design

- New tab inside the existing app shell: `Learning Quiz`
- Features:
  topic selector, bilingual rendering via current app language, 5-question quiz launch, answer selection, score summary, explanation review, history table, queue table.
- Current implementation keeps the UI lightweight for CPU-only / low-RAM hardware:
  no extra route framework, no heavy animation, no client-side embedding work.
- Queue visibility and scheduling controls live in the Automation tab to align with other pipelines and keep ETL runs serialized.

## Scheduler + Queue Design

- Queue states:
  `pending`, `running`, `completed`, `failed`
- Collision avoidance:
  queue processor claims only one `learning_etl` item at a time.
- Retry:
  failed items return to `pending` until `attempts >= max_attempts`, then become `failed`.
- Logging:
  learning service logs import and queue execution summaries through existing backend logging.

## Implementation Order

1. Inspect current app structure and reuse points.
2. Parse `learning_plan.md` first and seed the DB.
3. Extend schema for learning, quiz, and queue.
4. Integrate chunking + embedding into ETL.
5. Add distractor cache generation.
6. Add quiz APIs.
7. Add frontend quiz UI.
8. Add queue-backed scheduler support.
9. Update docs and smoke tests.

## Deployment Status (current branch)
- Seed ETL from `learning_plan.md` runs at backend startup and via `scripts/python/run_learning_etl.py`.
- Quiz APIs live: `/api/learning/topics`, `/api/learning/quiz`, `/api/learning/quiz/submit`, `/api/learning/quiz/history`.
- Queue-backed learning ETL live: schedule with `/api/automation/learning-etl/schedule`, queue visible at `/api/automation/queue`, processed by `learning_queue_processor` (one job at a time).
- Frontend built with a Learning tab (quiz) and Automation tab showing the learning queue and enqueue button.
- Dedup, chunking, hashed embeddings, and distractor cache are in place for the seed source; external crawl hook remains a future integration.
## Weak Hardware Notes

- Uses cached distractors instead of recomputing on each quiz request.
- Uses hashed embeddings instead of large model inference.
- Seeds from markdown locally and avoids network dependency.
- Queue processor runs single-threaded for `learning_etl` to reduce collision and RAM pressure.

## Current Scope Notes

- Seed import from `learning_plan.md` is fully wired and immediately usable.
- Daily external Q&A crawl is scaffolded through the queue/job system, but the actual remote content collector remains a hook for future integration.
