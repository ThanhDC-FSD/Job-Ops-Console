import time
import os
from rag.smoke_test import prepare_sample_index
from rag.query_router import route_query
from integrations.agent import LocalAgent


def run_rag_benchmark(query, runs=10, db_path=None):
    times = []
    for _ in range(runs):
        start = time.time()
        _ = route_query(query, top_k=5, db_path=db_path)
        times.append(time.time() - start)
    return times


def run_llm_only_benchmark(job, resume_text, runs=10):
    agent = LocalAgent('perf-test', model='test-model')
    times = []
    for _ in range(runs):
        start = time.time()
        _ = agent.prepare_cover_letter(job, resume_text, convert_to_australian_language=False)
        times.append(time.time() - start)
    return times


def summarize(name, times):
    import statistics
    print(f"--- {name} ---")
    print(f"runs: {len(times)}")
    print(f"avg: {statistics.mean(times):.4f}s, median: {statistics.median(times):.4f}s, min: {min(times):.4f}s, max: {max(times):.4f}s")


if __name__ == '__main__':
    # Use fake response only when explicitly requested by environment.
    # If you want to test against a local LLM gateway, unset LLM_TEST_FAKE_RESP before running.
    if os.getenv('LLM_TEST_FAKE_RESP') is None:
        os.environ['LLM_PROMPT_COMPRESSION'] = '1'
    else:
        # keep provided fake response and compression setting
        os.environ.setdefault('LLM_PROMPT_COMPRESSION', '1')

    # prepare sample index
    prepare_sample_index()

    query = 'Backend engineer with FastAPI and AWS experience'

    # sample job/resume for LLM-only
    job = {
        'title': 'Software Engineer',
        'companyProfile': {'name': 'Acme Co'},
        'content': {'sections': ['Build APIs with Python and FastAPI', 'Cloud integrations and deployments.']}
    }
    resume_text = 'Experienced backend engineer with Python, FastAPI, and cloud experience.'

    runs = 20
    rag_times = run_rag_benchmark(query, runs=runs)
    llm_times = run_llm_only_benchmark(job, resume_text, runs=runs)

    summarize('RAG (retrieve+grounded LLM)', rag_times)
    summarize('LLM-only (full prompt)', llm_times)

    # simple comparison
    import statistics
    print('\nComparison:')
    print(f"RAG avg / LLM avg = {statistics.mean(rag_times)/statistics.mean(llm_times):.3f}")
