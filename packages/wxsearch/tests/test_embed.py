import numpy as np
from wxsearch.embed import l2_normalize, OnnxEmbedRunner

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
