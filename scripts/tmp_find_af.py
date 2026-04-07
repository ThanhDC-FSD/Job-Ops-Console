from pathlib import Path
text=Path('docs/rag_workflow_v1.md').read_text(encoding='utf-8',errors='replace')
start=text.find('## AF. Consistency cleanup')
print('AF start', start)
start2=text.find('## AF. Consistency cleanup', start+1)
print('AF second', start2)
