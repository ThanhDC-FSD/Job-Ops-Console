import re
from typing import List

def token_set(text: str) -> set:
    return set(re.findall(r"\w+", (text or "").lower()))

def grounding_score(answer: str, retrieved_chunks: List[str]) -> float:
    """Estimate grounding by overlap between answer tokens and retrieved context tokens."""
    if not answer:
        return 0.0
    ans_t = token_set(answer)
    ctx_t = set()
    for c in retrieved_chunks:
        ctx_t.update(token_set(c))
    if not ctx_t:
        return 0.0
    overlap = len(ans_t & ctx_t) / max(1, len(ans_t))
    return float(overlap)

def extraction_completeness(extracted: dict, required_fields: List[str]) -> float:
    if not extracted:
        return 0.0
    found = sum(1 for f in required_fields if extracted.get(f))
    return float(found) / max(1, len(required_fields))
