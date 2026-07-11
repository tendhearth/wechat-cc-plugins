# wxmedia ASR Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire wxmedia's one unwired seam (`asr.py`'s runner) to real local Chinese speech-to-text via faster-whisper, so `voice_backfill` transcribes real WeChat voice → searchable text.

**Architecture:** faster-whisper does the mechanism (fetch + run the Whisper model by name, cache in the state dir, CPU int8, `language="zh"`); model-manager keeps the tier policy (`resolve`/`set_model`) via zero-URL marker artifacts. An injectable `transcribe_fn` keeps the runner unit-testable without a download. The `AsrRunner` Protocol + SILK pipeline (pilk) are unchanged.

**Tech Stack:** Python 3.12, faster-whisper (pulls ctranslate2 + av + tokenizers), pilk (already a dep), the sibling model-manager.

## Global Constraints

- faster-whisper for BOTH tiers; model-manager keeps tier policy via **zero-URL** asr artifacts (`source_urls=[]` → `download.ensure` `mkdir`s a marker dir + writes `.done`, no download). Light = `whisper-small` (verify first); high = `whisper-large-v3`.
- `AsrRunner.transcribe(wav_path)->str` boundary UNCHANGED. The `model_id not in _WHISPER` `ValueError` MUST precede `from faster_whisper import` (testable without faster-whisper + clear error on unmapped model). `language="zh"` pinned; `device="cpu"`, `compute_type="int8"`.
- Do NOT break existing tests (pipeline/transcribe_all tests inject a fake `AsrRunner`). Do NOT add any pytest that installs or downloads a real faster-whisper model — the real ASR is proven by the manual VERIFY-AGAINST-REAL section.
- SILK decode (`wxmedia/silk.py`, pilk) + the transcribe pipeline are untouched.
- `faster-whisper>=1.0` added to wxmedia `pyproject.toml` + installed by `setup.py`.
- Tests: out-of-repo venv python `/private/tmp/claude-501/-Users-nategu-mac-company-Documents-wxvault/96e8faa0-41a2-456b-88da-94b4b9e44cd8/scratchpad/pyv312/bin/python` (has pytest+numpy+zstandard+fastembed; faster-whisper NOT installed — the unit tests here don't need it). Run from the relevant package dir via `-m pytest`. NEVER a repo venv, NEVER `pip install -e`, NEVER `git add -A`/`.`, NEVER create `tests/__init__.py`.

---

### Task 1: model-manager registry — zero-URL asr artifacts + light→whisper-small

**Files:**
- Modify: `packages/model-manager/model_manager/registry.py` (the asr block)
- Modify: `packages/model-manager/tests/test_registry.py` (2 asr tests)
- Modify: `packages/model-manager/tests/test_manager.py` (light asr assertion)
- Modify: `packages/model-manager/tests/test_config.py` (asr override id)

**Interfaces:**
- Produces: `for_capability_tier("asr","light").id == "whisper-small"` (zero-URL); `for_capability_tier("asr","high").id == "whisper-large-v3"` (zero-URL). Both `runtime=="faster-whisper"`, `artifact_for("any").source_urls == []`.

- [ ] **Step 1: Update the four coupled tests first (they will fail until the registry changes)**

In `packages/model-manager/tests/test_registry.py`, replace `test_sensevoice_is_light_asr_and_cross_platform` and `test_asr_high_is_per_os_distinct` with:
```python
def test_whisper_small_is_zero_url_light_asr():
    # ASR models are fetched by faster-whisper by model-NAME from its own catalog,
    # so model-manager does not download them — the artifact is a zero-URL marker.
    spec = for_capability_tier("asr", "light")
    assert spec is not None
    assert spec.id == "whisper-small"
    assert spec.runtime == "faster-whisper"
    art = spec.artifact_for("any")
    assert art is not None
    assert art.source_urls == []


def test_whisper_large_is_zero_url_high_asr():
    spec = for_capability_tier("asr", "high")
    assert spec is not None
    assert spec.id == "whisper-large-v3"
    assert spec.runtime == "faster-whisper"
    art = spec.artifact_for("any")
    assert art is not None
    assert art.source_urls == []
```

In `packages/model-manager/tests/test_manager.py`, change the light-preset asr assertion (the one asserting `mm.resolve("asr").id == "sensevoice-small-q8"`) to:
```python
    assert mm.resolve("asr").id == "whisper-small"
```
(Leave the high-preset assertion `mm.resolve("asr").id == "whisper-large-v3"` unchanged.)

In `packages/model-manager/tests/test_config.py`, change both occurrences of `"sensevoice-small-q8"` (the `overrides={"asr": "sensevoice-small-q8"}` and its round-trip assert) to `"whisper-small"`.

- [ ] **Step 2: Run the updated tests to verify they FAIL against the current registry**

Run: `cd packages/model-manager && <venv>/bin/python -m pytest tests/test_registry.py::test_whisper_small_is_zero_url_light_asr tests/test_registry.py::test_whisper_large_is_zero_url_high_asr tests/test_manager.py -k asr tests/test_config.py -v`
Expected: FAIL — the registry still has `sensevoice-small-q8` + real URLs / per-OS artifacts.

- [ ] **Step 3: Edit the registry asr block**

In `packages/model-manager/model_manager/registry.py`, replace the entire `# --- asr ---` block (its NOTE/comment lines + both asr `ModelSpec`s — the `sensevoice-small-q8` light spec and the `whisper-large-v3` high spec) with:
```python
    # --- asr ---
    # ASR runs through faster-whisper (see wxmedia/asr.py), which fetches the Whisper
    # model by model-NAME from its own catalog and handles decode/inference. So
    # model-manager does NOT download asr files: artifacts are zero-URL markers
    # (ensure() just mkdirs the dir) and model-manager owns only the tier CHOICE
    # (resolve/set_model). wxmedia maps these ids -> faster-whisper model names.
    ModelSpec(
        id="whisper-small", capability="asr", tier="light", runtime="faster-whisper",
        artifacts=(
            Artifact("any", [], size_mb=500),
        ),
    ),
    ModelSpec(
        id="whisper-large-v3", capability="asr", tier="high", runtime="faster-whisper",
        artifacts=(
            Artifact("any", [], size_mb=3000),
        ),
    ),
```

- [ ] **Step 4: Run the whole model-manager suite**

Run: `cd packages/model-manager && <venv>/bin/python -m pytest tests/ -q`
Expected: PASS (41 passed — the 4 edited tests now pass, nothing else regressed).

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/model_manager/registry.py packages/model-manager/tests/test_registry.py packages/model-manager/tests/test_manager.py packages/model-manager/tests/test_config.py
git commit -m "feat(model-manager): asr tiers zero-URL (faster-whisper-managed); light -> whisper-small"
```

---

### Task 2: wxmedia asr.py — real faster-whisper runner + server + deps

**Files:**
- Modify: `packages/wxmedia/wxmedia/asr.py` (replace everything below the `AsrRunner` Protocol)
- Modify: `packages/wxmedia/wxmedia/server.py` (SenseVoiceRunner → FasterWhisperRunner)
- Modify: `packages/wxmedia/pyproject.toml` (add faster-whisper)
- Modify: `packages/wxmedia/setup.py` (install faster-whisper)
- Rewrite: `packages/wxmedia/tests/test_asr_runner.py`

**Interfaces:**
- Consumes: model-manager `for_capability_tier` (Task 1) via `wxmedia/_deps.ensure_model_manager()`.
- Produces: `wxmedia.asr.FasterWhisperRunner(model_manager, transcribe_fn=None)` (`AsrRunner`), `_default_transcribe(model_dir, model_id, wav_path) -> str` (raises `ValueError` for an unmapped id before importing faster-whisper), `_WHISPER` (dict model_id → faster-whisper name). `AsrRunner` Protocol unchanged.

- [ ] **Step 1: Write the failing tests (rewrite the file)**

Replace the entire contents of `packages/wxmedia/tests/test_asr_runner.py` with:
```python
import pytest

from wxmedia.asr import FasterWhisperRunner, _default_transcribe, _WHISPER


class FakeMM:
    def resolve(self, cap):
        class S:
            id = "whisper-small"
            runtime = "faster-whisper"
        return S()

    def ensure(self, cap, **kw):
        from pathlib import Path
        return Path("/models/asr/whisper-small")


def test_runner_model_id_and_delegates_to_fn():
    captured = {}

    def fake_fn(model_dir, model_id, wav_path):
        captured["args"] = (str(model_dir), model_id, wav_path)
        return "你好世界"

    r = FasterWhisperRunner(FakeMM(), transcribe_fn=fake_fn)
    assert r.model_id == "whisper-small"
    assert r.transcribe("/tmp/100.wav") == "你好世界"
    assert captured["args"] == ("/models/asr/whisper-small", "whisper-small", "/tmp/100.wav")


def test_default_transcribe_unmapped_model_raises(tmp_path):
    # An asr model id with no faster-whisper mapping must fail clearly BEFORE any
    # faster_whisper import — so this runs even without faster-whisper installed.
    d = tmp_path / "nope-model"
    d.mkdir()
    with pytest.raises(ValueError, match="no faster-whisper mapping"):
        _default_transcribe(d, "nope-model", "/tmp/x.wav")


def test_whisper_map_covers_every_registry_asr_tier():
    # Guards the "added/renamed a tier, forgot the faster-whisper mapping" drift.
    from wxmedia._deps import ensure_model_manager
    ensure_model_manager()
    from model_manager.registry import for_capability_tier
    for tier in ("light", "high"):
        spec = for_capability_tier("asr", tier)
        assert spec is not None
        assert spec.id in _WHISPER, "asr %s tier id %r missing from wxmedia.asr._WHISPER" % (tier, spec.id)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd packages/wxmedia && <venv>/bin/python -m pytest tests/test_asr_runner.py -v`
Expected: FAIL — `ImportError: cannot import name 'FasterWhisperRunner'` (asr.py still has SenseVoiceRunner/_parse_output).

- [ ] **Step 3: Replace the asr.py body below the Protocol**

In `packages/wxmedia/wxmedia/asr.py`, keep the module docstring, the `from typing import Protocol, runtime_checkable` import, the `AsrRunner` Protocol, and `from pathlib import Path`. Remove `import re`, `import subprocess`, `_parse_output`, `_default_runner_cmd`, and `SenseVoiceRunner`. The file becomes exactly:
```python
"""The ASR runner boundary. Concrete runners live behind this Protocol."""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AsrRunner(Protocol):
    model_id: str
    def transcribe(self, wav_path: str) -> str: ...


_WHISPER = {"whisper-small": "small", "whisper-large-v3": "large-v3"}
_cache = {}   # model_id -> WhisperModel (loading is expensive; reuse within a process)


def _default_transcribe(model_dir, model_id, wav_path):
    # faster-whisper fetches the model by name (into download_root=model_dir, once) and
    # decodes/infers. The map check runs BEFORE the import so an unmapped model errors
    # clearly without faster-whisper installed. language="zh" pinned (Whisper mis-detects
    # very short clips); CPU int8 for laptop footprint.
    if model_id not in _WHISPER:
        raise ValueError("wxmedia: no faster-whisper mapping for asr model %r" % model_id)
    from faster_whisper import WhisperModel
    if model_id not in _cache:
        _cache[model_id] = WhisperModel(_WHISPER[model_id], device="cpu",
                                        compute_type="int8", download_root=str(model_dir))
    segments, _info = _cache[model_id].transcribe(wav_path, language="zh")
    return "".join(s.text for s in segments).strip()


class FasterWhisperRunner:
    def __init__(self, model_manager, transcribe_fn=None):
        spec = model_manager.resolve("asr")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("asr"))
        self._fn = transcribe_fn or _default_transcribe

    def transcribe(self, wav_path):
        return self._fn(self._model_dir, self.model_id, wav_path)
