from pathlib import Path
text=Path('docs/rag_workflow_v1.md').read_text(encoding='utf-8',errors='replace')
start=text.index('## R. Strict Json schema details'.replace('Json','JSON'))
print(start)
print(text[start:start+1000])
