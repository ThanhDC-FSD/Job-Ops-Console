import time
import os
import json
from typing import List, Dict
from tmp_seek_automation.rag import sqlite_repository
from tmp_seek_automation.integrations.agent import LocalAgent

DEFAULT_BATCH_SIZE = 20

def preprocess_jd(jd: Dict) -> Dict:
    # simple preprocessing: normalize text fields
    out = dict(jd)
    content = jd.get('content') or {}
    sections = content.get('sections') if isinstance(content, dict) else None
    if isinstance(sections, list):
        out['__preprocessed_text'] = '\n'.join(sections)
    else:
        out['__preprocessed_text'] = str(sections or '')
    return out

def retrieve_similar_for_extraction(conn, jd_text: str, top_k: int = 5) -> List[Dict]:
    # very light-weight similarity: scan vector_index for overlapping words
    candidates = sqlite_repository.query_vectors(conn)
    words = set(jd_text.lower().split())
    scored = []
    for r in candidates:
        score = sum(1 for w in words if w in (r.get('text_chunk') or '').lower())
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:top_k]]

def extract_with_llm(agent: LocalAgent, jd_text: str, timeout: int = 120) -> Dict:
    system = "Extract structured job fields as JSON: title, skills, requirements, responsibilities, summary. Return only JSON."
    user = f"Job text:\n{jd_text}\n\nRespond with a JSON object with keys: title, skills (array), requirements (array), responsibilities (array), summary (short)."
    raw = agent._call_gateway(system, user)
    try:
        obj = json.loads(raw)
        return obj
    except Exception:
        return {"raw": raw}

def run_etl_benchmark(batch: List[Dict], conn=None, agent: LocalAgent = None) -> Dict:
    conn = conn or sqlite_repository.ensure_connection()
    agent = agent or LocalAgent('etl-bench', model=os.getenv('LLM_UPSTREAM_MODEL', ''))
    results = []
    ts0 = time.time()
    for jd in batch:
        res = {"jd_id": jd.get('id') or jd.get('job_id')}
        t0 = time.time()
        pre = preprocess_jd(jd)
        res['preprocess_ms'] = int((time.time() - t0) * 1000)

        # retrieval for extraction
        t1 = time.time()
        retrieved = retrieve_similar_for_extraction(conn, pre.get('__preprocessed_text', ''), top_k=5)
        res['retrieval_for_extraction_ms'] = int((time.time() - t1) * 1000)

        # LLM extraction
        t2 = time.time()
        extracted = extract_with_llm(agent, pre.get('__preprocessed_text', ''))
        res['extraction_ms'] = int((time.time() - t2) * 1000)

        # validation/normalization (light)
        t3 = time.time()
        success = bool(extracted and (extracted.get('skills') or extracted.get('summary')))
        res['validation_ms'] = int((time.time() - t3) * 1000)

        # persist (light) - simulate write time
        t4 = time.time()
        try:
            sqlite_repository.insert_vector(conn, res['jd_id'] or 'unknown', str(int(time.time()*1000)), pre.get('__preprocessed_text',''), [], time.time())
            res['persist_ms'] = int((time.time() - t4) * 1000)
        except Exception:
            res['persist_ms'] = int((time.time() - t4) * 1000)

        # embedding + indexing (simulate small cost)
        t5 = time.time()
        res['embedding_ms'] = 5
        res['indexing_ms'] = 10

        res['total_ms'] = int((time.time() - t0) * 1000)
        res['success'] = success
        results.append(res)

    meta = {
        'started_at': ts0,
        'finished_at': time.time(),
        'dataset_size': len(batch),
        'results': results
    }
    return meta
