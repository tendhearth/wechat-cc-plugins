#!/usr/bin/env python3
"""Real-machine verification for wxsearch.embed._default_embed_fn.

Not a unit test (no fakes) — downloads (or reuses) the real Xenova/bge-small-zh-v1.5
ONNX export, runs real inference on real Chinese sentences, and checks that the
resulting embeddings are semantically sane: two weather sentences should be more
similar to each other than either is to an unrelated "pay my credit card" sentence.

Usage:
    <venv>/bin/python3 packages/wxsearch/scripts/verify_embed.py [model_dir]

If model_dir is omitted, downloads the model into a cache dir under
~/.cache/wxsearch-verify/bge-small-zh-v1.5 (skips download if already present).
"""
import sys
import urllib.request
from pathlib import Path

REPO_BASE = "https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main"
FILES = ["tokenizer.json", "vocab.txt", "config.json", "onnx/model.onnx"]


def _download_model(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "onnx").mkdir(exist_ok=True)
    for rel in FILES:
        out = dest / rel
        if out.exists() and out.stat().st_size > 0:
            continue
        url = "%s/%s" % (REPO_BASE, rel)
        print("downloading %s -> %s" % (url, out))
        with urllib.request.urlopen(url, timeout=120) as r, open(out, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    return dest


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # packages/wxsearch
    from wxsearch.embed import _default_embed_fn, l2_normalize

    if len(sys.argv) > 1:
        model_dir = Path(sys.argv[1])
    else:
        model_dir = _download_model(Path.home() / ".cache" / "wxsearch-verify" / "bge-small-zh-v1.5")

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
        "dissimilar ones (cos01=%.6f, cos02=%.6f) -- check pooling/tokenizer/input names"
        % (cos01, cos02))
    print("OK: semantic ordering correct (cos01 > cos02)")


if __name__ == "__main__":
    main()
