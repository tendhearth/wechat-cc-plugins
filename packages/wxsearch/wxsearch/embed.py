"""The embedding runner boundary. Real ONNX inference is isolated in one place."""
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbedRunner(Protocol):
    model_id: str
    def embed(self, texts): ...   # list[str] -> np.ndarray (n, dim) L2-normalized float32


def l2_normalize(mat: np.ndarray) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0            # avoid divide-by-zero (zero vector stays zero)
    return (mat / norms).astype(np.float32)


_FE = {"bge-small-zh-v1.5": "BAAI/bge-small-zh-v1.5",
       "jina-embeddings-v2-base-zh": "jinaai/jina-embeddings-v2-base-zh"}
_cache = {}   # model_id -> TextEmbedding (loading is expensive; reuse within a process)


def _default_embed_fn(model_dir, texts):
    # fastembed fetches the ONNX model by name (into cache_dir=model_dir, once) and
    # handles tokenize -> ONNX session -> pooling -> normalize. The map check runs
    # BEFORE the fastembed import so an unmapped model errors clearly without it.
    mid = Path(model_dir).name
    if mid not in _FE:
        raise ValueError("wxsearch: no fastembed mapping for embedding model %r" % mid)
    from fastembed import TextEmbedding
    import numpy as np
    if mid not in _cache:
        _cache[mid] = TextEmbedding(_FE[mid], cache_dir=str(model_dir))
    return np.array(list(_cache[mid].embed(list(texts))), dtype=np.float32)


class OnnxEmbedRunner:
    def __init__(self, model_manager, embed_fn=None):
        spec = model_manager.resolve("embedding")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("embedding"))
        self._embed_fn = embed_fn or _default_embed_fn

    def embed(self, texts) -> np.ndarray:
        raw = self._embed_fn(self._model_dir, list(texts))
        return l2_normalize(raw)
