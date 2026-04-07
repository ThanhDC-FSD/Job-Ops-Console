import sqlite3
import json
import os
from typing import Any, Dict, List, Optional

DB_PATH_ENV = "TMP_SEEK_SQLITE_DB"

def get_db_path():
    return os.getenv(DB_PATH_ENV) or os.path.join(os.path.dirname(__file__), '..', 'data', 'jobs.sqlite')

def ensure_connection(path: Optional[str] = None):
    p = path or get_db_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_rag_tables(conn: sqlite3.Connection):
    cur = conn.cursor()
    # Create table if missing, or migrate existing table by adding missing columns
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_index (
            id INTEGER PRIMARY KEY,
            jd_id TEXT,
            chunk_id TEXT,
            segment_id TEXT,
            source_field TEXT,
            heading TEXT,
            text_chunk TEXT,
            embedding TEXT,
            metadata_json TEXT,
            created_at REAL,
            updated_at REAL
        )
        """
    )
    # Ensure columns exist (for migrations from older schema)
    cur.execute("PRAGMA table_info('vector_index')")
    existing_cols = {row[1] for row in cur.fetchall()}
    required_cols = {
        'chunk_id': 'TEXT',
        'source_field': 'TEXT',
        'heading': 'TEXT',
        'metadata_json': 'TEXT',
        'updated_at': 'REAL'
    }
    for col, coltype in required_cols.items():
        if col not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE vector_index ADD COLUMN {col} {coltype}")
            except Exception:
                pass
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS knowledge_feedback (
            id INTEGER PRIMARY KEY,
            query TEXT,
            llm_answer TEXT,
            extracted_summary TEXT,
            extracted_skills TEXT,
            created_at REAL
        )
        '''
    )
    conn.commit()

def list_jds(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    # Attempt to read from an existing table named 'job_descriptions' or 'jds' or raw JSON store
    cur = conn.cursor()
    candidates = ['job_descriptions', 'jds', 'jobs']
    for t in candidates:
        try:
            cur.execute(f"SELECT * FROM {t} LIMIT 100")
            rows = cur.fetchall()
            results = []
            for r in rows:
                # attempt to find a json column
                rowd = dict(r)
                # find json-like column
                for v in rowd.values():
                    if isinstance(v, str) and (v.strip().startswith('{') or v.strip().startswith('[')):
                        try:
                            obj = json.loads(v)
                            results.append(obj)
                            break
                        except Exception:
                            continue
            if results:
                return results
        except Exception:
            continue
    # fallback: no JD table found
    return []

def insert_vector(conn: sqlite3.Connection, jd_id: str, segment_id: str, text_chunk: str, embedding: List[float], ts: float):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO vector_index (jd_id, chunk_id, segment_id, source_field, heading, text_chunk, embedding, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (jd_id, None, segment_id, None, None, text_chunk, json.dumps(embedding), json.dumps({}), ts, ts)
    )
    conn.commit()


def insert_vector_full(conn: sqlite3.Connection, jd_id: str, chunk_id: str, segment_id: str, source_field: str, heading: str, text_chunk: str, embedding: List[float], metadata: Dict, created_ts: float, updated_ts: float = None):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO vector_index (jd_id, chunk_id, segment_id, source_field, heading, text_chunk, embedding, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (jd_id, chunk_id, segment_id, source_field, heading, text_chunk, json.dumps(embedding), json.dumps(metadata or {}), created_ts, updated_ts or created_ts)
    )
    conn.commit()


def delete_vectors_for_jd(conn: sqlite3.Connection, jd_id: str):
    cur = conn.cursor()
    cur.execute("DELETE FROM vector_index WHERE jd_id = ?", (jd_id,))
    conn.commit()


def get_indexed_jd_ids(conn: sqlite3.Connection) -> List[str]:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT jd_id FROM vector_index")
    rows = cur.fetchall()
    return [r[0] for r in rows]

def query_vectors(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT id,jd_id,chunk_id,segment_id,source_field,heading,text_chunk,embedding,metadata_json,created_at,updated_at FROM vector_index")
    rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d['embedding'] = json.loads(d.get('embedding') or '[]')
        except Exception:
            d['embedding'] = []
        try:
            d['metadata'] = json.loads(d.get('metadata_json') or '{}')
        except Exception:
            d['metadata'] = {}
        out.append(d)
    return out

def insert_feedback(conn: sqlite3.Connection, query: str, llm_answer: str, summary: str, skills: List[str], ts: float):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO knowledge_feedback (query, llm_answer, extracted_summary, extracted_skills, created_at) VALUES (?, ?, ?, ?, ?)",
        (query, llm_answer, summary, json.dumps(skills), ts)
    )
    conn.commit()
