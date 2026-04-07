import json
import os
from datetime import datetime
import sqlite3

BENCH_DB_SCHEMA = '''
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id TEXT PRIMARY KEY,
    mode TEXT,
    model_name TEXT,
    started_at REAL,
    finished_at REAL,
    dataset_size INTEGER,
    avg_latency REAL,
    p95_latency REAL,
    avg_quality_score REAL,
    llm_call_count INTEGER,
    rag_hit_rate REAL
);

CREATE TABLE IF NOT EXISTS benchmark_query_results (
    id TEXT PRIMARY KEY,
    benchmark_run_id TEXT,
    query TEXT,
    mode TEXT,
    route TEXT,
    top1_score REAL,
    avg_top_k_score REAL,
    relevant_count INTEGER,
    latency_ms INTEGER,
    retrieval_ms INTEGER,
    generation_ms INTEGER,
    quality_score REAL,
    notes TEXT
);
'''

def write_json_report(results: dict, out_dir: str = None) -> str:
    out_dir = out_dir or os.path.join(os.path.dirname(__file__), 'results')
    os.makedirs(out_dir, exist_ok=True)
    fname = os.path.join(out_dir, f"benchmark_{int(datetime.utcnow().timestamp())}.json")
    with open(fname, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    return fname


def write_sqlite_report(results: dict, db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # create schema if not exists
    for stmt in BENCH_DB_SCHEMA.split(';'):
        s = stmt.strip()
        if s:
            cur.execute(s)
    # insert runs and query rows
    run_id = results.get('run_id') or str(int(datetime.utcnow().timestamp()))
    run = (
        run_id,
        results.get('mode', 'mixed'),
        results.get('config', {}).get('model'),
        results.get('started_at', 0),
        results.get('finished_at', 0),
        results.get('dataset_size', 0),
        results.get('aggregates', {}).get('latency', {}).get('avg', 0.0),
        results.get('aggregates', {}).get('latency', {}).get('p95', 0.0),
        results.get('aggregates', {}).get('quality', 0.0),
        results.get('aggregates', {}).get('llm_call_count', 0),
        results.get('aggregates', {}).get('rag_hit_rate', 0.0),
    )
    try:
        cur.execute('INSERT OR REPLACE INTO benchmark_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)', run)
    except Exception:
        pass
    # insert query results if present
    for q in results.get('queries', {}).get('results', []):
        qid = q.get('id') or str(abs(hash(q.get('query',''))))
        row = (
            qid,
            run_id,
            q.get('query',''),
            results.get('mode','mixed'),
            q.get('route',''),
            q.get('top1_score',0.0),
            q.get('avg_top_k_score',0.0),
            q.get('relevant_count',0),
            q.get('latency_ms',0),
            q.get('retrieval_ms',0),
            q.get('generation_ms',0),
            q.get('quality_score',0.0),
            q.get('notes','')
        )
        try:
            cur.execute('INSERT OR REPLACE INTO benchmark_query_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', row)
        except Exception:
            pass
    conn.commit()
    conn.close()
    return db_path
