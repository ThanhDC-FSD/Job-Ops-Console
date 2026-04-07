import time
import json
import os
from typing import List, Dict, Any, Optional

from .sqlite_repository import ensure_connection, ensure_rag_tables, insert_vector_full, delete_vectors_for_jd, get_indexed_jd_ids, list_jds
from .embedding_service import embed_batch


def _normalize_text(s: Optional[str]) -> str:
    return (s or '').strip()


def _make_overview_text(jd: Dict[str, Any]) -> str:
    title = jd.get('title', '')
    company = (jd.get('company') or {}).get('name') if jd.get('company') else jd.get('companyProfile', {}).get('name', '')
    seniority = jd.get('seniority', '')
    loc = jd.get('location') or {}
    city = loc.get('city') or ''
    country = loc.get('country') or ''
    summary = jd.get('summary') or jd.get('raw_text', '')
    skills = jd.get('skills') or []
    musts = jd.get('must_have_requirements') or []
    skill_list = ', '.join(map(str, skills[:8]))
    must_list = '; '.join(map(str, musts[:6]))
    parts = [f"Job Title: {title}"]
    if company:
        parts.append(f"Company: {company}")
    if seniority:
        parts.append(f"Seniority: {seniority}")
    if city or country:
        parts.append(f"Location: {city}{(', ' + country) if city and country else country}")
    if summary:
        parts.append(f"Summary: {summary}")
    if skill_list:
        parts.append(f"Major skills: {skill_list}")
    if must_list:
        parts.append(f"Key requirements: {must_list}")
    return '. '.join(parts)


def _flatten_jd_to_units(jd: Dict[str, Any]) -> List[Dict[str, Any]]:
    jd_id = jd.get('jd_id') or jd.get('id') or jd.get('job_id') or 'unknown'
    title = jd.get('title', '')
    company = (jd.get('company') or {}).get('name') if jd.get('company') else jd.get('companyProfile', {}).get('name', '')
    city = (jd.get('location') or {}).get('city', '')
    country = (jd.get('location') or {}).get('country', '')
    seniority = jd.get('seniority', '')
    employment_type = jd.get('employment_type', '')
    tags = jd.get('tags') or []

    units: List[Dict[str, Any]] = []

    # overview chunk (combined fields for broad retrieval)
    overview = _make_overview_text(jd)
    overview_metadata = {
        'title': title,
        'company': company,
        'city': city,
        'country': country,
        'seniority': seniority,
        'employment_type': employment_type,
        'tags': tags,
        'skills': jd.get('skills') or [],
        'key_requirements': (jd.get('must_have_requirements') or [])[:6]
    }
    units.append({
        'jd_id': jd_id,
        'chunk_id': f"{jd_id}::overview",
        'segment_id': None,
        'source_field': 'overview',
        'heading': 'Overview',
        'text': overview,
        'metadata': overview_metadata
    })

    # summary (if separate)
    summary = jd.get('summary')
    if summary:
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::summary",
            'segment_id': None,
            'source_field': 'summary',
            'heading': 'Summary',
            'text': f"Job Title: {title}. Summary: {summary}",
            'metadata': {}
        })

    # responsibilities
    for i, r in enumerate(jd.get('responsibilities') or []):
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::responsibility::{i}",
            'segment_id': None,
            'source_field': 'responsibility',
            'heading': 'Responsibility',
            'text': f"Job Title: {title}. Responsibility: {r}",
            'metadata': {}
        })

    # must_have_requirements
    for i, r in enumerate(jd.get('must_have_requirements') or []):
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::must::{i}",
            'segment_id': None,
            'source_field': 'must_have',
            'heading': 'Must Have',
            'text': f"Job Title: {title}. Must-have requirement: {r}",
            'metadata': {}
        })

    # nice_to_have
    for i, r in enumerate(jd.get('nice_to_have') or []):
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::nice::{i}",
            'segment_id': None,
            'source_field': 'nice_to_have',
            'heading': 'Nice To Have',
            'text': f"Job Title: {title}. Nice-to-have: {r}",
            'metadata': {}
        })

    # skills
    for i, s in enumerate(jd.get('skills') or []):
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::skill::{i}",
            'segment_id': None,
            'source_field': 'skill',
            'heading': 'Skill',
            'text': f"Job Title: {title}. Skill: {s}",
            'metadata': {}
        })

    # highlights
    for i, h in enumerate(jd.get('highlights') or []):
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::highlight::{i}",
            'segment_id': None,
            'source_field': 'highlight',
            'heading': 'Highlight',
            'text': f"Job Title: {title}. Highlight: {h}",
            'metadata': {}
        })

    # segments (detailed sections)
    for seg in jd.get('segments') or []:
        sid = seg.get('segment_id') or seg.get('id') or str(hash(seg.get('heading','') + str(seg.get('text',''))))
        heading = seg.get('heading') or 'Section'
        text = seg.get('text') or ''
        units.append({
            'jd_id': jd_id,
            'chunk_id': f"{jd_id}::segment::{sid}",
            'segment_id': sid,
            'source_field': 'segment',
            'heading': heading,
            'text': f"Job Title: {title}. Section: {heading}. Text: {text}",
            'metadata': {}
        })

    return units


