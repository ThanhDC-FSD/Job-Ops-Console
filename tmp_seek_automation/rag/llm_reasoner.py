import time
from typing import Dict, Any
from integrations.agent import LocalAgent
from .knowledge_extractor import extract_structured_from_llm
from .sqlite_repository import ensure_connection, ensure_rag_tables, insert_feedback
from .vector_index_manager import index_segments

def reason_with_llm(query: str, agent: LocalAgent = None, db_path: str = None) -> Dict[str, Any]:
    agent = agent or LocalAgent('rag-reasoner', model='')
    system = "You are an assistant. Answer the user query thoroughly and concisely."
    user = f"{query}\n\nProvide a helpful answer." 
    llm_answer = agent._call_gateway(system, user)
    # extract structured knowledge
    structured = extract_structured_from_llm(query, llm_answer, agent=agent)
    # persist feedback and add embeddings to index
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    ts = time.time()
    try:
        insert_feedback(conn, query, llm_answer, structured.get('summary',''), structured.get('skills', []), ts)
    except Exception:
        pass
    # if structured has meaningful segments, index them
    segs = []
    if structured.get('summary'):
        segs.append({'jd_id': 'feedback', 'segment_id': f'fb-{int(ts)}', 'text': structured.get('summary')})
    # build embeddings and index
    if segs:
        from .embedding_service import embed_batch
        embs = embed_batch([s['text'] for s in segs])
        index_segments(segs, embs, db_path=db_path)

    return {'answer': llm_answer, 'structured': structured}
