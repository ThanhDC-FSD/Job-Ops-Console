import time
import math
from typing import List, Dict
from .sqlite_repository import ensure_connection, ensure_rag_tables, insert_vector, query_vectors

def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return s / (na * nb)

def index_segments(segments: List[Dict], embeddings: List[List[float]], db_path: str = None):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    ts = time.time()
    for seg, emb in zip(segments, embeddings):
        jd_id = seg.get('jd_id') or seg.get('job_id') or 'unknown'
        segment_id = seg.get('segment_id') or seg.get('id') or 's-unknown'
        text = seg.get('text') or seg.get('heading', '') + '\n' + seg.get('text', '')
        insert_vector(conn, jd_id, segment_id, text, emb, ts)

def retrieve(query_emb: List[float], top_k: int = 5, db_path: str = None):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    rows = query_vectors(conn)
    scored = []
    for r in rows:
        score = _cosine(query_emb, r.get('embedding') or [])
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return scored[:top_k]