```

- [ ] **Step 4: Run the new asr tests + the whole wxmedia suite**

Run: `cd packages/wxmedia && <venv>/bin/python -m pytest tests/ -q`
Expected: PASS (all existing pipeline/silk/store/server/deps tests + the 3 rewritten asr tests). No test installs faster-whisper.

- [ ] **Step 5: Point server.py at the new runner**

In `packages/wxmedia/wxmedia/server.py`, `main()` imports and constructs the old runner. Change the import `from .asr import SenseVoiceRunner` → `from .asr import FasterWhisperRunner`, and the construction `SenseVoiceRunner(manager)` → `FasterWhisperRunner(manager)`. (Grep `SenseVoiceRunner` in server.py to find the exact lines; there should be exactly two references — the import and the call inside the `transcribe` dep lambda. Change both. Nothing else in server.py.)

Verify no stale reference remains:
Run: `cd packages/wxmedia && grep -rn "SenseVoiceRunner\|_parse_output\|_default_runner_cmd" wxmedia/ tests/`
Expected: no matches.

- [ ] **Step 6: Add the faster-whisper dependency**

In `packages/wxmedia/pyproject.toml`, change `dependencies = ["pilk"]` to:
```toml
dependencies = ["pilk", "faster-whisper>=1.0"]
```

In `packages/wxmedia/setup.py`, after the existing pilk install block, add a faster-whisper block mirroring it:
```python
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("安装依赖：faster-whisper（本地语音转文字，含 ctranslate2 + av）")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper"])
        if r.returncode != 0:
            sys.exit("!! faster-whisper 安装失败")
