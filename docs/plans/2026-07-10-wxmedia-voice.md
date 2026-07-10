# wxmedia (voice→text) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `wxmedia` plugin's voice pipeline: turn WeChat voice messages (SILK, stored in wxvault's decrypted `media_*.sqlite`) into searchable text, incrementally + one-time backfill, choosing the ASR model via `model-manager`.

**Architecture:** Pure data contract with wxvault — wxmedia reads wxvault's decrypted output under `${dataDir}/out/decrypted/media_*.sqlite` (`VoiceInfo`), never imports wxvault code. Pipeline: read `voice_data` → strip WeChat's leading byte → `pilk.silk_to_wav` → an injectable `AsrRunner` → store `{svr_id → text}` in a sidecar `${dataDir}/wxmedia/derived.sqlite` (idempotent, so incremental = skip rows already present). An MCP stdio server exposes tools. The concrete SenseVoice runner is isolated behind `AsrRunner` so the pipeline is fully testable with a fake and the external-binary specifics live in one swappable place.

**Tech Stack:** Python 3.10+, pytest, `pilk` (SILK decode), `model-manager` (sibling package), stdlib `sqlite3` + JSON-RPC over stdio (same minimal MCP framing as wxvault_mcp.py).

## Global Constraints

- Package at `packages/wxmedia/` in `wechat-cc-plugins`; import name `wxmedia`.
- Python **3.10+**. Runtime deps: `pilk`, `model-manager` (path/editable). ASR model runtimes are installed per model-manager config, not hard-listed here.
- **Hybrid privacy — hard rule:** audio and derived text stay local. This plugin makes ZERO network/provider calls. (LLM/provider usage belongs to wxsearch/wxgraph, not wxmedia.)
- Reads wxvault decrypted DBs **read-only**, via `sqlite3` opened with `mode=ro`. Voice source table: `VoiceInfo(svr_id, local_id, voice_data BLOB)` in `${dataDir}/out/decrypted/media_*.sqlite`.
- WeChat SILK fix: `voice_data` is standard SILK v3 with ONE extra leading byte — strip `blob[0]` to get `#!SILK_V3...`. (Verified against wxvault decode_voice.py `fix_silk`.)
- `pilk` API: `pilk.silk_to_wav(silk_path, wav_path, rate=16000)`. (Verified against decode_voice.py.)
- State dir passed in as `state_dir` (the plugin injects `${dataDir}`), same convention as wxvault/model-manager. Sidecar DB: `${state_dir}/wxmedia/derived.sqlite`. Work files: `${state_dir}/wxmedia/work/`.
- MCP tool names are prefixed by the host as `mcp__wxmedia__*`; server declares bare names: `voice_backfill`, `get_media_text`, `models_status`, `set_model`.

---

## File Structure

```
packages/wxmedia/
├── pyproject.toml
├── wechat-cc.plugin.json          # manifest (spawn + setup + healthcheck)
├── setup.py                       # deps + model-manager config (per-OS)
├── wxmedia/
│   ├── __init__.py
│   ├── store.py                   # derived.sqlite: get/put/has (idempotent)
│   ├── voice_source.py            # read VoiceInfo from decrypted media_*.sqlite (ro)
│   ├── silk.py                    # fix_silk + silk_to_wav (pilk wrapper)
│   ├── asr.py                     # AsrRunner protocol + SenseVoiceRunner (isolated)
│   ├── pipeline.py                # orchestrate: source → silk → asr → store (incremental)
│   └── server.py                  # MCP stdio server exposing the tools
└── tests/
    ├── test_store.py
    ├── test_voice_source.py
    ├── test_silk.py
    ├── test_pipeline.py
    └── test_server.py
```

Responsibilities: `store` = persistence only. `voice_source` = read-only DB access. `silk` = decode. `asr` = the swappable runner boundary. `pipeline` = orchestration/incremental logic (the brains, fully testable with fakes). `server` = protocol glue.

---

### Task 1: Package scaffold + derived-text store

**Files:**
- Create: `packages/wxmedia/pyproject.toml`
- Create: `packages/wxmedia/wxmedia/__init__.py`
- Create: `packages/wxmedia/wxmedia/store.py`
- Test: `packages/wxmedia/tests/test_store.py`

