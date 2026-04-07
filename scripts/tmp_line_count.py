from pathlib import Path
path=Path('docs/rag_workflow_v1.md')
data=path.read_text(encoding='utf-8', errors='replace')
print(len(data.splitlines()))
