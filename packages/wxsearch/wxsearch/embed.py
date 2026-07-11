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


# Module-level cache: (tokenizer, onnxruntime session) keyed by model_dir, so repeated
# calls to _default_embed_fn (e.g. per-batch indexing) don't reload the tokenizer/model
# from disk each time.
_SESSION_CACHE: dict = {}


def _onnx_model_path(model_dir: Path) -> Path:
    # Xenova-style HF exports sometimes nest the artifact under onnx/model.onnx,
    # sometimes flatten it at the repo root as model.onnx. Handle both.
    flat = model_dir / "model.onnx"
    nested = model_dir / "onnx" / "model.onnx"
    if flat.exists():
        return flat
    if nested.exists():
        return nested
    raise FileNotFoundError(
        "no model.onnx found under %s (checked %s and %s)" % (model_dir, flat, nested))


def _load_session(model_dir: Path):
    key = str(model_dir)
    cached = _SESSION_CACHE.get(key)
    if cached is not None:
        return cached

    from tokenizers import Tokenizer
    import onnxruntime as ort

    tok = Tokenizer.from_file(str(Path(model_dir) / "tokenizer.json"))
    tok.enable_padding()
    tok.enable_truncation(max_length=512)

    sess = ort.InferenceSession(str(_onnx_model_path(model_dir)), providers=["CPUExecutionProvider"])

    _SESSION_CACHE[key] = (tok, sess)
    return tok, sess


def _default_embed_fn(model_dir: Path, texts):
    # Real ONNX inference: tokenize -> onnxruntime InferenceSession -> CLS-pool ->
    # return (n, dim) float32, un-normalized (OnnxEmbedRunner.embed L2-normalizes).
    # Isolated here so the pipeline is fully testable with an injected fake.
    tok, sess = _load_session(model_dir)

    enc = tok.encode_batch(list(texts))
    input_ids = np.array([e.ids for e in enc], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    token_type_ids = np.array([e.type_ids for e in enc], dtype=np.int64)

    available = {"input_ids": input_ids, "attention_mask": attention_mask,
                 "token_type_ids": token_type_ids}
    feeds = {name: available[name] for name in (i.name for i in sess.get_inputs())
             if name in available}

    outputs = sess.run(None, feeds)
    last_hidden_state = outputs[0]   # first output == last_hidden_state for this model

    # CLS pooling (bge-small-zh-v1.5's 1_Pooling/config.json is CLS, not mean-pool).
    emb = np.asarray(last_hidden_state[:, 0, :], dtype=np.float32)
    return emb


class OnnxEmbedRunner:
    def __init__(self, model_manager, embed_fn=None):
        spec = model_manager.resolve("embedding")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("embedding"))
        self._embed_fn = embed_fn or _default_embed_fn

    def embed(self, texts) -> np.ndarray:
        raw = self._embed_fn(self._model_dir, list(texts))
        return l2_normalize(raw)
