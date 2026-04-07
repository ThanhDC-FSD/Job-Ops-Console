## Purpose

Ensure every implementation in this repository is safe, performance-aware, and continuously improves the system without breaking existing behavior.

This file defines mandatory rules for all changes.

---

## Core Rule

Before making ANY change:

* Preserve all existing business logic
* Do NOT remove or break current workflows
* Do NOT redesign the system unless explicitly requested

All changes must be incremental and backward-compatible.

---

## Mandatory Performance Rule

Every implementation MUST:

1. **Check performance impact**
2. **Tune performance if possible**
3. **Avoid making performance worse**

This is REQUIRED for every task.

---

## What Must Be Evaluated

After each implementation, you MUST evaluate:

### Latency

* user-facing response time
* LLM call time
* hot path execution time

### Compute

* repeated work (chunking, embedding, parsing)
* unnecessary processing
* redundant DB or file operations

### Prompt Efficiency

* prompt size
* irrelevant context included
* output verbosity

### Stability

* local LLM gateway reliability
* timeout / retry behavior
* SQLite I/O / locking risks
* queue blocking or long-running tasks

---

## Required Tuning Actions

When possible, you MUST apply safe optimizations:

* reduce duplicate work
* add caching where safe
* reduce prompt size
* trim low-signal context
* move non-critical work out of hot paths
* precompute reusable data
* avoid unnecessary synchronous steps
* improve logging and observability

Do NOT introduce risky or large redesigns.

---

## Hot Path Rule

User-facing flows MUST be kept fast.

Do NOT leave these in hot paths unless necessary:

* heavy file rendering (docx/pdf)
* repeated chunking / embedding
* large prompt assembly from raw text
* optional LLM calls
* unnecessary DB writes

If they remain, you MUST explain why.

---

## LLM Rule

For any LLM usage:

* keep prompt concise and structured
* avoid injecting full raw text unnecessarily
* preserve output format
* reduce token usage where possible
* keep fallback behavior intact

---

## Required Documentation Update

After EVERY implementation, you MUST update:

* `docs/10.1_current_system_explanation.md`
* `docs/10.1_current_system_explanation.mmd`

These files must reflect the **current system AFTER your changes**.

---

## Required End-of-Task Output

You MUST provide:

1. What was changed
2. What was preserved
3. Performance impact (measured or estimated)
4. What was optimized
5. Remaining bottlenecks
6. What should be tuned next

---

## Prohibited

DO NOT:

* remove existing business logic
* break APIs or flows
* skip performance evaluation
* skip documentation update
* claim optimization without justification
* use Vietnamese text in code (identifiers, strings, comments)

---

## Git Safety Rule

When staging or committing changes:

* Never add `.env`
* Never add CV or personal data files
* Never add sensitive user artifacts such as `.docx`, `.pdf`, or `.txt` files that contain CV or private content
* Prefer committing only source, docs, and intentional configuration changes
* If an ignored file must be reviewed, inspect it explicitly before deciding whether it is safe

## Database Snapshot Rule

When a commit includes SQLite or DB-related changes:

* Create a timestamped SQL snapshot named `db_snapshot_<timestamp>.sql` before committing
* Keep the snapshot aligned with the committed code state
* Do not use the snapshot as a replacement for schema or migration files
* Do not snapshot raw CV or personal content unless it is explicitly required and already approved as safe

---

## Default Priority

Always optimize in this order:

1. user-facing latency
2. prompt efficiency
3. duplicate work reduction
4. LLM stability
5. queue and batch control
6. storage / I/O safety

---

## Final Rule

Every change must leave the system:

* faster OR more efficient
* more observable
* and correctly documented

No task is complete without performance validation and updated docs.
