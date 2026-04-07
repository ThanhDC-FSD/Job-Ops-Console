from pathlib import Path
path = Path('docs/rag_workflow_v1.md')
text = path.read_text(encoding='utf-8',errors='replace')
append = "\n## AF. Consistency cleanup\n..."
path.write_text(text + append, encoding='utf-8')
