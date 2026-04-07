from pathlib import Path
path=Path('apps/backend/app/services/cv_rewrite_service.py')
print('size',path.stat().st_size)