```

- [ ] **Step 7: Re-run the wxmedia suite (deps/server change shouldn't affect it) + import check + commit**

Run: `cd packages/wxmedia && <venv>/bin/python -m pytest tests/ -q`
Expected: PASS (unchanged count from Step 4).
Run: `cd packages/wxmedia && PYTHONPATH=$(pwd) <venv>/bin/python -c "import wxmedia.server"`
Expected: no ImportError (`main()` not invoked on import; faster-whisper imported lazily inside `_default_transcribe`, not at module load).

```bash
git add packages/wxmedia/wxmedia/asr.py packages/wxmedia/wxmedia/server.py packages/wxmedia/tests/test_asr_runner.py packages/wxmedia/pyproject.toml packages/wxmedia/setup.py
git commit -m "feat(wxmedia): wire real ASR via faster-whisper (whisper-small / large-v3, zh)"
```

---

## VERIFY-AGAINST-REAL (controller runs this after Task 2 — NOT a subagent task, NOT CI)

The acceptance gate. Downloads `whisper-small` (~500MB, once) and transcribes real WeChat voice. Run from `packages/wxmedia` with the venv python (install faster-whisper into it first: `<venv>/bin/python -m pip install faster-whisper`).

1. **Real-clip sanity** — pull a few of the 214 real voice blobs from `/Users/nategu_mac_company/Documents/wxvault/out/decrypted/media_0.sqlite` `VoiceInfo(voice_data)`, decode each with `wxmedia.silk.to_wav` (pilk), transcribe with `FasterWhisperRunner(ModelManager(scratch))`. Assert each returns a non-empty string; eyeball that several are **plausible Chinese** (not gibberish, not English).
2. **Full pipeline** — point `WXVAULT_STATE_DIR` at a scratch dir symlinking the real `out/decrypted`, run `wxmedia.pipeline.transcribe_all(scratch, runner)` (what `voice_backfill` calls) → transcripts written to `${scratch}/wxmedia/derived.sqlite`. Query `DerivedStore` for a handful and spot-check.
3. **Watch the known Whisper failure mode** — hallucinated Chinese on silent/non-speech clips (spurious "谢谢观看" / "请点赞" / "字幕由…"). Count how many of the sampled transcripts are obvious hallucinations. If frequent (say >20%), do NOT silently pass — report it; the fix is `medium` tier (`_WHISPER["whisper-medium"]="medium"` + registry id, one line) or `transcribe(..., vad_filter=True)` in `_default_transcribe`.
4. **Acceptance:** plausible Chinese on real speech + hallucination rate acceptable. Only then: `cd ~/Documents/wechat-cc && bun cli.ts plugin enable wxmedia` (restart daemon to load). Bonus — wxsearch's `text_source` already joins wxmedia's `derived.sqlite` by server_id, so a subsequent wxsearch `reindex` makes voice messages semantically searchable too.

---

## Self-Review

**1. Spec coverage:** faster-whisper both tiers + model-manager tier policy via zero-URL → Task 1 (registry) + Task 2 (`_WHISPER`) ✓; light whisper-small / high whisper-large-v3 → Task 1 ids + Task 2 `_WHISPER` ✓; `AsrRunner.transcribe` unchanged, fakes/pipeline intact → Task 2 replaces only the runner internals ✓; ValueError-before-faster-whisper-import → Task 2 Step 3 order + test (b) ✓; language="zh" + cpu int8 → Task 2 `_default_transcribe` ✓; injectable transcribe_fn → Task 2 signature + test (a) ✓; map↔registry consistency → Task 2 test (c) ✓; SILK/pipeline unchanged → not touched ✓; server.py runner swap → Task 2 Step 5 ✓; deps faster-whisper in pyproject+setup → Task 2 Step 6 ✓; coupled model-manager tests updated → Task 1 ✓; no CI model download → tests avoid it, real ASR is the VERIFY section ✓; VERIFY on 214 real voice blobs + hallucination watch → dedicated section ✓.

**2. Placeholder scan:** No TBD/TODO. Every code step has complete code. The VERIFY section gives concrete asserts (non-empty, plausible Chinese, hallucination-rate threshold), not vague "test it".

**3. Type consistency:** `_WHISPER` keys (`"whisper-small"`, `"whisper-large-v3"`) exactly match the Task 1 registry ids. `_default_transcribe(model_dir, model_id, wav_path)` + `FasterWhisperRunner(model_manager, transcribe_fn=None)` signatures match the test call sites and `for_capability_tier("asr", tier).id` (Task 2 test c) matches the registry API. `art.source_urls == []` matches the `Artifact("any", [], …)` zero-URL edit. `FasterWhisperRunner` replaces `SenseVoiceRunner` at the single server.py construction site.

**Out of scope (this plan):** image OCR, reranker, ASR model bake-off, speaker diarization/timestamps, feeding derived text back into wxsearch/wxgraph (manual reindex covers it).
