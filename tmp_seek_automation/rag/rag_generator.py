from typing import List, Dict
from tmp_seek_automation.integrations.agent import LocalAgent

def generate_rag_answer(query: str, retrieved_segments: List[Dict], agent: LocalAgent = None) -> str:
    agent = agent or LocalAgent('rag-generator', model='')
    system = (
        "You are an assistant that must answer queries strictly grounded in provided context. "
        "Do not add information not present in the context. Respond concisely."
    )
    context = '\n\n'.join([f"- {s.get('text_chunk')}" for s in retrieved_segments])
    user = f"Context:\n{context}\n\nUser Query:\n{query}\n\nAnswer using only the context above."
    return agent._call_gateway(system, user)
