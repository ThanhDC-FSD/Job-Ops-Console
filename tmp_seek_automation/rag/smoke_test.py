import time
from rag.sqlite_repository import ensure_connection, ensure_rag_tables
from rag.embedding_service import embed_batch
from rag.vector_index_manager import index_segments, retrieve
from rag.query_router import route_query

def prepare_sample_index(db_path=None):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    segments = [
        {'jd_id': 'job_1', 'segment_id': 's1', 'text': 'Senior backend engineer with Python, FastAPI, AWS and microservices.'},
        {'jd_id': 'job_2', 'segment_id': 's2', 'text': 'Frontend role focusing on React, TypeScript and UX.'},
        {'jd_id': 'job_3', 'segment_id': 's3', 'text': 'Data scientist with experience in Python, ML, PyTorch and data pipelines.'}
    ]
    embs = embed_batch([s['text'] for s in segments])
    index_segments(segments, embs, db_path=db_path)

def run_smoke(db_path=None):
    prepare_sample_index(db_path=db_path)
    q = 'Looking for Python backend experience with FastAPI and AWS'
    import os
    os.environ['LLM_TEST_FAKE_RESP'] = 'This is a fake LLM response for smoke test.'
    res = route_query(q, top_k=2, db_path=db_path)
    print('ROUTER RESULT:', res)

if __name__ == '__main__':
    run_smoke()
