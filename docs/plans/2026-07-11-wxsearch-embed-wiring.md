# wxsearch Embedding Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire wxsearch's one unwired seam (`embed.py` `_default_embed_fn`) to real local Chinese embeddings via fastembed, so `index_update` + semantic search work on real data.

**Architecture:** fastembed does the mechanism (fetch + run the ONNX embedding model by model-name, cache in the state dir, correct pooling/normalization internally); model-manager keeps the tier policy (`resolve`/`set_model`) via zero-URL marker artifacts. The `embed_fn(model_dir, texts)` boundary signature is unchanged — the real fn derives the model id from `Path(model_dir).name` and maps it to a fastembed model name — so every existing FakeEmbedder test is untouched.

**Tech Stack:** Python 3.12, fastembed (pulls onnxruntime + tokenizers + huggingface-hub), numpy, the sibling model-manager.

## Global Constraints

- fastembed for BOTH tiers; model-manager keeps tier policy via **zero-URL** embedding artifacts (`source_urls=[]` → `download.ensure` `mkdir`s a marker dir + writes `.done`, no download). Light = `bge-small-zh-v1.5` (512d, verify first); high = `jina-embeddings-v2-base-zh` (768d).
- `embed_fn(model_dir, texts)` signature UNCHANGED. The `mid not in _FE` `ValueError` MUST precede `from fastembed import` (so it's testable without fastembed + gives a clear error on an unmapped model). `OnnxEmbedRunner.embed` already `l2_normalize`s the output — do not add normalization to `embed_fn`.
- Do NOT break existing tests. Do NOT add any pytest that downloads/runs a real fastembed model — the real embedding is proven by the manual VERIFY-AGAINST-REAL section, not CI.
- `fastembed>=0.7` added to wxsearch `pyproject.toml` + installed by `setup.py`.
- Tests: out-of-repo venv python `/private/tmp/claude-501/-Users-nategu-mac-company-Documents-wxvault/96e8faa0-41a2-456b-88da-94b4b9e44cd8/scratchpad/pyv312/bin/python` (has pytest+numpy+zstandard+fastembed). Run from the relevant package dir via `-m pytest`. NEVER a repo venv, NEVER `pip install -e`, NEVER `git add -A`/`.`, NEVER create `tests/__init__.py`.

---

### Task 1: model-manager registry — zero-URL embedding artifacts + high→jina

**Files:**
- Modify: `packages/model-manager/model_manager/registry.py` (the embedding block)
- Modify: `packages/model-manager/tests/test_registry.py` (`test_bge_small_zh_resolves_to_onnx_source`)
- Modify: `packages/model-manager/tests/test_manager.py` (`test_high_preset_switches_all`)

**Interfaces:**
- Produces: `for_capability_tier("embedding","light").id == "bge-small-zh-v1.5"` (zero-URL); `for_capability_tier("embedding","high").id == "jina-embeddings-v2-base-zh"` (zero-URL). Both `runtime=="onnx"`, `artifact_for("any").source_urls == []`.

- [ ] **Step 1: Update the two coupled tests first (they will fail until the registry changes)**

In `packages/model-manager/tests/test_registry.py`, replace the whole `test_bge_small_zh_resolves_to_onnx_source` function with:
```python
def test_bge_small_zh_is_zero_url_fastembed_managed():
    # Embedding models are fetched by fastembed by model-NAME from its own catalog,
    # so model-manager does not download them — the artifact is a zero-URL marker
    # (ensure() just mkdirs the dir). model-manager still owns the tier CHOICE.
    spec = for_capability_tier("embedding", "light")
    assert spec is not None
    assert spec.id == "bge-small-zh-v1.5"
    assert spec.runtime == "onnx"
    art = spec.artifact_for("any")
    assert art is not None
    assert art.source_urls == []
```

In `packages/model-manager/tests/test_manager.py`, in `test_high_preset_switches_all`, change the embedding assertion:
```python
    assert mm.resolve("embedding").id == "jina-embeddings-v2-base-zh"
```
(Leave `test_per_capability_override_wins`'s `assert mm.resolve("embedding").id == "bge-small-zh-v1.5"` unchanged.)

- [ ] **Step 2: Run the two tests to verify they FAIL against the current registry**

Run: `cd packages/model-manager && <venv>/bin/python -m pytest tests/test_registry.py::test_bge_small_zh_is_zero_url_fastembed_managed tests/test_manager.py::test_high_preset_switches_all -v`
Expected: FAIL — light still has Xenova URLs (`art.source_urls == []` fails); high still resolves to `bge-m3`.

- [ ] **Step 3: Edit the registry embedding block**

In `packages/model-manager/model_manager/registry.py`, replace the entire `# --- embedding ---` block (the NOTE comment + both embedding `ModelSpec`s) with:
```python
    # --- embedding ---
    # Embedding models run through fastembed (see wxsearch/embed.py), which fetches
    # them by model-NAME from its own catalog and handles tokenize/pool/normalize.
    # So model-manager does NOT download embedding files: artifacts are zero-URL
    # markers (ensure() just mkdirs the dir) and model-manager owns only the tier
    # CHOICE (resolve/set_model). wxsearch maps these ids -> fastembed model names.
    ModelSpec(
        id="bge-small-zh-v1.5", capability="embedding", tier="light", runtime="onnx",
        artifacts=(
            Artifact("any", [], size_mb=100),
        ),
    ),
    ModelSpec(
        id="jina-embeddings-v2-base-zh", capability="embedding", tier="high", runtime="onnx",
        artifacts=(
            Artifact("any", [], size_mb=640),
        ),
    ),
```

- [ ] **Step 4: Run the two updated tests + the whole model-manager suite**

Run: `cd packages/model-manager && <venv>/bin/python -m pytest tests/ -q`
Expected: PASS (41 passed — the 2 edited tests now pass, nothing else regressed).

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/model_manager/registry.py packages/model-manager/tests/test_registry.py packages/model-manager/tests/test_manager.py
git commit -m "feat(model-manager): embedding tiers zero-URL (fastembed-managed); high -> jina-embeddings-v2-base-zh"
```

---

### Task 2: wxsearch embed.py — real fastembed runner + deps

**Files:**
- Modify: `packages/wxsearch/wxsearch/embed.py` (replace `_default_embed_fn`, add `_FE` + `_cache`)
- Modify: `packages/wxsearch/pyproject.toml` (add `fastembed>=0.7`)
- Modify: `packages/wxsearch/setup.py` (install fastembed)
- Create: `packages/wxsearch/tests/test_embed_real.py`

**Interfaces:**
- Consumes: model-manager `for_capability_tier` (Task 1), via `wxsearch/_deps.ensure_model_manager()`.
- Produces: `wxsearch.embed._FE` (dict model_id → fastembed name), `_default_embed_fn(model_dir, texts) -> np.ndarray` (raises `ValueError` for an unmapped model id before importing fastembed). `EmbedRunner`, `l2_normalize`, `OnnxEmbedRunner` unchanged.

- [ ] **Step 1: Write the failing tests**

Create `packages/wxsearch/tests/test_embed_real.py`:
```python
import pytest

from wxsearch.embed import _default_embed_fn, _FE


def test_default_embed_fn_unmapped_model_raises(tmp_path):
    # An embedding model id with no fastembed mapping must fail clearly BEFORE any
    # fastembed import/download — so this runs even without fastembed installed.
    d = tmp_path / "nope-model"
    d.mkdir()
    with pytest.raises(ValueError, match="no fastembed mapping"):
        _default_embed_fn(d, ["hi"])


def test_fe_map_covers_every_registry_embedding_tier():
    # Guards the "added/renamed a tier, forgot the fastembed mapping" drift.
    from wxsearch._deps import ensure_model_manager
    ensure_model_manager()
    from model_manager.registry import for_capability_tier
    for tier in ("light", "high"):
        spec = for_capability_tier("embedding", tier)
        assert spec is not None
        assert spec.id in _FE, "embedding %s tier id %r missing from wxsearch.embed._FE" % (tier, spec.id)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/wxsearch && <venv>/bin/python -m pytest tests/test_embed_real.py -v`
Expected: FAIL — `_FE` doesn't exist yet (`ImportError: cannot import name '_FE'`), and `_default_embed_fn` currently raises `NotImplementedError`, not `ValueError`.

- [ ] **Step 3: Replace `_default_embed_fn` and add `_FE` + `_cache` in embed.py**

In `packages/wxsearch/wxsearch/embed.py`, replace the existing `_default_embed_fn` function (the one importing onnxruntime and raising NotImplementedError) with the following, and add `_FE`/`_cache` just above it. Leave `EmbedRunner`, `l2_normalize`, and `OnnxEmbedRunner` exactly as they are:
```python
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
```
(`Path` is already imported at the top of `embed.py` — `from pathlib import Path`.)

- [ ] **Step 4: Run the new tests + the whole wxsearch suite**

Run: `cd packages/wxsearch && <venv>/bin/python -m pytest tests/ -q`
Expected: PASS (all existing FakeEmbedder/pipeline tests + the 2 new `test_embed_real.py` tests). No test downloads a model.

- [ ] **Step 5: Add the fastembed dependency**

In `packages/wxsearch/pyproject.toml`, add `"fastembed>=0.7"` to the `dependencies` list (keep numpy + zstandard). It becomes e.g.:
```toml
dependencies = ["numpy>=1.24", "zstandard>=0.22", "fastembed>=0.7"]
```
(Match the exact existing list — only ADD the fastembed entry; do not drop the others.)

In `packages/wxsearch/setup.py`, add a fastembed install block mirroring the existing numpy one. After the numpy install block, add:
```python
    try:
        import fastembed  # noqa: F401
    except ImportError:
        print("安装依赖：fastembed（本地嵌入运行时，含 onnxruntime）")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "fastembed"])
        if r.returncode != 0:
            sys.exit("!! fastembed 安装失败")
