import math
import re
from typing import List

# Prefer sentence-transformers when available; otherwise fallback to simple embedding
_has_st = False
_st_model = None
try:
    from sentence_transformers import SentenceTransformer
    _has_st = True
except Exception:
    _has_st = False


def _simple_tokenize(text: str):
    toks = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", (text or '').lower())
    return toks


def simple_embedding(text: str, dim: int = 256) -> List[float]:
    toks = _simple_tokenize(text)
    buckets = [0.0] * dim
    for t in toks:
        h = 0
        for c in t:
            h = (h * 31 + ord(c)) & 0xFFFFFFFF
        idx = h % dim
        buckets[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in buckets)) or 1.0
    return [x / norm for x in buckets]


def _ensure_st_model(name: str = 'all-MiniLM-L6-v2'):
    global _st_model, _has_st
    if not _has_st:
        return None
    if _st_model is None:
        _st_model = SentenceTransformer(name)
    return _st_model


def sentence_transformers_embed(texts: List[str], model_name: str = 'all-MiniLM-L6-v2') -> List[List[float]]:
    model = _ensure_st_model(model_name)
    if model is None:
        return [simple_embedding(t or '') for t in texts]
    embs = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    # normalize
    out = []
    for v in embs:
        norm = math.sqrt(float((v * v).sum())) or 1.0
        out.append([float(x / norm) for x in v.tolist()])
    return out


def embed_batch(texts: List[str], dim: int = 256, model_name: str = 'all-MiniLM-L6-v2') -> List[List[float]]:
    """Generate embeddings for a batch of texts.

    If sentence-transformers is available, uses that model; otherwise falls back to simple local embedding.
    """
    if _has_st:
        try:
            return sentence_transformers_embed(texts, model_name=model_name)
        except Exception:
            return [simple_embedding(t or '', dim=dim) for t in texts]
    return [simple_embedding(t or '', dim=dim) for t in texts]

