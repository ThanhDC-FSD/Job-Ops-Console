import pathlib
path=pathlib.Path('apps/backend/app/main.py')
with path.open(encoding='utf-8',errors='ignore') as f:
    for i,line in enumerate(f.readlines()[:200],start=1):
        print(f"{i}: {line.rstrip()}")
