import os
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from wxsearch.embed import l2_normalize, OnnxEmbedRunner, _default_embed_fn

def test_l2_normalize_rows_unit_length():
    m = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)
    n = l2_normalize(m)
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0)
    assert n.dtype == np.float32

def test_l2_normalize_zero_row_safe():
    m = np.array([[0.0, 0.0]], dtype=np.float32)
    n = l2_normalize(m)          # must not divide by zero / produce NaN
    assert not np.isnan(n).any()

class FakeMM:
    def resolve(self, cap):
        class S: id = "bge-small-zh-v1.5"; runtime = "onnx"
        return S()
    def ensure(self, cap, **kw):
        from pathlib import Path
        return Path("/models/embedding/bge-small-zh-v1.5")

def test_runner_model_id_and_normalizes():
    captured = {}
    def fake_embed(model_dir, texts):
        captured["model_dir"] = str(model_dir); captured["texts"] = texts
        return np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)  # not normalized
    r = OnnxEmbedRunner(FakeMM(), embed_fn=fake_embed)
    assert r.model_id == "bge-small-zh-v1.5"
    out = r.embed(["你好", "世界"])
    assert out.shape == (2, 2)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)   # runner L2-normalizes
    assert captured["texts"] == ["你好", "世界"]
    assert captured["model_dir"].endswith("bge-small-zh-v1.5")


# --- real-machine verification (real ONNX model, real Chinese semantics) ---
# Requires network on first run (downloads/caches Xenova/bge-small-zh-v1.5 ONNX,
# ~95 MB) and onnxruntime + tokenizers installed. Not part of the default fast
# suite's guarantees beyond "collects cleanly" -- run explicitly with
# `-m integration` when verifying real inference end-to-end.

_HF_REPO_BASE = "https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main"
_HF_FILES = ["tokenizer.json", "vocab.txt", "config.json", "onnx/model.onnx"]


def _ensure_real_model_dir() -> Path:
    cache = Path.home() / ".cache" / "wxsearch-verify" / "bge-small-zh-v1.5"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "onnx").mkdir(exist_ok=True)
    for rel in _HF_FILES:
        out = cache / rel
        if out.exists() and out.stat().st_size > 0:
            continue
        with urllib.request.urlopen("%s/%s" % (_HF_REPO_BASE, rel), timeout=120) as r, \
                open(out, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    return cache


@pytest.mark.integration
def test_default_embed_fn_real_model_chinese_semantics():
    """Real ONNX inference on real Chinese text: similar sentences must cosine
    higher than dissimilar ones. This is the actual point of Task 2 -- it fails
    loudly if pooling/tokenizer/input-name wiring is wrong (e.g. mean-pool
    instead of CLS), even though the fake-injected tests above would stay green."""
    if os.environ.get("WXSEARCH_SKIP_INTEGRATION"):
        pytest.skip("WXSEARCH_SKIP_INTEGRATION set")
    model_dir = _ensure_real_model_dir()

    texts = ["今天天气很好", "天气不错", "我要还信用卡"]
    raw = _default_embed_fn(model_dir, texts)
    assert raw.shape == (3, 512)
    assert raw.dtype == np.float32

    vecs = l2_normalize(raw)
    cos_similar = float(vecs[0] @ vecs[1])
    cos_dissimilar = float(vecs[0] @ vecs[2])
    assert cos_similar > cos_dissimilar, (
        "cos(similar)=%.6f should exceed cos(dissimilar)=%.6f" % (cos_similar, cos_dissimilar))