```

- [ ] **Step 6: Re-run the wxsearch suite (deps change shouldn't affect tests) + commit**

Run: `cd packages/wxsearch && <venv>/bin/python -m pytest tests/ -q`
Expected: PASS (unchanged count from Step 4).

```bash
git add packages/wxsearch/wxsearch/embed.py packages/wxsearch/tests/test_embed_real.py packages/wxsearch/pyproject.toml packages/wxsearch/setup.py
git commit -m "feat(wxsearch): wire real embeddings via fastembed (bge-small-zh / jina-zh)"
```

---

## VERIFY-AGAINST-REAL (controller runs this after Task 2 — NOT a subagent task, NOT CI)

This is the acceptance gate that declares the embedding "wired". It downloads the real model (~90MB, once) and runs against the user's real decrypted WeChat data. Run from `packages/wxsearch` with the venv python; point `WXVAULT_STATE_DIR` at a scratch dir that symlinks the real `out/decrypted` (read-only reads; index/vectors written to scratch):

```bash
SCRATCH=<scratchpad>/realval-embed
rm -rf "$SCRATCH"; mkdir -p "$SCRATCH/out"
ln -s /Users/nategu_mac_company/Documents/wxvault/out/decrypted "$SCRATCH/out/decrypted"
```

Then, from `packages/wxsearch`, drive the real pipeline via the module API (light tier resolves by default):
1. Build `OnnxEmbedRunner(ModelManager(SCRATCH))` (its `_default_embed_fn` now real), run `search.index_update(SCRATCH, runner)` → fastembed downloads bge-small-zh once and embeds the real messages. Assert `index_update` returns `{"indexed": >0, ...}` and `GraphStore`-less: confirm `IndexStore(SCRATCH).load_vectors()` returns a matrix with **dim == 512** and finite values.
2. Run `search.search(SCRATCH, query, runner)` with a **paraphrase / synonym query whose exact words do NOT appear** in a message you know exists (e.g. a semantically-related phrase to a real conversation topic). Assert `out["vectors_stale"] is False` and that a relevant message appears in `out["results"]` — i.e. the vector path surfaced a hit BM25 alone would miss (sanity-compare against `keyword_search` returning nothing for that exact query).

**Acceptance:** dim 512 + finite vectors + a semantic hit that keyword search misses. Only then: re-enable the plugin — `cd ~/Documents/wechat-cc && bun cli.ts plugin enable wxsearch` (restart daemon to load).

If the semantic hit is weak/absent, do NOT silently pass — report it; it may indicate a model/pooling mismatch worth investigating before declaring wired.

---

## Self-Review

**1. Spec coverage:** fastembed both tiers + model-manager tier policy via zero-URL → Task 1 (registry) + Task 2 (`_FE` map) ✓; light bge-small-zh 512d / high jina-zh 768d → Task 1 ids + Task 2 `_FE` ✓; embed_fn signature unchanged, fakes intact → Task 2 replaces only `_default_embed_fn` ✓; ValueError-before-fastembed-import → Task 2 Step 3 order + test 1 ✓; map↔registry consistency test → Task 2 test 2 ✓; deps fastembed in pyproject+setup → Task 2 Steps 5 ✓; coupled model-manager tests updated → Task 1 ✓; no CI model download → tests avoid it, real embed is the VERIFY section ✓; dim-switch via existing reindex path → unchanged, noted ✓; VERIFY-AGAINST-REAL on real data → dedicated section ✓.

**2. Placeholder scan:** No TBD/TODO. Every code step has complete code. The VERIFY section describes concrete asserts (dim 512, finite, semantic hit) rather than vague "test it".

**3. Type consistency:** `_FE` keys (`"bge-small-zh-v1.5"`, `"jina-embeddings-v2-base-zh"`) exactly match the Task 1 registry ids. `_default_embed_fn(model_dir, texts)` signature matches the unchanged `OnnxEmbedRunner.embed` call site. `for_capability_tier("embedding", tier).id` (Task 2 test) matches the registry API used in test_manager/test_registry. `art.source_urls == []` assertion matches the `Artifact("any", [], ...)` zero-URL edit.

**Out of scope (this plan):** wxmedia ASR wiring (next), reranker, embedding-model bake-off (swap high tier later via registry id + one `_FE` line), model-manager repo-aware fetcher (fastembed makes it unnecessary).