def build_rag_data_from_existing_jobs(db_path: Optional[str] = None, dim: int = 256, batch_size: int = 256):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    jds = list_jds(conn)
    if not jds:
        print('No JD records found in database; nothing to index.')
        return 0

    total_indexed = 0
    for jd in jds:
        units = _flatten_jd_to_units(jd)
        texts = [u['text'] for u in units]
        embs = embed_batch(texts, dim=dim)
        ts = time.time()
        for u, emb in zip(units, embs):
            insert_vector_full(conn, u['jd_id'], u['chunk_id'], u.get('segment_id'), u['source_field'], u['heading'], u['text'], emb, u.get('metadata', {}), ts, updated_ts=ts)
            total_indexed += 1

    print(f'Indexed {total_indexed} retrieval units from {len(jds)} JDs')
    return total_indexed


def rebuild_vector_index(db_path: Optional[str] = None, dim: int = 256):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    # clear existing vectors
    cur = conn.cursor()
    cur.execute('DELETE FROM vector_index')
    conn.commit()
    return build_rag_data_from_existing_jobs(db_path=db_path, dim=dim)


def index_job(jd_id: str, db_path: Optional[str] = None, dim: int = 256):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    jds = list_jds(conn)
    for jd in jds:
        if jd.get('jd_id') == jd_id or jd.get('id') == jd_id or jd.get('job_id') == jd_id:
            # remove old vectors for this jd
            delete_vectors_for_jd(conn, jd_id)
            units = _flatten_jd_to_units(jd)
            texts = [u['text'] for u in units]
            embs = embed_batch(texts, dim=dim)
            ts = time.time()
            for u, emb in zip(units, embs):
                insert_vector_full(conn, u['jd_id'], u['chunk_id'], u.get('segment_id'), u['source_field'], u['heading'], u['text'], emb, u.get('metadata', {}), ts, updated_ts=ts)
            return True
    return False


def sync_unindexed_jobs(db_path: Optional[str] = None, dim: int = 256):
    conn = ensure_connection(db_path)
    ensure_rag_tables(conn)
    jds = list_jds(conn)
    if not jds:
        print('No JDs available to sync.')
        return 0
    indexed = set(get_indexed_jd_ids(conn))
    to_index = [jd for jd in jds if (jd.get('jd_id') or jd.get('id') or jd.get('job_id') or 'unknown') not in indexed]
    count = 0
    for jd in to_index:
        units = _flatten_jd_to_units(jd)
        texts = [u['text'] for u in units]
        embs = embed_batch(texts, dim=dim)
        ts = time.time()
        for u, emb in zip(units, embs):
            insert_vector_full(conn, u['jd_id'], u['chunk_id'], u.get('segment_id'), u['source_field'], u['heading'], u['text'], emb, u.get('metadata', {}), ts, updated_ts=ts)
            count += 1
    print(f'Indexed {count} new retrieval units from {len(to_index)} JDs')
    return count


if __name__ == '__main__':
    # CLI driver
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--rebuild', action='store_true')
    p.add_argument('--db', default=None)
    args = p.parse_args()
    if args.rebuild:
        rebuild_vector_index(db_path=args.db)
    else:
        build_rag_data_from_existing_jobs(db_path=args.db)
