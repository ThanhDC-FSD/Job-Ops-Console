import json
import sqlite3
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.python.interview_qa.contracts import CandidateJob
from scripts.python.interview_qa.runner import _predict_job
from scripts.python.interview_qa.storage import JsonlLogger


class InterviewQaRunnerTest(unittest.TestCase):
    def test_predict_job_persists_filtered_result(self) -> None:
        job = CandidateJob(
            job_id=99,
            title="Software Engineer",
            company="Example",
            location="Remote",
            jd_text="Need automation, API design, debugging, and testing experience.",
            cv_text="Built FastAPI services, automation pipelines, and debugging workflows.",
        )
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v BLOB, ts INTEGER)")
        output_dir = ROOT / "tmp_tests" / "runner_case"
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        logger = JsonlLogger(output_dir / "events.jsonl")
        try:
            with patch("scripts.python.interview_qa.runner.chat_backend") as mocked_chat:
                mocked_chat.return_value = {
                    "message": {
                        "content": json.dumps(
                            {
                                "qa": [
                                    {
                                        "question": "What automation story fits this role?",
                                        "answer": "I built automation workflows for delivery and debugging.",
                                        "evidence_ids": ["jd_0", "bad_id"],
                                        "confidence": "HIGH",
                                    }
                                ]
                            }
                        )
                    },
                    "prompt_eval_count": 12,
                    "eval_count": 34,
                }
                with patch("scripts.python.interview_qa.runner.TUNING_PREDICT_QA_USE_VET_PASS", False):
                    result = _predict_job(job, cache_conn=conn, output_dir=output_dir, logger=logger)
        finally:
            logger.close()
            conn.close()

        self.assertEqual(len(result["qa"]), 1)
        self.assertEqual(result["qa"][0]["confidence"], "high")
        self.assertEqual(result["qa"][0]["evidence_ids"], ["jd_0"])
        saved = json.loads((output_dir / "job_99.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["qa"][0]["evidence_ids"], ["jd_0"])
        shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
