import pathlib
path=pathlib.Path('apps/backend/app/repositories/job_repository.py')
with path.open(encoding='utf-8',errors='ignore') as f:
    lines=f.readlines()
for i,line in enumerate(lines[1870:2040],start=1871):
    print(f"{i}: {line.rstrip()}" )
