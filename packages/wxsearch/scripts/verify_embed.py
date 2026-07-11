#!/usr/bin/env python3
"""Real-machine verification for wxsearch.embed._default_embed_fn (fastembed-backed).

Not a unit test (no fakes) — fastembed downloads (or reuses) the real
bge-small-zh-v1.5 ONNX by model-name, runs real inference on real Chinese
sentences, and checks the embeddings are semantically sane: two weather
sentences should be more similar to each other than either is to an unrelated
"pay my credit card" sentence.

Usage:
    <venv>/bin/python3 packages/wxsearch/scripts/verify_embed.py [model_dir]

model_dir's basename must be an embedding model id in wxsearch.embed._FE
(default: a cache dir named bge-small-zh-v1.5). fastembed caches the ONNX there.
"""
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # packages/wxsearch
    from wxsearch.embed import _default_embed_fn, l2_normalize

    if len(sys.argv) > 1:
        model_dir = Path(sys.argv[1])
    else:
        model_dir = Path.home() / ".cache" / "wxsearch-verify" / "bge-small-zh-v1.5"
    model_dir.mkdir(parents=True, exist_ok=True)   # fastembed downloads the model here

    texts = ["今天天气很好", "天气不错", "我要还信用卡"]
    raw = _default_embed_fn(model_dir, texts)
    print("raw shape:", raw.shape, "dtype:", raw.dtype)
    assert raw.shape == (3, 512), "expected (3, 512), got %s" % (raw.shape,)
    assert raw.dtype.name == "float32"

    vecs = l2_normalize(raw)
    cos01 = float(vecs[0] @ vecs[1])
    cos02 = float(vecs[0] @ vecs[2])
    print("cos(今天天气很好, 天气不错)   = %.6f" % cos01)
    print("cos(今天天气很好, 我要还信用卡) = %.6f" % cos02)

    assert cos01 > cos02, (
        "semantic check FAILED: similar sentences should cosine higher than "
        "dissimilar ones (cos01=%.6f, cos02=%.6f)" % (cos01, cos02))
    print("OK: semantic ordering correct (cos01 > cos02)")


if __name__ == "__main__":
    main()
