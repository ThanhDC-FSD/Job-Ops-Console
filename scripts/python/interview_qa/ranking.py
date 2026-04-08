from __future__ import annotations

from app.services.text_vector_utils import build_hashed_embedding, cosine_similarity, split_text_chunks

from .contracts import CandidateJob, EvidenceChunk, RankedQuestion
from .question_bank import QUESTION_BANK


def rank_question_bank(job: CandidateJob, *, top_k: int, out_n: int) -> list[RankedQuestion]:
    """Use cheap hashed embeddings to shortlist relevant interview question themes."""
    query_text = "\n".join([job.title, job.company, job.jd_text[:4000], job.cv_text[:2500]]).strip()
    query_vec = build_hashed_embedding(query_text)
    ranked: list[RankedQuestion] = []
    for item in QUESTION_BANK:
        score = cosine_similarity(query_vec, build_hashed_embedding(item["question"]))
        ranked.append(RankedQuestion(question_id=item["id"], question=item["question"], score=score))
    ranked.sort(key=lambda pair: pair.score, reverse=True)
    return ranked[: max(1, min(max(1, top_k), max(1, out_n), len(ranked)))]


def retrieve_evidence_chunks(job: CandidateJob, questions: list[RankedQuestion]) -> list[EvidenceChunk]:
    """Retrieve a compact set of grounding chunks from JD and CV text."""
    chunks: list[EvidenceChunk] = []
    for source_name, text in [("jd", job.jd_text), ("cv", job.cv_text)]:
        for idx, chunk in enumerate(split_text_chunks(text, max_chars=700, overlap_chars=100)):
            if chunk.strip():
                chunks.append(EvidenceChunk(chunk_id=f"{source_name}_{idx}", source=source_name, text=chunk))
    if not chunks:
        return []
    selected: list[EvidenceChunk] = []
    seen_chunk_ids: set[str] = set()
    for question in questions:
        qvec = build_hashed_embedding(question.question)
        ranked = sorted(
            (
                (cosine_similarity(qvec, build_hashed_embedding(chunk.text)), chunk)
                for chunk in chunks
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for score, chunk in ranked[:3]:
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            selected.append(
                EvidenceChunk(
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    text=chunk.text,
                    score=score,
                    question_id=question.question_id,
                )
            )
    return selected