**Interfaces:**
- Produces `class DerivedStore`:
  - `__init__(self, state_dir)` — opens/creates `${state_dir}/wxmedia/derived.sqlite`, table `media_text(svr_id TEXT PRIMARY KEY, kind TEXT, text TEXT, model_id TEXT, created_at INTEGER)`.
  - `has(self, svr_id: str) -> bool`
  - `put(self, svr_id: str, kind: str, text: str, model_id: str, created_at: int) -> None` (upsert)
  - `get(self, svr_id: str) -> dict | None`
  - `count(self) -> int`
  - `close(self) -> None`

- [ ] **Step 1: Write the failing test**

```python
# packages/wxmedia/tests/test_store.py
from wxmedia.store import DerivedStore

def test_put_then_get_and_has(tmp_path):
    s = DerivedStore(tmp_path)
    assert s.has("100") is False
    s.put("100", "voice", "你好", "sensevoice-small-q8", 1720000000)
    assert s.has("100") is True
    row = s.get("100")
    assert row["text"] == "你好"
    assert row["kind"] == "voice"
    assert row["model_id"] == "sensevoice-small-q8"
    s.close()

def test_put_is_upsert(tmp_path):
    s = DerivedStore(tmp_path)
    s.put("1", "voice", "old", "m", 1)
    s.put("1", "voice", "new", "m", 2)
    assert s.get("1")["text"] == "new"
    assert s.count() == 1
    s.close()

def test_persists_across_instances(tmp_path):
    DerivedStore(tmp_path).put("7", "voice", "hi", "m", 1)
    assert DerivedStore(tmp_path).get("7")["text"] == "hi"

def test_get_missing_is_none(tmp_path):
    assert DerivedStore(tmp_path).get("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/wxmedia && python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wxmedia'`

- [ ] **Step 3: Create scaffold + store**

```toml
# packages/wxmedia/pyproject.toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "wxmedia"
version = "0.1.0"
description = "WeChat media->text (voice ASR) enrichment plugin for wechat-cc"
requires-python = ">=3.10"
dependencies = ["pilk"]

[project.optional-dependencies]
test = ["pytest>=7"]

[tool.setuptools.packages.find]
include = ["wxmedia*"]
```

```python
# packages/wxmedia/wxmedia/__init__.py
__all__ = []
```

```python
# packages/wxmedia/wxmedia/store.py
"""Idempotent store for derived media text (sidecar sqlite in state dir)."""
import sqlite3
from pathlib import Path


class DerivedStore:
    def __init__(self, state_dir):
        d = Path(state_dir) / "wxmedia"
        d.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(d / "derived.sqlite"))
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS media_text ("
            "svr_id TEXT PRIMARY KEY, kind TEXT, text TEXT, model_id TEXT, created_at INTEGER)")
        self.con.commit()

    def has(self, svr_id: str) -> bool:
        r = self.con.execute("SELECT 1 FROM media_text WHERE svr_id=?", (str(svr_id),)).fetchone()
        return r is not None

    def put(self, svr_id, kind, text, model_id, created_at) -> None:
        self.con.execute(
            "INSERT INTO media_text(svr_id, kind, text, model_id, created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(svr_id) DO UPDATE SET kind=excluded.kind, text=excluded.text, "
            "model_id=excluded.model_id, created_at=excluded.created_at",
            (str(svr_id), kind, text, model_id, int(created_at)))
        self.con.commit()

    def get(self, svr_id):
        r = self.con.execute("SELECT * FROM media_text WHERE svr_id=?", (str(svr_id),)).fetchone()
        return dict(r) if r else None

    def count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM media_text").fetchone()[0]

    def close(self) -> None:
        self.con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/wxmedia && python -m pytest tests/test_store.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/wxmedia/pyproject.toml packages/wxmedia/wxmedia/__init__.py packages/wxmedia/wxmedia/store.py packages/wxmedia/tests/test_store.py
git commit -m "feat(wxmedia): scaffold + idempotent derived-text store"
```

---

### Task 2: Voice source (read VoiceInfo from decrypted media DBs, read-only)

**Files:**
- Create: `packages/wxmedia/wxmedia/voice_source.py`
- Test: `packages/wxmedia/tests/test_voice_source.py`

