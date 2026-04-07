from typing import List, Dict
from .embedding_service import simple_embedding
from .vector_index_manager import retrieve
from .config import RELEVANCE_THRESHOLD


def retrieve_top_k(query: str, top_k: int = 5, dim: int = 256, db_path: str = None) -> List[Dict]:
    """
    Return top_k retrieved segments for the query. Each item contains:
    - score: similarity score (float)
    - jd_id
    - segment_id
    - text_chunk
    """
    q_emb = simple_embedding(query, dim=dim)
    scored = retrieve(q_emb, top_k=top_k, db_path=db_path)
    results = []
    for score, row in scored:
        results.append({
            'score': float(score),
            'jd_id': row.get('jd_id'),
            'segment_id': row.get('segment_id'),
            'text_chunk': row.get('text_chunk')
        })
    return results


def compute_retrieval_metrics(results: List[Dict], relevance_threshold: float = RELEVANCE_THRESHOLD) -> Dict:
    """Compute retrieval diagnostics from a list of retrieve results (top_k order not required).
    Returns a dict with top1_score, avg_top_k_score, relevant_count, source_diversity, top_k.
    """
    scores = [r.get('score', 0.0) for r in results]
    top_k = len(scores)
    top1_score = max(scores) if scores else 0.0
    avg_top_k_score = (sum(scores) / top_k) if top_k > 0 else 0.0
    relevant_count = sum(1 for s in scores if s >= relevance_threshold)
    source_diversity = len(set(r.get('jd_id') for r in results)) if results else 0
    return {
        'top_k': top_k,
        'top1_score': float(top1_score),
        'avg_top_k_score': float(avg_top_k_score),
        'relevant_count': int(relevant_count),
        'source_diversity': int(source_diversity),
        'scores': scores
    }


def should_use_rag(metrics: Dict, *,
                   top1_min: float = None,
                   avg_min: float = None,
                   relevance_threshold: float = None,
                   min_relevant_count: int = None,
                   strict: bool = False,
                   strict_max_source_diversity: int = None) -> bool:
    """Decide whether to use RAG based on computed metrics and thresholds.
    If strict=True, apply stricter thresholds suitable for JD-specific queries.
    """
    from .config import TOP1_MIN, AVG_TOPK_MIN, MIN_RELEVANT_COUNT, RELEVANCE_THRESHOLD, STRICT_TOP1_MIN, STRICT_AVG_TOPK_MIN, STRICT_MIN_RELEVANT_COUNT, STRICT_MAX_SOURCE_DIVERSITY

    if relevance_threshold is None:
        relevance_threshold = RELEVANCE_THRESHOLD
    if top1_min is None:
        top1_min = STRICT_TOP1_MIN if strict else TOP1_MIN
    if avg_min is None:
        avg_min = STRICT_AVG_TOPK_MIN if strict else AVG_TOPK_MIN
    if min_relevant_count is None:
        min_relevant_count = STRICT_MIN_RELEVANT_COUNT if strict else MIN_RELEVANT_COUNT
    if strict_max_source_diversity is None:
        strict_max_source_diversity = STRICT_MAX_SOURCE_DIVERSITY

    top1 = metrics.get('top1_score', 0.0)
    avg = metrics.get('avg_top_k_score', 0.0)
    relevant_count = metrics.get('relevant_count', 0)
    source_div = metrics.get('source_diversity', 0)

    if top1 >= top1_min and avg >= avg_min and relevant_count >= min_relevant_count:
        if strict:
            # enforce source diversity limit
            return source_div <= (strict_max_source_diversity or 3)
        return True
    return False

