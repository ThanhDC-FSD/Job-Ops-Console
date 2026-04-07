from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.database import Database
from app.repositories.learning_repository import LearningRepository
from app.repositories.meta_repository import MetaRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.learning_service import LearningService


def _parse_payload(raw_payload: str) -> dict:
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Learning ETL without queue.")
    parser.add_argument("--payload", default="", help="JSON payload string for learning ETL")
    parser.add_argument("--payload-path", default="", help="Path to JSON payload file")
    args = parser.parse_args()

    payload = {}
    if args.payload_path:
        payload_path = Path(args.payload_path)
        if not payload_path.is_absolute():
            payload_path = (PROJECT_ROOT / payload_path).resolve()
        if payload_path.exists():
            payload = _parse_payload(payload_path.read_text(encoding="utf-8", errors="ignore"))
    if not payload and args.payload:
        payload = _parse_payload(args.payload)

    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("seed_path", "learning_plan.md")

    db = Database()
    meta_repo = MetaRepository(db)
    meta_repo.ensure_app_tables(run_maintenance=False)
    service = LearningService(LearningRepository(db), ScheduleRepository(db))
    result = service.run_learning_etl(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