**Interfaces:**
- Produces:
  - `find_media_dbs(state_dir) -> list[Path]` — globs `${state_dir}/out/decrypted/media_*.sqlite`.
  - `iter_voice(state_dir) -> Iterator[dict]` — yields `{"svr_id": str, "voice_data": bytes}` for rows where `length(voice_data)>0`, opening each DB **read-only**. `svr_id` falls back to `"local_<local_id>"` when svr_id is 0/empty (matches wxvault naming).

- [ ] **Step 1: Write the failing test**

```python
# packages/wxmedia/tests/test_voice_source.py
import sqlite3
from pathlib import Path
from wxmedia.voice_source import find_media_dbs, iter_voice

def _make_media_db(state_dir, name, rows):
    d = Path(state_dir) / "out" / "decrypted"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / name))
    con.execute("CREATE TABLE VoiceInfo (svr_id INTEGER, local_id INTEGER, voice_data BLOB)")
    con.executemany("INSERT INTO VoiceInfo VALUES (?,?,?)", rows)
    con.commit(); con.close()

def test_find_media_dbs(tmp_path):
    _make_media_db(tmp_path, "media_0.sqlite", [])
    _make_media_db(tmp_path, "media_1.sqlite", [])
    assert len(find_media_dbs(tmp_path)) == 2

def test_iter_voice_yields_nonempty(tmp_path):
    _make_media_db(tmp_path, "media_0.sqlite",
                   [(100, 1, b"\x02silkdata"), (0, 0, b""), (200, 2, b"\x02more")])
    got = list(iter_voice(tmp_path))
    assert {g["svr_id"] for g in got} == {"100", "200"}
    assert got[0]["voice_data"].startswith(b"\x02")

def test_iter_voice_local_fallback_id(tmp_path):
    _make_media_db(tmp_path, "media_0.sqlite", [(0, 42, b"\x02x")])
    got = list(iter_voice(tmp_path))
    assert got[0]["svr_id"] == "local_42"

def test_iter_voice_no_dbs_is_empty(tmp_path):
    assert list(iter_voice(tmp_path)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/wxmedia && python -m pytest tests/test_voice_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wxmedia.voice_source'`

- [ ] **Step 3: Write voice_source.py**

```python
# packages/wxmedia/wxmedia/voice_source.py
"""Read WeChat voice blobs from wxvault's decrypted media_*.sqlite (read-only)."""
import glob
import os
import sqlite3
from pathlib import Path


def find_media_dbs(state_dir) -> list:
    pat = os.path.join(str(state_dir), "out", "decrypted", "media_*.sqlite")
    return [Path(p) for p in sorted(glob.glob(pat))]


def iter_voice(state_dir):
    for db in find_media_dbs(state_dir):
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        con.row_factory = sqlite3.Row
        try:
            names = [x[0] for x in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            if "VoiceInfo" not in names:
                continue
            for r in con.execute(
                    "SELECT svr_id, local_id, voice_data FROM VoiceInfo WHERE length(voice_data)>0"):
                svr = str(r["svr_id"]) if r["svr_id"] else "local_%s" % r["local_id"]
                yield {"svr_id": svr, "voice_data": bytes(r["voice_data"])}
        finally:
            con.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/wxmedia && python -m pytest tests/test_voice_source.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/wxmedia/wxmedia/voice_source.py packages/wxmedia/tests/test_voice_source.py
git commit -m "feat(wxmedia): read-only VoiceInfo source from decrypted media DBs"
```

---

### Task 3: SILK decode (fix + pilk to wav)

**Files:**
- Create: `packages/wxmedia/wxmedia/silk.py`
- Test: `packages/wxmedia/tests/test_silk.py`

**Interfaces:**
- Produces:
  - `fix_silk(blob: bytes) -> bytes` — strip WeChat's single leading byte; if it already starts with `#!SILK_V3` return unchanged.
  - `to_wav(voice_data: bytes, work_dir, name: str, rate: int = 16000, pilk_mod=None) -> Path` — write fixed silk to `${work_dir}/<name>.silk`, call `pilk.silk_to_wav(silk, wav, rate)`, return wav path. `pilk_mod` injectable for tests.

- [ ] **Step 1: Write the failing test**

