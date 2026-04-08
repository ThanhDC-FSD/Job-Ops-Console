from __future__ import annotations

from .contracts import CandidateJob, EvidenceChunk, RankedQuestion


def build_generation_prompt(
    job: CandidateJob,
    questions: list[RankedQuestion],
    evidence_chunks: list[EvidenceChunk],
) -> str:
    """Build a compact evidence-linked prompt for the generation pass."""
    evidence_lines = []
    for chunk in evidence_chunks:
        evidence_lines.append(f"[{chunk.chunk_id}] ({chunk.source}) {chunk.text[:500]}")
    question_lines = [f"- {item.question}" for item in questions]
    return (
        "Return JSON only with shape "
        "{\"qa\":[{\"question\":\"...\",\"answer\":\"...\",\"evidence_ids\":[\"jd_0\"],\"confidence\":\"high|medium|low\"}]}"
        "\nUse only the evidence below and never invent experience not present in CV or JD.\n\n"
        f"ROLE:\nTitle: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n\n"
        "SHORTLISTED_QUESTIONS:\n"
        + "\n".join(question_lines)
        + "\n\nEVIDENCE:\n"
        + "\n".join(evidence_lines)
    )


def build_vet_prompt(generated: dict[str, object], evidence_chunks: list[EvidenceChunk]) -> str:
    """Build a second-pass prompt that removes unsupported claims."""
    evidence_lines = [f"[{chunk.chunk_id}] {chunk.text[:500]}" for chunk in evidence_chunks]
    return (
        "Review the generated interview Q&A. Return JSON only with the same shape. "
        "Remove unsupported claims, keep evidence_ids valid, and lower confidence when evidence is weak.\n\n"
        f"CANDIDATE_QA:\n{generated}\n\n"
        "EVIDENCE:\n"
        + "\n".join(evidence_lines)
    )
