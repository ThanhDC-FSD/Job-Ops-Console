# Job Ops (BE + FE)

## Ports
- Backend API: `8101`
- Frontend UI: `5180`

## Backend architecture
- `apps/backend/app/repositories`: SQL access layer
- `apps/backend/app/services`: business logic layer
- `apps/backend/app/controllers`: API layer

## Start backend
```bat
scripts\bat\run_job_ops_backend.bat
```

## Start frontend
```bat
scripts\bat\run_job_ops_frontend.bat
```

## Main API endpoints
- `GET /health`
- `GET /api/dashboard`
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `GET /api/analytics/reposts`
- `GET /api/analytics/countries-overview`
- `GET /api/schedules`
- `POST /api/schedules`
- `PATCH /api/schedules/{id}`
- `GET /api/runs`
- `POST /api/actions/trigger`
- `POST /api/fit/evaluate`

## Manual tests run
- Backend smoke tests: `3 passed`
- Frontend production build: `vite build` success
- API smoke with real DB: health/dashboard/analytics successful