```python
# packages/wxmedia/tests/test_silk.py
from pathlib import Path
from wxmedia.silk import fix_silk, to_wav

SILK_HDR = b"#!SILK_V3"

def test_fix_strips_wechat_leading_byte():
    assert fix_silk(b"\x02" + SILK_HDR + b"rest") == SILK_HDR + b"rest"

def test_fix_leaves_standard_silk_untouched():
    assert fix_silk(SILK_HDR + b"rest") == SILK_HDR + b"rest"

def test_to_wav_writes_silk_and_calls_pilk(tmp_path):
    calls = {}
    class FakePilk:
        @staticmethod
        def silk_to_wav(silk, wav, rate):
            calls["silk"] = silk; calls["wav"] = wav; calls["rate"] = rate
            Path(wav).write_bytes(b"RIFFfakewav")
    wav = to_wav(b"\x02" + SILK_HDR + b"data", tmp_path, "100", rate=16000, pilk_mod=FakePilk)
    assert Path(wav).exists()
    assert calls["rate"] == 16000
    assert Path(calls["silk"]).read_bytes() == SILK_HDR + b"data"   # fixed, no leading byte
    assert Path(wav).name == "100.wav"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/wxmedia && python -m pytest tests/test_silk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wxmedia.silk'`

- [ ] **Step 3: Write silk.py**

```python
# packages/wxmedia/wxmedia/silk.py
"""WeChat SILK -> wav via pilk. WeChat prepends one byte to standard SILK v3."""
from pathlib import Path

_SILK_MAGIC = b"#!SILK_V3"


def fix_silk(blob: bytes) -> bytes:
    if blob[:len(_SILK_MAGIC)] == _SILK_MAGIC:
        return blob
    return blob[1:]   # drop WeChat's leading byte


def to_wav(voice_data: bytes, work_dir, name: str, rate: int = 16000, pilk_mod=None) -> Path:
    if pilk_mod is None:
        import pilk as pilk_mod
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    silk = work / (name + ".silk")
    wav = work / (name + ".wav")
    silk.write_bytes(fix_silk(voice_data))
    pilk_mod.silk_to_wav(str(silk), str(wav), rate)
    return wav
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/wxmedia && python -m pytest tests/test_silk.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/wxmedia/wxmedia/silk.py packages/wxmedia/tests/test_silk.py
git commit -m "feat(wxmedia): WeChat SILK fix + pilk wav decode"
```

---

### Task 4: ASR runner boundary + pipeline (orchestration, incremental)

**Files:**
- Create: `packages/wxmedia/wxmedia/asr.py`
- Create: `packages/wxmedia/wxmedia/pipeline.py`
- Test: `packages/wxmedia/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `DerivedStore` (T1), `iter_voice` (T2), `to_wav` (T3).
- Produces:
  - `asr.py`: `class AsrRunner(typing.Protocol)` with `transcribe(self, wav_path: str) -> str` and `model_id: str`. (Concrete `SenseVoiceRunner` is Task 5.)
  - `pipeline.py`: `transcribe_all(state_dir, runner, pilk_mod=None, limit=None, progress=None) -> dict` — iterate `iter_voice`, skip svr_ids already in the store, `to_wav` → `runner.transcribe` → `store.put(kind="voice", model_id=runner.model_id)`. Returns `{"processed": int, "skipped": int, "failed": int}`. Never raises on a single-clip failure (count it, continue). Deletes each work wav after use. `progress(done, total)` optional callback.

- [ ] **Step 1: Write the failing test**

```python
# packages/wxmedia/tests/test_pipeline.py
import sqlite3
from pathlib import Path
from wxmedia.pipeline import transcribe_all
from wxmedia.store import DerivedStore

def _media_db(state_dir, rows):
    d = Path(state_dir) / "out" / "decrypted"; d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "media_0.sqlite"))
    con.execute("CREATE TABLE VoiceInfo (svr_id INTEGER, local_id INTEGER, voice_data BLOB)")
    con.executemany("INSERT INTO VoiceInfo VALUES (?,?,?)", rows); con.commit(); con.close()

class FakePilk:
    @staticmethod
    def silk_to_wav(silk, wav, rate): Path(wav).write_bytes(b"RIFF")

class FakeRunner:
    model_id = "fake-asr"
    def __init__(self, mapping=None, fail_on=()): self.mapping = mapping or {}; self.fail_on = fail_on
    def transcribe(self, wav_path):
        name = Path(wav_path).stem
        if name in self.fail_on: raise RuntimeError("boom")
        return self.mapping.get(name, "text-%s" % name)

