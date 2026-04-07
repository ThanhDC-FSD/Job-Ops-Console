from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from typing import Iterable

from app.config import ENABLE_EMBED_CACHE, TUNING_CACHE_VERSION

TOKEN_RE = re.compile(r"[a-z0-9+#./_-]{2,}", re.IGNORECASE)

# cache metrics for smoke
CACHE_STATS = {
    "normalize_hit": 0,
    "tokenize_hit": 0,
    "split_hit": 0,
    "embed_hit": 0,
    "normalize_miss": 0,
    "tokenize_miss": 0,
    "split_miss": 0,
    "embed_miss": 0,
}

@lru_cache(maxsize=1024)
def normalize_vector_text(value: str) -> str:
    CACHE_STATS["normalize_hit"] += 1
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@lru_cache(maxsize=1024)
def tokenize_vector_text(value: str) -> list[str]:
    CACHE_STATS["tokenize_hit"] += 1
    text = normalize_vector_text(value).lower()
    return TOKEN_RE.findall(text)


@lru_cache(maxsize=512)
def _split_text_chunks_cached(value: str, max_chars: int, overlap_chars: int) -> tuple[str, ...]:
    CACHE_STATS["split_hit"] += 1
    text = normalize_vector_text(value)
    if not text:
        return ()
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue
        candidate = f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        chunks.append(current.strip())
        if overlap_chars > 0 and len(current) > overlap_chars:
            carry = current[-overlap_chars:].strip()
            current = f"{carry}\n\n{paragraph}".strip()
        else:
            current = paragraph
    if current.strip():
        chunks.append(current.strip())

    normalized_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            normalized_chunks.append(chunk)
            continue
        start = 0
        step = max(120, max_chars - overlap_chars)
        while start < len(chunk):
            piece = chunk[start : start + max_chars].strip()
            if piece:
                normalized_chunks.append(piece)
            start += step
    return tuple(normalized_chunks)


def split_text_chunks(value: str, *, max_chars: int = 900, overlap_chars: int = 140) -> list[str]:
    # cached to avoid recomputing for identical text/params in a single run
    if not ENABLE_EMBED_CACHE:
        CACHE_STATS["split_miss"] += 1
        return list(_split_text_chunks_cached.__wrapped__(f"{TUNING_CACHE_VERSION}::{value}", max_chars, overlap_chars))
    return list(_split_text_chunks_cached(f"{TUNING_CACHE_VERSION}::{value}", max_chars, overlap_chars))


@lru_cache(maxsize=512)
def build_hashed_embedding(value: str, *, dimensions: int = 128) -> list[float]:
    token_source = f"{TUNING_CACHE_VERSION}::{value}"
    if not ENABLE_EMBED_CACHE:
        CACHE_STATS["embed_miss"] += 1
        tokens = tokenize_vector_text.__wrapped__(token_source)
    else:
        CACHE_STATS["embed_hit"] += 1
        tokens = tokenize_vector_text(token_source)
    if not tokens:
        return [0.0] * dimensions
    counts = Counter(tokens)
    vector = [0.0] * dimensions
    for token, count in counts.items():
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % dimensions
        vector[bucket] += float(count)
    norm = math.sqrt(sum(component * component for component in vector))
    if norm <= 0:
        return [0.0] * dimensions
    return [round(component / norm, 6) for component in vector]


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_list = list(left)
    right_list = list(right)
    if not left_list or not right_list or len(left_list) != len(right_list):
        return 0.0
    numerator = sum((a * b) for a, b in zip(left_list, right_list))
    left_norm = math.sqrt(sum((a * a) for a in left_list))
    right_norm = math.sqrt(sum((b * b) for b in right_list))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)
