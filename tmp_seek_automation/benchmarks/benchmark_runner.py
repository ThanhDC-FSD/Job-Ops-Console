import argparse
import os
import json
from tmp_seek_automation.benchmarks.benchmark_etl import run_etl_benchmark
from tmp_seek_automation.benchmarks.benchmark_queries import build_query_sets, run_query_benchmark
from tmp_seek_automation.rag.sqlite_repository import ensure_connection, list_jds
from tmp_seek_automation.benchmarks.performance_reporter import write_json_report, write_sqlite_report
from tmp_seek_automation.benchmarks.evaluation_metrics import aggregate_metrics
import uuid


def load_dataset(sample_limit: int = 100):
    conn = ensure_connection()
    jds = list_jds(conn)
    return jds[:sample_limit]


def run_all(args):
    out = {"config": {"gateway": os.getenv('LLM_GATEWAY_BASE_URL'), "model": os.getenv('LLM_UPSTREAM_MODEL')} }
    jds = load_dataset(args.sample)
    out['dataset_size'] = len(jds)
    run_id = str(uuid.uuid4())
    out['run_id'] = run_id

    if args.etl:
        etl_res = run_etl_benchmark(jds[: args.batch or 10])
        out['etl'] = etl_res

    if args.queries:
        qs = build_query_sets(jds, n_per_group=args.per_group or 10)
        all_queries = []
        for group, items in qs.items():
            all_queries.extend(items)

        modes = args.modes.split(',') if args.modes else ['llm','rag','rag_feedback','auto']
        out['modes'] = {}
        for m in modes:
            print('Running mode:', m)
            first = run_query_benchmark(all_queries, mode=m)
            # repeated run to simulate hot-cache / feedback
            second = run_query_benchmark(all_queries, mode=m)
            out['modes'][m] = {'first': first, 'repeat': second}
            # aggregate for this mode
            out['modes'][m]['aggregates'] = {
                'llm_call_count': first.get('llm_call_count', 0),
                'rag_hit_rate': first.get('rag_hit_rate', 0.0)
            }

        # overall aggregate from the last executed mode
        last_mode = modes[-1]
        last_results = out['modes'][last_mode]['first']['results']
        out['query_metrics'] = aggregate_metrics(last_results)

    # write JSON and optionally sqlite
    outfile = write_json_report(out, out_dir=args.outdir)
    print("Wrote report:", outfile)
    if args.sqlite:
        dbpath = args.sqlite
        try:
            write_sqlite_report(out, dbpath)
            print('Wrote sqlite report to', dbpath)
        except Exception as e:
            print('Failed writing sqlite report:', e)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--etl', action='store_true')
    p.add_argument('--queries', action='store_true')
    p.add_argument('--modes', type=str, default=None, help='Comma-separated run modes: llm,rag,rag_feedback,auto')
    p.add_argument('--sqlite', type=str, default=None, help='Optional sqlite file to write benchmark results')
    p.add_argument('--sample', type=int, default=100)
    p.add_argument('--batch', type=int, default=10)
    p.add_argument('--per-group', type=int, default=10)
    p.add_argument('--outdir', type=str, default=None)
    args = p.parse_args()
    run_all(args)


if __name__ == '__main__':
    main()
