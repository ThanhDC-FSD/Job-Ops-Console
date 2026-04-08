import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.python.interview_qa.schema import parse_json_message, validate_prediction_payload


class InterviewQaSchemaTest(unittest.TestCase):
    def test_parse_json_message_supports_openai_style_choices(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"qa":[{"question":"Q1","answer":"A1","evidence_ids":["jd_0"],"confidence":"HIGH"}]}'
                    }
                }
            ]
        }
        parsed = parse_json_message(payload)
        self.assertEqual(parsed["qa"][0]["question"], "Q1")

    def test_validate_prediction_payload_filters_invalid_fields(self) -> None:
        payload = {
            "qa": [
                {"question": "Q1", "answer": "A1", "evidence_ids": ["jd_0", "bad"], "confidence": "HIGH"},
                {"question": "Q1", "answer": "A2", "evidence_ids": ["cv_0"], "confidence": "low"},
                {"question": "", "answer": "A3", "evidence_ids": ["cv_0"], "confidence": "low"},
            ]
        }
        normalized = validate_prediction_payload(payload, valid_evidence_ids={"jd_0", "cv_0"})
        self.assertEqual(len(normalized["qa"]), 1)
        self.assertEqual(normalized["qa"][0]["evidence_ids"], ["jd_0"])
        self.assertEqual(normalized["qa"][0]["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
