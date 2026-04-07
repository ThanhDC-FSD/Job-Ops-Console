"""
Lightweight performance smoke harness for CPU-only environment.
Runs synthetic operations to capture p50/p95 timings and cache hit stats.
This is not a full integration test; it avoids external LLM/gateway calls.
"""

import statistics
import time
from pathlib import Path

from app.services.text_vector_utils import (
    build_hashed_embedding,
    split_text_chunks,
    CACHE_STATS,
)


def time_call(fn, *args, **kwargs):
    t0 = time.perf_counter()
    fn(*args, **kwargs)
    return time.perf_counter() - t0


def run_smoke(samples: int = 5):
    jd = (Path(__file__).parent / "fixtures" / "sample_jd.txt").read_text(encoding="utf-8")
    cv = (Path(__file__).parent / "fixtures" / "sample_cv.txt").read_text(encoding="utf-8")

    chunk_timings = []
    embed_timings = []

    for _ in range(samples):
        chunk_timings.append(time_call(split_text_chunks, jd, max_chars=700, overlap_chars=120))
        embed_timings.append(time_call(build_hashed_embedding, cv))

    def stats(name, arr):
        if not arr:
            return {"name": name, "count": 0}
        return {
            "name": name,
            "count": len(arr),
            "p50": round(statistics.median(arr), 4),
            "p95": round(sorted(arr)[int(len(arr) * 0.95) if len(arr) > 1 else -1], 4),
            "min": round(min(arr), 4),
            "max": round(max(arr), 4),
        }

    return {
        "samples": samples,
        "stats": [
            stats("chunk", chunk_timings),
            stats("embed", embed_timings),
        ],
        "cache_stats": CACHE_STATS,
    }


if __name__ == "__main__":
    result = run_smoke()
    print(result)
