import json
import time
from typing import Dict, Any, List
from integrations.agent import LocalAgent

def extract_structured_from_llm(query: str, llm_answer: str, agent: LocalAgent = None) -> Dict[str, Any]:
    # If the answer is already JSON, attempt to parse
    text = (llm_answer or '').strip()
    try:
        if text.startswith('{') or text.startswith('['):
            return json.loads(text)
    except Exception:
        pass

    # Otherwise, ask the LLM to produce a JSON extraction
    agent = agent or LocalAgent('extractor', model='')
    system = (
        "You are a structured data extractor. Given a user query and an LLM answer, return a JSON object:\n"
        "{\n  \"summary\": string,\n  \"skills\": [string],\n  \"concepts\": [string],\n  \"job_related_topics\": [string]\n}\n"
    )
    user = f"User Query:\n{query}\n\nLLM Answer:\n{llm_answer}\n\nReturn only valid JSON."
    resp = agent._call_gateway(system, user)
    try:
        return json.loads(resp)
    except Exception:
        # best-effort fallback
        return {
            'summary': (llm_answer or '')[:512],
            'skills': [],
            'concepts': [],
            'job_related_topics': []
        }
