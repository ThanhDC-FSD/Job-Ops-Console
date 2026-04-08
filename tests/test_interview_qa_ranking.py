import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.python.interview_qa.contracts import CandidateJob
from scripts.python.interview_qa.ranking import rank_question_bank, retrieve_evidence_chunks


class InterviewQaRankingTest(unittest.TestCase):
    def test_rank_question_bank_returns_bounded_results(self) -> None:
        job = CandidateJob(
            job_id=1,
            title="Backend Engineer",
            company="Example",
            location="Remote",
            jd_text="Build APIs, debug incidents, improve performance, and own backend delivery.",
            cv_text="Delivered FastAPI services, automation workflows, and performance tuning work.",
        )
        questions = rank_question_bank(job, top_k=6, out_n=4)
        self.assertGreaterEqual(len(questions), 1)
        self.assertLessEqual(len(questions), 4)
        self.assertTrue(all(item.question_id for item in questions))

    def test_retrieve_evidence_chunks_returns_grounded_chunks(self) -> None:
        job = CandidateJob(
            job_id=2,
            title="Full Stack Engineer",
            company="Example",
            location="Remote",
            jd_text="Need API design, testing, collaboration, and delivery under constraints.",
            cv_text="Built React UI, FastAPI APIs, and automation for release workflows.",
        )
        questions = rank_question_bank(job, top_k=4, out_n=3)
        chunks = retrieve_evidence_chunks(job, questions)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertTrue(all(chunk.chunk_id for chunk in chunks))
        self.assertTrue(all(chunk.source in {"jd", "cv"} for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
