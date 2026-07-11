import os

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


# --- real-machine verification (real fastembed model, real Chinese semantics) ---
# Requires network on first run (fastembed downloads/caches bge-small-zh-v1.5 ONNX,
# ~90 MB, into the given model_dir). Opt-in — run explicitly with `-m integration`
# when verifying real inference end-to-end.

@pytest.mark.integration
def test_default_embed_fn_real_model_chinese_semantics(tmp_path):
    """Real embedding on real Chinese text: similar sentences must cosine higher
    than dissimilar ones. Fails loudly if the model/mapping is wrong, even though
    the fake-injected tests above would stay green."""
    if os.environ.get("WXSEARCH_SKIP_INTEGRATION"):
        pytest.skip("WXSEARCH_SKIP_INTEGRATION set")
    model_dir = tmp_path / "bge-small-zh-v1.5"      # dir name -> _FE key; fastembed caches here
    model_dir.mkdir()

    texts = ["今天天气很好", "天气不错", "我要还信用卡"]
    raw = _default_embed_fn(model_dir, texts)
    assert raw.shape == (3, 512)
    assert raw.dtype == np.float32

    vecs = l2_normalize(raw)
    cos_similar = float(vecs[0] @ vecs[1])
    cos_dissimilar = float(vecs[0] @ vecs[2])
    assert cos_similar > cos_dissimilar, (
        "cos(similar)=%.6f should exceed cos(dissimilar)=%.6f" % (cos_similar, cos_dissimilar))
