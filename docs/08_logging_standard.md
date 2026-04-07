# Logging Standard

This project uses a single log format across **FE, BE, Crawl, ETL, DB, and CICD** so runs can be audited and correlated quickly.

## Format (key=value, single-line)
```
ts=2026-03-20T08:30:12+07:00 level=INFO component=BE.API event=list_jobs run_id=20260320_083012 trace_id=- job_id=- message="List jobs | filters=... limit=200 offset=0"
```

## Required Fields
- `ts`: ISO timestamp with timezone offset.
- `level`: `DEBUG|INFO|WARNING|ERROR|CRITICAL`
- `component`: logical component name (ex: `BE.API`, `FE.ApplyCV`, `Crawl.LinkedIn`, `ETL.BackfillCV`, `DB.Backup`, `CICD.Release`)
- `event`: short machine-readable event key (ex: `open_modal_start`, `job_preview`, `fix_success`)
- `run_id`: run correlation id (ex: `20260320_083012`)
- `trace_id`: optional request/trace id or `-`
- `job_id`: optional job id or `-`
- `message`: human readable details (always present, quoted)

## Recommended Fields
- `duration_ms`, `status`, `error`, `count`, `page`, `offset`, `limit`

## Component Mapping
- **FE**: `apps/frontend/src/utils/logger.js`
- **BE**: `apps/backend/app/logging_setup.py`
- **Crawl**: `scripts/node/backfill_missing_jd_from_public_pages.js` or `scripts/python/linkedin_jobs_jd.py`
- **ETL**: `scripts/python/backfill_generated_cv_metadata.py`
- **DB**: `scripts/python/db_backup.py`
- **CICD**: `scripts/bat/run_local_bare_git_flow.bat`

## Usage Examples
```
ts=2026-03-20T08:31:44+07:00 level=INFO component=FE.ApplyCV event=open_modal_start run_id=20260320_083012 trace_id=- job_id=- message="selected_jobs=3"
ts=2026-03-20T08:31:52+07:00 level=ERROR component=ETL.BackfillCV event=sql_error run_id=20260320_083012 trace_id=- job_id=1074 message="no such column: cv_text"
```
