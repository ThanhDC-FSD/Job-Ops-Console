# Project Structure Map

## 1) Folder layout

```text
2.automate_updating_CV/
|-- apps/
|   |-- backend/
|   |   |-- app/
|   |   |   |-- controllers/
|   |   |   |-- services/
|   |   |   |-- repositories/
|   |   |   |-- schemas/
|   |   |   `-- main.py
|   |   `-- tests/
|   `-- frontend/
|       `-- src/
|-- scripts/
|   |-- bat/
|   |   |-- run_linkedin_jobs_jd.bat
|   |   |-- run_linkedin_jobs_applied_tracker.bat
|   |   |-- run_job_ops_backend.bat
|   |   `-- run_job_ops_frontend.bat
|   |   |-- render_cv_docx.bat
|   |   `-- render_cv_electic_docx.bat
|   `-- python/
|       |-- linkedin_jobs_jd.py
|       |-- linkedin_jobs_applied_tracker.py
|       |-- render_cv_docx.py
|       |-- evaluate_cv_fit.py
|       `-- technical_skill_groups.py
|-- input/
|-- documents/
|-- .venv/
`-- PROJECT_STRUCTURE.md
```

## 2) Entry points (you run these)

- `scripts/bat/run_linkedin_jobs_jd.bat`
- `scripts/bat/run_linkedin_jobs_applied_tracker.bat`
- `scripts/bat/run_job_ops_backend.bat`
- `scripts/bat/run_job_ops_frontend.bat`
- `scripts/bat/render_cv_docx.bat`
- `scripts/bat/render_cv_electic_docx.bat`

All `.bat` files now:
- Resolve `PROJECT_ROOT` automatically
- Use Python at `.venv/Scripts/python.exe`
- Call Python scripts in `scripts/python/`
- Execute from project root so relative `input/` and `documents/` paths remain stable

## 3) Call map (file -> file)

- `scripts/bat/run_linkedin_jobs_jd.bat` -> `scripts/python/linkedin_jobs_jd.py`
- `scripts/bat/run_linkedin_jobs_applied_tracker.bat` -> `scripts/python/linkedin_jobs_applied_tracker.py`
- `scripts/bat/run_job_ops_backend.bat` -> `apps/backend/app/main.py`
- `scripts/bat/run_job_ops_frontend.bat` -> `apps/frontend/src/App.jsx`
- `scripts/bat/render_cv_docx.bat` -> `scripts/python/render_cv_docx.py`
- `scripts/bat/render_cv_electic_docx.bat` -> `scripts/python/render_cv_docx.py`
- `scripts/python/render_cv_docx.py` -> imports `scripts/python/technical_skill_groups.py`
- `scripts/python/linkedin_jobs_applied_tracker.py` -> imports helpers from `scripts/python/linkedin_jobs_jd.py`

## 4) Data/output map

- `scripts/python/linkedin_jobs_jd.py`
  - Reads from LinkedIn URL / optional input JSON
  - Writes `output-json`, `output-csv`
  - Writes SQLite DB (default: `input/crawled_job/linkedin_jobs_jd.sqlite`)

- `scripts/python/render_cv_docx.py`
  - Reads from `input/*.txt`
  - Writes to `documents/*.docx` and optional `documents/*.pdf`

- `scripts/python/evaluate_cv_fit.py`
  - Reads JD + CV text inputs
  - Writes fit report markdown

## 5) Run examples

- Crawl LinkedIn jobs:
  - `scripts\bat\run_linkedin_jobs_jd.bat --max-jobs 20`

- Render CV (default profile):
  - `scripts\bat\render_cv_docx.bat`

- Render CV (electric profile):
  - `scripts\bat\render_cv_electic_docx.bat`
