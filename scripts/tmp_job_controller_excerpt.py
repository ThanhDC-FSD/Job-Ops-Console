import pathlib
path=pathlib.Path('apps/backend/app/controllers/job_controller.py')
with path.open(encoding='utf-8',errors='ignore') as f:
    lines=f.readlines()
for i,line in enumerate(lines[40:120],start=41):
    print(f"{i}: {line.rstrip()}")
