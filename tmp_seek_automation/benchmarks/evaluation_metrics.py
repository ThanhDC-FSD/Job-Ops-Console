import statistics
from typing import List, Dict

def latency_stats(latencies_ms: List[float]) -> Dict:
    if not latencies_ms:
        return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0}
    return {
        "count": len(latencies_ms),
        "avg": float(statistics.mean(latencies_ms)),
        "p50": float(statistics.median(latencies_ms)),
        "p95": float(sorted(latencies_ms)[int(len(latencies_ms) * 0.95) - 1]) if len(latencies_ms) >= 1 else float(latencies_ms[0])
    }

def aggregate_metrics(results: List[Dict]) -> Dict:
    latencies = [r.get('latency_ms', 0.0) for r in results]
    retrievals = [r.get('retrieval_ms', 0.0) for r in results]
    gens = [r.get('generation_ms', 0.0) for r in results]
    routes = [r.get('route', 'llm') for r in results]
    return {
        "total_queries": len(results),
        "latency": latency_stats(latencies),
        "retrieval": latency_stats(retrievals),
        "generation": latency_stats(gens),
        "route_counts": {"rag": routes.count('rag'), "llm": routes.count('llm')}
    }
