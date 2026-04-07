import pathlib
path=pathlib.Path('apps/backend/app/services/job_service.py')
with path.open(encoding='utf-8',errors='ignore') as f:
    lines=f.readlines()
for i,line in enumerate(lines[500:560],start=501):
    print(f"{i}: {line.rstrip()}")
