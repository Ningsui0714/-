"""
Embedding service with pluggable backends.

Backends:
  - local: sentence-transformers (gte-small, 384d, default)
  - api:   OpenAI-compatible API (e.g., DeepSeek, OpenAI)
  
Configure via .env: EMBEDDING_BACKEND=local|api
"""
import os
import json
import numpy as np
from typing import List, Optional

from app.core.config import settings

EMBEDDING_BACKEND = getattr(settings, "embedding_backend", "local")

# ── Local Backend (sentence-transformers) ──

_model = None

def _get_local_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("TaylorAI/gte-small")
    return _model


# ── API Backend (OpenAI-compatible) ──

_api_client = None

def _get_api_client():
    global _api_client
    if _api_client is None:
        from openai import AsyncOpenAI
        # Use embedding-specific settings if provided, fallback to LLM settings
        api_key = settings.embedding_api_key or settings.llm_api_key
        base_url = settings.embedding_base_url or settings.llm_base_url
        _api_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _api_client

EMBEDDING_API_MODEL = getattr(settings, "embedding_model", "text-embedding-ada-002")


# ── Unified Interface ──

def embed_text(text: str) -> List[float]:
    """Embed a single text. Returns vector (384d local, configurable via API)."""
    if EMBEDDING_BACKEND == "api":
        import asyncio
        client = _get_api_client()
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(
            client.embeddings.create(model=EMBEDDING_API_MODEL, input=text)
        )
        return resp.data[0].embedding
    else:
        model = _get_local_model()
        emb = model.encode(text, normalize_embeddings=True)
        return emb.tolist()


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Embed multiple texts in batch."""
    if EMBEDDING_BACKEND == "api":
        import asyncio
        client = _get_api_client()
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        resp = loop.run_until_complete(
            client.embeddings.create(model=EMBEDDING_API_MODEL, input=texts)
        )
        sorted_data = sorted(resp.data, key=lambda x: x.index)
        return [d.embedding for d in sorted_data]
    else:
        model = _get_local_model()
        embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [e.tolist() for e in embs]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity (assumes L2-normalized vectors for dot product)."""
    return float(np.dot(a, b))


# ── Disk Cache ──

EMBEDDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
CACHE_FILE = os.path.join(EMBEDDINGS_DIR, "chunk_embeddings.json")


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def get_cached_embedding(chunk_id: int) -> Optional[List[float]]:
    cache = load_cache()
    return cache.get(f"chunk-{chunk_id}")


def cache_embedding(chunk_id: int, embedding: List[float]):
    cache = load_cache()
    cache[f"chunk-{chunk_id}"] = embedding
    save_cache(cache)
