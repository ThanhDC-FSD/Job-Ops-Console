import time
import os
import random
from typing import List, Dict
from tmp_seek_automation.rag import retriever
from tmp_seek_automation.rag import rag_generator
from tmp_seek_automation.integrations.agent import LocalAgent
from tmp_seek_automation.rag.sqlite_repository import ensure_connection, list_jds, insert_feedback
from tmp_seek_automation.benchmarks.quality_scorer import grounding_score

DEFAULT_TOP_K = 5

def build_query_sets(jds: List[Dict], n_per_group: int = 10) -> Dict[str, List[str]]:
    specific = []
    skills = []
    requirements = []
    summary = []
    for jd in jds[: max(100, n_per_group*5)]:
        title = jd.get('title') or jd.get('jobTitle') or jd.get('position') or ''
        content = jd.get('content') or {}
        sections = content.get('sections') if isinstance(content, dict) else content
        text = '\n'.join(sections) if isinstance(sections, list) else str(sections or '')
        if title:
            specific.append(f"What are the main responsibilities for the {title} role?")
        # attempt to extract skill-like tokens
        words = text.split()
        if words:
            w = words[0:5]
            skills.append(f"Which skills are required for roles that mention { ' '.join(w) }?")
        requirements.append(f"List the requirements from this job: { (title or 'job') }")
        summary.append(f"Summarize the following job posting: { (title or 'job') }")
    # sample
    return {
        'specific': random.sample(specific, min(len(specific), n_per_group)) if specific else [],
        'skills': random.sample(skills, min(len(skills), n_per_group)) if skills else [],
        'requirements': random.sample(requirements, min(len(requirements), n_per_group)) if requirements else [],
        'summary': random.sample(summary, min(len(summary), n_per_group)) if summary else []
    }

def run_query_benchmark(queries: List[str], agent: LocalAgent = None, top_k: int = DEFAULT_TOP_K, mode: str = 'auto') -> Dict:
    """
    Run queries with mode:
      - 'auto': use routing logic (default)
      - 'llm': always call LLM directly
      - 'rag': always use RAG generator
      - 'rag_feedback': use RAG and persist feedback for some answers
    Returns detailed per-query metrics and summary counts.
    """
    conn = ensure_connection()
    agent = agent or LocalAgent('query-bench', model=os.getenv('LLM_UPSTREAM_MODEL',''))
    results = []
    llm_calls = 0
    rag_hits = 0
    for q in queries:
        rec = {'query': q}
        t0 = time.time()
        # retrieval
        t1 = time.time()
        retrieved = retriever.retrieve_top_k(q, top_k=top_k, db_path=None)
        rec['retrieval_ms'] = int((time.time() - t1) * 1000)
        metrics = retriever.compute_retrieval_metrics(retrieved)
        rec.update(metrics)

        # decide route based on mode
        if mode == 'llm':
            route = 'llm'
        elif mode == 'rag':
            route = 'rag'
        elif mode == 'rag_feedback':
            route = 'rag'
        else:
            route = 'rag' if retriever.should_use_rag(metrics, strict=False) else 'llm'

        rec['route'] = route

        # generation and bookkeeping
        if route == 'rag':
            rag_hits += 1
            t2 = time.time()
            ans = rag_generator.generate_rag_answer(q, retrieved, agent=agent)
            rec['generation_ms'] = int((time.time() - t2) * 1000)
            rec['llm_call'] = 1
            llm_calls += 1
            # optionally persist feedback (simulate feedback loop)
            if mode == 'rag_feedback':
                try:
                    insert_feedback(conn, q, ans, ans[:200], [], time.time())
                except Exception:
                    pass
        else:
            t2 = time.time()
            ans = agent._call_gateway("Answer the query concisely.", q)
            rec['generation_ms'] = int((time.time() - t2) * 1000)
            rec['llm_call'] = 1
            llm_calls += 1

        rec['latency_ms'] = int((time.time() - t0) * 1000)
        rec['answer'] = ans
        rec['grounding_score'] = grounding_score(ans, [r.get('text_chunk','') for r in retrieved])
        rec['prompt_length'] = len(q)
        rec['response_length'] = len(ans or '')
        results.append(rec)

    summary = {
        'started_at': time.time(),
        'finished_at': time.time(),
        'results': results,
        'llm_call_count': llm_calls,
        'rag_hits': rag_hits,
        'rag_hit_rate': (rag_hits / max(1, len(queries)))
    }
    return summary
