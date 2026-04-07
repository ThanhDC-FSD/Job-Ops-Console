from typing import Dict, Any
from .retriever import retrieve_top_k, compute_retrieval_metrics, should_use_rag
from .rag_generator import generate_rag_answer
from .llm_reasoner import reason_with_llm
from .config import TOP_K_DEFAULT


def route_query(query: str, *, top_k: int = TOP_K_DEFAULT, db_path: str = None, jd_specific: bool = False, overrides: Dict[str, Any] = None) -> Dict[str, Any]:
    """Route a query to RAG or LLM using a top-k retrieval evaluation layer.

    Returns a dict containing decision diagnostics and the answer.
    """
    overrides = overrides or {}
    retrieved = retrieve_top_k(query, top_k=top_k, db_path=db_path)
    if overrides.get('relevance_threshold') is not None:
        metrics = compute_retrieval_metrics(retrieved, relevance_threshold=overrides.get('relevance_threshold'))
    else:
        metrics = compute_retrieval_metrics(retrieved)
    strict = bool(jd_specific or overrides.get('strict'))
    use_rag = should_use_rag(metrics,
                            top1_min=overrides.get('top1_min'),
                            avg_min=overrides.get('avg_min'),
                            relevance_threshold=overrides.get('relevance_threshold'),
                            min_relevant_count=overrides.get('min_relevant_count'),
                            strict=strict,
                            strict_max_source_diversity=overrides.get('strict_max_source_diversity'))

    if use_rag:
        answer = generate_rag_answer(query, retrieved)
        return {
            'mode': 'rag',
            'metrics': metrics,
            'route': 'rag',
            'answer': answer,
            'retrieved': retrieved
        }

    # LLM fallback
    res = reason_with_llm(query, db_path=db_path)
    return {
        'mode': 'llm',
        'metrics': metrics,
        'route': 'llm',
        'answer': res.get('answer'),
        'structured': res.get('structured')
    }
