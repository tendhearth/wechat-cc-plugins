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


def _default_embed_fn(model_dir: Path, texts):
    # VERIFY-AGAINST-REAL-MODEL: run the resolved embedding model (bge/BGE-M3) via ONNX Runtime
    # (tokenize -> onnxruntime InferenceSession -> mean-pool -> return (n, dim) float32).
    # Isolated here so the pipeline is fully testable with an injected fake.
    import onnxruntime  # noqa: F401  (real impl pinned when the model is chosen)
    raise NotImplementedError("OnnxEmbedRunner default embed_fn: wire ONNX Runtime for the chosen model")


class OnnxEmbedRunner:
    def __init__(self, model_manager, embed_fn=None):
        spec = model_manager.resolve("embedding")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("embedding"))
        self._embed_fn = embed_fn or _default_embed_fn

    def embed(self, texts) -> np.ndarray:
        raw = self._embed_fn(self._model_dir, list(texts))
        return l2_normalize(raw)
