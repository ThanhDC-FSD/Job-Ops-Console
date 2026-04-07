from pathlib import Path
text=Path('scripts/python/linkedin_jobs_jd.py').read_text(encoding='utf-8',errors='ignore')
print(text[-4000:])
