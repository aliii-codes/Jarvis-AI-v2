"""Local text embeddings (fastembed + ONNX, no PyTorch, nothing leaves the computer).

Used for meaning-based search in memory and documents. The model (~65 MB) downloads once into
Data/models on first use. If it can't load (e.g. offline on first run), callers fall back to keywords.
"""
import hashlib
import logging
import threading

import numpy as np
from langchain_core.embeddings import Embeddings

from . import config

MODEL = "BAAI/bge-small-en-v1.5"
DIMS = 384
MODELS_DIR = config.DATA_DIR / "models"  # fixed at import, so tests that redirect DATA_DIR reuse the download

_model = None
_failed = False
_lock = threading.Lock()


def _load():
    global _model, _failed
    with _lock:
        if _model is None and not _failed:
            try:
                from fastembed import TextEmbedding
                _model = TextEmbedding(MODEL, cache_dir=str(MODELS_DIR))
            except Exception as e:  # no network on first run, broken install...
                logging.warning(f"Embedding model unavailable, using keyword search: {e}")
                _failed = True
    return _model


def available() -> bool:
    return _load() is not None


def warm_up() -> bool:
    """Load (and on first run download) the model ahead of time, e.g. from a background thread at startup."""
    return available()


class LocalEmbeddings(Embeddings):
    """LangChain Embeddings over the local model, for LangGraph's store index."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = _load()
        if model is None:
            raise RuntimeError("embedding model unavailable")
        return [v.tolist() for v in model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        model = _load()
        if model is None:
            raise RuntimeError("embedding model unavailable")
        return next(iter(model.query_embed(text))).tolist()


class HashEmbeddings(Embeddings):
    """Deterministic bag-of-words vectors for tests: no model, no network. Shared words -> similar vectors."""

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(DIMS)
        for word in text.lower().split():
            v[int(hashlib.md5(word.strip(".,?!").encode()).hexdigest(), 16) % DIMS] += 1
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# The embeddings in use; tests swap in HashEmbeddings.
current: Embeddings = LocalEmbeddings()


def index_config() -> dict | None:
    """LangGraph store index settings, or None if no embeddings are available (keyword search only)."""
    if isinstance(current, LocalEmbeddings) and not available():
        return None
    return {"dims": DIMS, "embed": current, "fields": ["text"]}
