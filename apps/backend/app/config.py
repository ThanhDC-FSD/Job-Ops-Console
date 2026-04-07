import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv_file() -> None:
    if not ENV_FILE.exists():
        return
    try:
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            if not key:
                continue
            cleaned_value = value.strip().strip("'").strip('"')
            existing = os.getenv(key)
            if existing is None or str(existing).strip() == "":
                os.environ[key] = cleaned_value
    except Exception:
        return


_load_dotenv_file()

DB_PATH = Path(os.getenv("JOB_DB_PATH", PROJECT_ROOT / "input" / "crawled_job" / "linkedin_jobs_jd.sqlite")).resolve()
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8102"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5182")
APP_ENV = str(os.getenv("env", os.getenv("APP_ENV", "prod")) or "prod").strip().lower()
CLEAR_LOGS_ON_STARTUP = str(os.getenv("CLEAR_LOGS_ON_STARTUP", "0") or "").strip().lower() in {"1", "true", "yes", "on"}
RUN_STARTUP_BOOTSTRAP_ACTIONS = str(os.getenv("RUN_STARTUP_BOOTSTRAP_ACTIONS", "0") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DIAGNOSTICS = str(os.getenv("DIAGNOSTICS", "0") or "").strip().lower() in {"1", "true", "yes", "on"}
AUTO_SHUTDOWN_AFTER_ETL = str(os.getenv("AUTO_SHUTDOWN_AFTER_ETL", "1") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ETL_SHUTDOWN_DELAY_SECONDS = int(os.getenv("ETL_SHUTDOWN_DELAY_SECONDS", "60") or "60")
ETL_SHUTDOWN_MESSAGE = str(os.getenv("ETL_SHUTDOWN_MESSAGE", "ETL pipeline complete; shutting down.")).strip()

# Tuning flags (safe defaults keep legacy behavior)
TUNING_CACHE_VERSION = str(os.getenv("TUNING_CACHE_VERSION", "v1")).strip()
TUNING_CHUNK_CACHE_ENABLED = str(os.getenv("TUNING_CHUNK_CACHE_ENABLED", "1")).strip().lower() in {"1", "true", "yes"}
TUNING_GATEWAY_WARMUP = str(os.getenv("TUNING_GATEWAY_WARMUP", "0")).strip().lower() in {"1", "true", "yes"}
TUNING_DEFER_RENDER = str(os.getenv("TUNING_DEFER_RENDER", "0")).strip().lower() in {"1", "true", "yes"}
TUNING_ENABLE_JSONL_METRICS = str(os.getenv("TUNING_ENABLE_JSONL_METRICS", "1")).strip().lower() in {"1", "true", "yes"}
TUNING_ENABLE_RERANK_FOR_CV_REWRITE = str(os.getenv("TUNING_ENABLE_RERANK_FOR_CV_REWRITE", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_PROMPT_JD_MAX_CHARS = int(os.getenv("TUNING_PROMPT_JD_MAX_CHARS", "700"))
TUNING_PROMPT_CV_MAX_CHARS = int(os.getenv("TUNING_PROMPT_CV_MAX_CHARS", "900"))
TUNING_PROMPT_GUIDE_MAX_CHARS = int(os.getenv("TUNING_PROMPT_GUIDE_MAX_CHARS", "500"))
TUNING_TOP_K_CONTEXT = int(os.getenv("TUNING_TOP_K_CONTEXT", "6"))
TUNING_ENRICH_MAX_BATCH = int(os.getenv("TUNING_ENRICH_MAX_BATCH", "80"))
TUNING_ENRICH_MAX_RUNTIME_SEC = int(os.getenv("TUNING_ENRICH_MAX_RUNTIME_SEC", "180"))
TUNING_ENRICH_CHUNK_LIMIT = int(os.getenv("TUNING_ENRICH_CHUNK_LIMIT", "3"))
TUNING_SQLITE_CACHE_SIZE = int(os.getenv("TUNING_SQLITE_CACHE_SIZE", "-2000"))  # pages; negative -> KB
TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE = str(os.getenv("TUNING_ENABLE_RETRIEVAL_FOR_CV_REWRITE", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_RETRIEVAL_TOP_K = int(os.getenv("TUNING_RETRIEVAL_TOP_K", "8"))
TUNING_RERANK_TOP_K = int(os.getenv("TUNING_RERANK_TOP_K", "4"))
TUNING_RETRIEVAL_MIN_SCORE = float(os.getenv("TUNING_RETRIEVAL_MIN_SCORE", "0.30"))
TUNING_RETRIEVAL_MIN_GAP = float(os.getenv("TUNING_RETRIEVAL_MIN_GAP", "0.05"))
TUNING_MAX_PROMPT_TOKENS = int(os.getenv("TUNING_MAX_PROMPT_TOKENS", "1800"))
TUNING_PROMPT_RESERVED_TOKENS = int(os.getenv("TUNING_PROMPT_RESERVED_TOKENS", "350"))
TUNING_ENABLE_PERSISTED_CONTEXT_CACHE = str(os.getenv("TUNING_ENABLE_PERSISTED_CONTEXT_CACHE", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_ENABLE_CONTEXT_PACK = str(os.getenv("TUNING_ENABLE_CONTEXT_PACK", "0")).strip().lower() in {"1", "true", "yes"}
TUNING_CONTEXT_PACK_MAX_CHUNKS = int(os.getenv("TUNING_CONTEXT_PACK_MAX_CHUNKS", "4"))
TUNING_ENABLE_PERSISTED_CACHE = str(os.getenv("TUNING_ENABLE_PERSISTED_CACHE", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_CACHE_DB_PATH = str(os.getenv("TUNING_CACHE_DB_PATH", ".cache/tuning_cache.sqlite")).strip()
TUNING_CACHE_SQLITE_WAL = str(os.getenv("TUNING_CACHE_SQLITE_WAL", "1")).strip().lower() in {"1", "true", "yes"}
TUNING_TOKENIZER_BACKEND = str(os.getenv("TUNING_TOKENIZER_BACKEND", "auto")).strip().lower()
TUNING_BENCH_REPEAT = int(os.getenv("TUNING_BENCH_REPEAT", "3"))
TUNING_BENCH_CONCURRENCY = int(os.getenv("TUNING_BENCH_CONCURRENCY", "1"))
TUNING_BENCH_FAIL_ON_REGRESSION = str(os.getenv("TUNING_BENCH_FAIL_ON_REGRESSION", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_REGRESSION_P95_PCT = float(os.getenv("TUNING_REGRESSION_P95_PCT", "10"))
TUNING_LOG_RETRIEVAL_METRICS = str(os.getenv("TUNING_LOG_RETRIEVAL_METRICS", "1")).strip().lower() in {"1", "true", "yes"}
TUNING_FORCE_HEURISTIC_FALLBACK_ON_ERROR = str(os.getenv("TUNING_FORCE_HEURISTIC_FALLBACK_ON_ERROR", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_LOG_DIR = str(os.getenv("TUNING_LOG_DIR", "/home/user/tuning_logs")).strip()
TUNING_LOG_DIR_WIN = str(os.getenv("TUNING_LOG_DIR_WIN", "")).strip()
TUNING_ENABLE_INTERVIEW_PREDICTION = str(os.getenv("TUNING_ENABLE_INTERVIEW_PREDICTION", "0")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_PREDICT_QA_TOP_K = int(os.getenv("TUNING_PREDICT_QA_TOP_K", "12"))
TUNING_PREDICT_QA_OUT_N = int(os.getenv("TUNING_PREDICT_QA_OUT_N", "8"))
TUNING_PREDICT_QA_BACKEND = str(os.getenv("TUNING_PREDICT_QA_BACKEND", "ollama")).strip().lower()
TUNING_PREDICT_QA_MODEL = str(os.getenv("TUNING_PREDICT_QA_MODEL", "qwen2.5:1.5b-instruct")).strip()
TUNING_PREDICT_QA_USE_VET_PASS = str(os.getenv("TUNING_PREDICT_QA_USE_VET_PASS", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
}
TUNING_PREDICT_QA_OUTPUT_FORMAT = str(os.getenv("TUNING_PREDICT_QA_OUTPUT_FORMAT", "json")).strip().lower()
TUNING_PREDICT_QA_MAX_JOBS = int(os.getenv("TUNING_PREDICT_QA_MAX_JOBS", "10"))
TUNING_PREDICT_QA_KEEP_ALIVE = str(os.getenv("TUNING_PREDICT_QA_KEEP_ALIVE", "30m")).strip()
TUNING_PREDICT_QA_LOG_DIR = str(os.getenv("TUNING_PREDICT_QA_LOG_DIR", "tmp_seek_automation/prediction/interview_qa")).strip()
TUNING_PREDICT_QA_QUESTION_BANK_VERSION = str(os.getenv("TUNING_PREDICT_QA_QUESTION_BANK_VERSION", "v1")).strip()

# Explicit feature toggles (default safe)
ENABLE_TIMING_LOGS = str(os.getenv("ENABLE_TIMING_LOGS", "1")).strip().lower() in {"1", "true", "yes"}
ENABLE_EMBED_CACHE = str(os.getenv("ENABLE_EMBED_CACHE", "1")).strip().lower() in {"1", "true", "yes"}
ENABLE_PERSISTED_EMBED_CACHE = str(os.getenv("ENABLE_PERSISTED_EMBED_CACHE", "0")).strip().lower() in {"1", "true", "yes"}
ENABLE_PROMPT_BUDGET = str(os.getenv("ENABLE_PROMPT_BUDGET", "1")).strip().lower() in {"1", "true", "yes"}
ENABLE_ASYNC_RENDER = str(os.getenv("ENABLE_ASYNC_RENDER", "0")).strip().lower() in {"1", "true", "yes"}
ENABLE_WARMUP = str(os.getenv("ENABLE_WARMUP", "0")).strip().lower() in {"1", "true", "yes"}
ENABLE_HEALTHCHECK = str(os.getenv("ENABLE_HEALTHCHECK", "1")).strip().lower() in {"1", "true", "yes"}
ENABLE_SQLITE_WAL_TUNING = str(os.getenv("ENABLE_SQLITE_WAL_TUNING", "1")).strip().lower() in {"1", "true", "yes"}
ENABLE_STREAMING = str(os.getenv("ENABLE_STREAMING", "0")).strip().lower() in {"1", "true", "yes"}

GATEWAY_TIMEOUT_SEC = float(os.getenv("GATEWAY_TIMEOUT_SEC", "180"))
GATEWAY_MAX_RETRIES = int(os.getenv("GATEWAY_MAX_RETRIES", "2"))
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "30000"))