def test_transcribes_and_stores(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a"), (200, 2, b"\x02b")])
    res = transcribe_all(tmp_path, FakeRunner({"100": "你好", "200": "在吗"}), pilk_mod=FakePilk)
    assert res == {"processed": 2, "skipped": 0, "failed": 0}
    s = DerivedStore(tmp_path)
    assert s.get("100")["text"] == "你好"
    assert s.get("200")["model_id"] == "fake-asr"

def test_incremental_skips_existing(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a")])
    transcribe_all(tmp_path, FakeRunner(), pilk_mod=FakePilk)
    res = transcribe_all(tmp_path, FakeRunner(), pilk_mod=FakePilk)  # second run
    assert res == {"processed": 0, "skipped": 1, "failed": 0}

def test_single_failure_does_not_abort(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a"), (200, 2, b"\x02b")])
    res = transcribe_all(tmp_path, FakeRunner(fail_on=("100",)), pilk_mod=FakePilk)
    assert res == {"processed": 1, "skipped": 0, "failed": 1}
    assert DerivedStore(tmp_path).get("200") is not None
    assert DerivedStore(tmp_path).get("100") is None

def test_work_wavs_cleaned_up(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a")])
    transcribe_all(tmp_path, FakeRunner(), pilk_mod=FakePilk)
    work = tmp_path / "wxmedia" / "work"
    assert not list(work.glob("*.wav")) if work.exists() else True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/wxmedia && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wxmedia.pipeline'`

- [ ] **Step 3: Write asr.py and pipeline.py**

```python
# packages/wxmedia/wxmedia/asr.py
"""The ASR runner boundary. Concrete runners live behind this Protocol."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class AsrRunner(Protocol):
    model_id: str
    def transcribe(self, wav_path: str) -> str: ...
```

```python
# packages/wxmedia/wxmedia/pipeline.py
"""Orchestrate voice -> text: source -> silk -> asr -> store, incrementally."""
import time
from pathlib import Path

from .store import DerivedStore
from .voice_source import iter_voice
from .silk import to_wav


def transcribe_all(state_dir, runner, pilk_mod=None, limit=None, progress=None) -> dict:
    store = DerivedStore(state_dir)
    work = Path(state_dir) / "wxmedia" / "work"
    processed = skipped = failed = 0
    try:
        items = list(iter_voice(state_dir))
        total = len(items)
        for i, item in enumerate(items):
            if limit is not None and processed >= limit:
                break
            svr = item["svr_id"]
            if store.has(svr):
                skipped += 1
                continue
            wav = None
            try:
                wav = to_wav(item["voice_data"], work, svr, pilk_mod=pilk_mod)
                text = runner.transcribe(str(wav))
                store.put(svr, "voice", text, runner.model_id, int(time.time()))
                processed += 1
            except Exception:
                failed += 1
            finally:
                if wav is not None:
                    try:
                        Path(wav).unlink(missing_ok=True)
                        Path(str(wav)[:-4] + ".silk").unlink(missing_ok=True)
                    except OSError:
                        pass
            if progress is not None:
                progress(i + 1, total)
    finally:
        store.close()
    return {"processed": processed, "skipped": skipped, "failed": failed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/wxmedia && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/wxmedia/wxmedia/asr.py packages/wxmedia/wxmedia/pipeline.py packages/wxmedia/tests/test_pipeline.py
git commit -m "feat(wxmedia): ASR runner boundary + incremental transcription pipeline"
```

---

### Task 5: Concrete SenseVoiceRunner (isolated external-binary invocation)

**Files:**
- Modify: `packages/wxmedia/wxmedia/asr.py` (append `SenseVoiceRunner`)
- Test: `packages/wxmedia/tests/test_asr_runner.py`

**Interfaces:**
- Consumes: `model-manager` `ModelManager.ensure("asr")` → model dir; the resolved spec's `runtime`.
- Produces: `class SenseVoiceRunner` implementing `AsrRunner`: `__init__(self, model_manager, runner_cmd=None)` — resolves+ensures the ASR model, records `model_id`; `transcribe(wav_path)` shells out to the model's runtime binary and returns text. `runner_cmd(model_dir, wav_path) -> list[str]` is injectable; the default builds the SenseVoice-GGUF/whisper.cpp command. Output parsing via `_parse_output(stdout: str) -> str`.

> ⚠️ **VERIFY-AGAINST-REAL-BINARY:** the default `runner_cmd` and `_parse_output` below encode the *expected* SenseVoice-GGUF/llama.cpp CLI (single self-contained binary that prints the transcript to stdout). Before shipping, run the actual downloaded binary on one wav and adjust the argv + stdout parsing to match. The Protocol boundary means only this file changes.

- [ ] **Step 1: Write the failing test** (fully mocks the subprocess — no real binary needed)

```python
# packages/wxmedia/tests/test_asr_runner.py
from wxmedia.asr import SenseVoiceRunner, _parse_output

class FakeMM:
    def resolve(self, cap):
        class S: id = "sensevoice-small-q8"; runtime = "llama.cpp"
        return S()
    def ensure(self, cap, **kw):
        from pathlib import Path
        return Path("/models/asr/sensevoice-small-q8")

def test_model_id_from_manager():
    r = SenseVoiceRunner(FakeMM(), runner_cmd=lambda d, w: ["echo", "hi"])
    assert r.model_id == "sensevoice-small-q8"

def test_transcribe_runs_cmd_and_parses(monkeypatch):
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0; stdout = "transcript: 你好世界\n"; stderr = ""
        return R()
    monkeypatch.setattr("wxmedia.asr.subprocess.run", fake_run)
    r = SenseVoiceRunner(FakeMM(), runner_cmd=lambda d, w: ["asr", str(d), w])
    out = r.transcribe("/tmp/100.wav")
    assert out == "你好世界"
    assert captured["cmd"] == ["asr", "/models/asr/sensevoice-small-q8", "/tmp/100.wav"]

def test_parse_output_strips_label_and_ws():
    assert _parse_output("transcript: 在吗 \n") == "在吗"
    assert _parse_output("no label here") == "no label here"

def test_transcribe_raises_on_nonzero(monkeypatch):
    def fake_run(cmd, **kw):
        class R: returncode = 1; stdout = ""; stderr = "err"
        return R()
    monkeypatch.setattr("wxmedia.asr.subprocess.run", fake_run)
    r = SenseVoiceRunner(FakeMM(), runner_cmd=lambda d, w: ["x"])
    import pytest
    with pytest.raises(RuntimeError):
        r.transcribe("/tmp/1.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/wxmedia && python -m pytest tests/test_asr_runner.py -v`
Expected: FAIL — `ImportError: cannot import name 'SenseVoiceRunner'`

- [ ] **Step 3: Append to asr.py**

```python
# ---- append to packages/wxmedia/wxmedia/asr.py ----
import re
import subprocess
from pathlib import Path


def _parse_output(stdout: str) -> str:
    # SenseVoice/whisper.cpp print the transcript to stdout; strip an optional label.
    text = stdout.strip()
    m = re.match(r"^\s*(?:transcript|text)\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
    return (m.group(1) if m else text).strip()


def _default_runner_cmd(model_dir: Path, wav_path: str) -> list:
    # Expected SenseVoice-GGUF self-contained binary; VERIFY against the real binary.
    binary = model_dir / ("sense-voice.exe" if __import__("os").name == "nt" else "sense-voice")
    return [str(binary), "-m", str(model_dir / "model.bin"), "-f", wav_path, "--no-timestamps"]


class SenseVoiceRunner:
    def __init__(self, model_manager, runner_cmd=None):
        spec = model_manager.resolve("asr")
        self.model_id = spec.id
        self._model_dir = Path(model_manager.ensure("asr"))
        self._cmd = runner_cmd or _default_runner_cmd

    def transcribe(self, wav_path: str) -> str:
        cmd = self._cmd(self._model_dir, wav_path)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("ASR failed (%s): %s" % (proc.returncode, proc.stderr[:200]))
        return _parse_output(proc.stdout)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/wxmedia && python -m pytest tests/test_asr_runner.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/wxmedia/wxmedia/asr.py packages/wxmedia/tests/test_asr_runner.py
git commit -m "feat(wxmedia): SenseVoiceRunner (isolated, injectable-cmd) behind AsrRunner"
```

---

### Task 6: MCP server + manifest + setup

**Files:**
- Create: `packages/wxmedia/wxmedia/server.py`
- Create: `packages/wxmedia/wechat-cc.plugin.json`
- Create: `packages/wxmedia/setup.py`
- Test: `packages/wxmedia/tests/test_server.py`

**Interfaces:**
- Consumes: `transcribe_all` (T4), `SenseVoiceRunner` (T5), `DerivedStore` (T1), `ModelManager` (model-manager pkg).
- Produces: `dispatch(req: dict, deps: dict) -> dict` (pure JSON-RPC handler, `deps` injects store/manager/runner-factory for tests) handling tools: `voice_backfill` (limit?), `get_media_text` (svr_id), `models_status`, `set_model` (capability, tier). `main()` wires real deps and runs the stdio loop with UTF-8 reconfigure (Windows).

- [ ] **Step 1: Write the failing test**

```python
# packages/wxmedia/tests/test_server.py
from wxmedia.server import dispatch
from wxmedia.store import DerivedStore

class FakeMM:
    def __init__(self): self._preset = "light"
    def status(self): return {"preset": self._preset, "platform": "win-x64", "capabilities": {}}
    def set_choice(self, cap, tier): self._set = (cap, tier)

def _deps(tmp_path, mm=None, transcribe=None):
    return {"state_dir": tmp_path, "manager": mm or FakeMM(),
            "transcribe": transcribe or (lambda: {"processed": 3, "skipped": 0, "failed": 0})}

def _call(name, args, deps):
    return dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, deps)

def test_get_media_text(tmp_path):
    DerivedStore(tmp_path).put("100", "voice", "你好", "m", 1)
    r = _call("get_media_text", {"svr_id": "100"}, _deps(tmp_path))
    assert "你好" in r["result"]["content"][0]["text"]

def test_voice_backfill_reports_counts(tmp_path):
    r = _call("voice_backfill", {}, _deps(tmp_path))
    assert "3" in r["result"]["content"][0]["text"]

def test_models_status(tmp_path):
    r = _call("models_status", {}, _deps(tmp_path))
    assert "light" in r["result"]["content"][0]["text"]

def test_set_model(tmp_path):
    mm = FakeMM()
    _call("set_model", {"capability": "asr", "tier": "high"}, _deps(tmp_path, mm=mm))
    assert mm._set == ("asr", "high")

def test_unknown_tool_is_error(tmp_path):
    r = _call("nope", {}, _deps(tmp_path))
    assert r["error"]["code"] == -32601
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/wxmedia && python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wxmedia.server'`

- [ ] **Step 3: Write server.py, manifest, setup.py**

```python
# packages/wxmedia/wxmedia/server.py
"""Minimal MCP stdio server for wxmedia (same framing as wxvault_mcp.py)."""
import json
import os
import sys

from .store import DerivedStore


def _ok(mid, text):
    return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def dispatch(req: dict, deps: dict) -> dict:
    mid = req.get("id")
    if req.get("method") != "tools/call":
        return _err(mid, -32601, "only tools/call")
    p = req.get("params") or {}
    name = p.get("name")
    args = p.get("arguments") or {}
    sd = deps["state_dir"]
    if name == "voice_backfill":
        res = deps["transcribe"]()
        return _ok(mid, json.dumps(res, ensure_ascii=False))
    if name == "get_media_text":
        store = DerivedStore(sd)
        row = store.get(str(args.get("svr_id", "")))
        store.close()
        return _ok(mid, json.dumps(row or {"note": "no text for this id"}, ensure_ascii=False))
    if name == "models_status":
        return _ok(mid, json.dumps(deps["manager"].status(), ensure_ascii=False))
    if name == "set_model":
        deps["manager"].set_choice(args["capability"], args["tier"])
        return _ok(mid, "ok")
    return _err(mid, -32601, "unknown tool: %s" % name)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    from model_manager import ModelManager
    from .pipeline import transcribe_all
    from .asr import SenseVoiceRunner
    manager = ModelManager(state_dir)
    deps = {
        "state_dir": state_dir,
        "manager": manager,
        "transcribe": lambda: transcribe_all(state_dir, SenseVoiceRunner(manager)),
    }
    sys.stderr.write("[wxmedia] ready\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = dispatch(req, deps)
        except Exception as e:
            resp = _err(None, -32603, "internal: %s" % e)
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
```

```json
// packages/wxmedia/wechat-cc.plugin.json
{
  "name": "wxmedia",
  "kind": "mcp",
  "version": "0.1.0",
  "minWechatCcVersion": "0.6.4",
  "displayName": "语音转文字 (wxmedia)",
  "description": "把微信语音消息本地转成可搜索文本（SILK→ASR，全本地，模型分层可选）。读 wxvault 解密产物，不外连。",
  "spawn": {
    "command": "python3",
    "args": ["${pluginDir}/wxmedia/server.py"],
    "env": { "WXVAULT_STATE_DIR": "${dataDir}" }
  },
  "healthcheck": { "requiresPaths": ["${dataDir}/out/decrypted"] },
  "setup": {
    "command": "python3",
    "args": ["${pluginDir}/setup.py"],
    "env": { "WXVAULT_STATE_DIR": "${dataDir}" }
  },
  "requires": {
    "python3": "required（依赖 pilk + model-manager；ASR 运行时按所选档下载）",
    "setup": "python3 ${pluginDir}/setup.py：装依赖 + 选模型档（轻量/高精度）。语音源来自 wxvault 解密的 media_*.sqlite，需先跑 wxvault。"
  },
  "tools": ["voice_backfill", "get_media_text", "models_status", "set_model"]
}
```

```python
# packages/wxmedia/setup.py
"""wxmedia setup: install deps + choose ASR model tier (per-OS via model-manager)."""
import subprocess
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxmedia setup ==")
    need = []
    try:
        import pilk  # noqa: F401
    except ImportError:
        need.append("pilk")
    try:
        import model_manager  # noqa: F401
    except ImportError:
        need.append("model-manager")
    if need:
        print("安装依赖：%s" % " ".join(need))
        r = subprocess.run([sys.executable, "-m", "pip", "install", *need])
        if r.returncode != 0:
            sys.exit("!! 依赖安装失败")
    print("✓ 依赖就绪。ASR 模型在首次 voice_backfill 时按所选档懒下载（默认轻量 SenseVoice）。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the full suite**

Run: `cd packages/wxmedia && python -m pytest -v`
Expected: PASS (store 4, voice_source 4, silk 3, pipeline 4, asr_runner 4, server 5 = 24)

- [ ] **Step 5: Commit**

```bash
git add packages/wxmedia/wxmedia/server.py packages/wxmedia/wechat-cc.plugin.json packages/wxmedia/setup.py packages/wxmedia/tests/test_server.py
git commit -m "feat(wxmedia): MCP server + manifest + setup"
```

---

## Self-Review

**1. Spec coverage** (spec §3–5, wxmedia voice slice): SILK→PCM via pilk ✓ (T3), ASR light default via model-manager ✓ (T5 + T4 pipeline), incremental + backfill ✓ (T4 skip-existing + `voice_backfill`), read wxvault decrypted output read-only ✓ (T2), models_status/set_model MCP tools ✓ (T6), hybrid privacy (zero network) ✓ (no provider/network call anywhere; ASR is local). Per-OS ASR high tier resolution lives in model-manager (Plan A). **Image OCR + VLM escalation: deliberately OUT of this plan** (needs the wxvault→wxmedia plaintext-image interface decision) → next plan `wxmedia-image`.

**2. Placeholder scan:** No TBD/TODO. The one flagged item — `SenseVoiceRunner`'s default `runner_cmd`/`_parse_output` — is real, runnable code isolated behind the `AsrRunner` Protocol with a VERIFY-AGAINST-REAL-BINARY note; tests fully mock the subprocess so the pipeline is proven regardless. This is intentional isolation, not a placeholder.

**3. Type consistency:** `DerivedStore.has/put/get/count/close`, `iter_voice`→`{"svr_id","voice_data"}`, `to_wav(...pilk_mod=)`, `AsrRunner.transcribe/model_id`, `transcribe_all(...)→{"processed","skipped","failed"}`, `dispatch(req, deps)` with `deps={"state_dir","manager","transcribe"}` — consistent across tasks and tests.

**Out of scope (this plan):** image OCR, VLM escalation (next plan), wxsearch, wxgraph.
