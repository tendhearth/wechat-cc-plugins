# model-manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared `model-manager` Python package that lets the wechat-cc enrichment plugins pick, resolve (per-OS), lazily download, and track tiered local models via a global preset + per-capability override.

**Architecture:** A single `ModelManager(state_dir)` class is the entry point. A static `registry` module declares every model (id, capability, tier, per-OS artifact, runtime). A `platform` module reports the current OS key. Per-user choices live in `${state_dir}/models/config.json` (preset + overrides). `resolve(capability)` maps config+platform → a `ModelSpec`; `ensure(model_id)` returns a local path, downloading (ModelScope-primary / HuggingFace-fallback, optional sha256 verify) only if missing. Downloads are injectable so tests never hit the network.

**Tech Stack:** Python 3.10+, pytest, standard library only (no third-party runtime deps for the manager itself; `urllib` for fetch).

## Global Constraints

- Package lives at `packages/model-manager/` in the `wechat-cc-plugins` monorepo; import name `model_manager`.
- Python **3.10+** (uses `X | Y` type unions and `dataclasses`).
- **No third-party runtime dependency** in `model-manager` (keep the shared lib light; ML runtimes are the consumers' concern). Test-only dep: `pytest`.
- State dir is passed in explicitly as `state_dir` (the plugin injects `${dataDir}`); the manager never reads global env for it. Model files live under `${state_dir}/models/<capability>/<model_id>/`; config at `${state_dir}/models/config.json`.
- Two presets only: `"light"` (default) and `"high"`. Capabilities with a user tier: `asr`, `embedding`, `vlm`. `vlm` light == off (no model). `ocr` is resolved per-OS but is not a user preset axis.
- Platform keys: `"mac-arm64"`, `"mac-x64"`, `"win-x64"`, `"linux-x64"`.
- Download source order: ModelScope first, HuggingFace fallback. sha256 verify only when a spec provides a `sha256` (specs may omit it until a model is pinned).
- All network access goes through one injectable `fetcher(url, dest_path)` callable so tests pass a fake. Never hit the network in tests.

---

## File Structure

```
packages/model-manager/
├── pyproject.toml                 # package metadata, py>=3.10, pytest extra
├── model_manager/
│   ├── __init__.py                # exports ModelManager, ModelSpec, capability constants
│   ├── platform.py                # current_platform() -> platform key
│   ├── registry.py                # ModelSpec dataclass + MODELS list + lookups
│   ├── config.py                  # Config load/save (preset + overrides) under state_dir
│   ├── download.py                # ensure(spec, models_dir, fetcher) -> Path
│   └── manager.py                 # ModelManager class (ties resolve/ensure/status/set/prefetch)
└── tests/
    ├── test_platform.py
    ├── test_registry.py
    ├── test_config.py
    ├── test_download.py
    └── test_manager.py
```

Responsibilities: `platform` = OS detection only. `registry` = static data + pure lookups. `config` = read/write user choices. `download` = filesystem + fetch + verify. `manager` = orchestration (resolve using registry+config+platform, then ensure). Files that change together (a capability's resolution rules) live in `manager`/`registry`, not scattered.

---

### Task 1: Package scaffold + platform detection

**Files:**
- Create: `packages/model-manager/pyproject.toml`
- Create: `packages/model-manager/model_manager/__init__.py`
- Create: `packages/model-manager/model_manager/platform.py`
- Test: `packages/model-manager/tests/test_platform.py`

**Interfaces:**
- Produces: `current_platform() -> str` returning one of `"mac-arm64"|"mac-x64"|"win-x64"|"linux-x64"`; `platform_from(system: str, machine: str) -> str` (pure, testable core).

- [ ] **Step 1: Write the failing test**

```python
# packages/model-manager/tests/test_platform.py
from model_manager.platform import platform_from, current_platform

def test_mac_arm():
    assert platform_from("Darwin", "arm64") == "mac-arm64"

def test_mac_intel():
    assert platform_from("Darwin", "x86_64") == "mac-x64"

def test_windows():
    assert platform_from("Windows", "AMD64") == "win-x64"

def test_linux():
    assert platform_from("Linux", "x86_64") == "linux-x64"

def test_unknown_falls_back_to_linux_x64():
    assert platform_from("Plan9", "sparc") == "linux-x64"

def test_current_platform_returns_known_key():
    assert current_platform() in {"mac-arm64", "mac-x64", "win-x64", "linux-x64"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/model-manager && python -m pytest tests/test_platform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'model_manager'`

- [ ] **Step 3: Create the package files**

```toml
# packages/model-manager/pyproject.toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "model-manager"
version = "0.1.0"
description = "Tiered local-model manager for wechat-cc enrichment plugins"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=7"]

[tool.setuptools.packages.find]
include = ["model_manager*"]
```

```python
# packages/model-manager/model_manager/__init__.py
from .platform import current_platform

__all__ = ["current_platform"]
```

```python
# packages/model-manager/model_manager/platform.py
"""Current-OS detection, reduced to a small set of platform keys."""
import platform as _platform


def platform_from(system: str, machine: str) -> str:
    system = (system or "").lower()
    machine = (machine or "").lower()
    if system == "darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    if system == "windows":
        return "win-x64"
    if system == "linux":
        return "linux-x64"
    return "linux-x64"  # conservative fallback


def current_platform() -> str:
    return platform_from(_platform.system(), _platform.machine())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/model-manager && python -m pytest tests/test_platform.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/pyproject.toml packages/model-manager/model_manager/__init__.py packages/model-manager/model_manager/platform.py packages/model-manager/tests/test_platform.py
git commit -m "feat(model-manager): package scaffold + platform detection"
```

---

### Task 2: Model registry (ModelSpec + static MODELS)

**Files:**
- Create: `packages/model-manager/model_manager/registry.py`
- Test: `packages/model-manager/tests/test_registry.py`

**Interfaces:**
- Produces:
  - `CAPABILITIES = ("asr", "embedding", "vlm", "ocr")`, `PRESETS = ("light", "high")`
  - `@dataclass(frozen=True) class Artifact: platform: str; source_urls: list[str]; size_mb: int; sha256: str | None`
  - `@dataclass(frozen=True) class ModelSpec: id: str; capability: str; tier: str; runtime: str; artifacts: tuple[Artifact, ...]` with method `artifact_for(platform: str) -> Artifact | None`
  - `MODELS: tuple[ModelSpec, ...]` (static)
  - `by_id(model_id: str) -> ModelSpec | None`
  - `for_capability_tier(capability: str, tier: str) -> ModelSpec | None`

- [ ] **Step 1: Write the failing test**

```python
# packages/model-manager/tests/test_registry.py
from model_manager.registry import (
    by_id, for_capability_tier, MODELS, ModelSpec, CAPABILITIES, PRESETS,
)

def test_sensevoice_is_light_asr_and_cross_platform():
    spec = for_capability_tier("asr", "light")
    assert spec is not None
    assert spec.id == "sensevoice-small-q8"
    # cross-platform GGUF: resolvable on both mac and windows
    assert spec.artifact_for("mac-arm64") is not None
    assert spec.artifact_for("win-x64") is not None

def test_asr_high_is_per_os_distinct():
    spec = for_capability_tier("asr", "high")
    assert spec is not None
    # high-tier ASR resolves to a real artifact on each OS
    assert spec.artifact_for("mac-arm64") is not None
    assert spec.artifact_for("win-x64") is not None

def test_by_id_roundtrip():
    for m in MODELS:
        assert by_id(m.id) is m

def test_by_id_unknown_returns_none():
    assert by_id("does-not-exist") is None

def test_every_model_has_valid_capability_and_tier():
    for m in MODELS:
        assert m.capability in CAPABILITIES
        assert m.tier in (PRESETS + ("fixed",))

def test_artifact_for_unknown_platform_is_none():
    spec = for_capability_tier("embedding", "light")
    assert spec.artifact_for("plan9-sparc") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/model-manager && python -m pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'model_manager.registry'`

- [ ] **Step 3: Write the registry**

> NOTE: `source_urls` are repo-level identifiers verified best-effort at authoring time; `sha256=None` is intentional until a model is pinned (Task 5 verifies only when present). Sizes are approximate for the download-confirm UX.

```python
# packages/model-manager/model_manager/registry.py
"""Static catalogue of downloadable local models, per capability/tier/OS."""
from dataclasses import dataclass

CAPABILITIES = ("asr", "embedding", "vlm", "ocr")
PRESETS = ("light", "high")


@dataclass(frozen=True)
class Artifact:
    platform: str            # platform key, or "any" for cross-platform
    source_urls: list[str]   # ordered: ModelScope first, HuggingFace fallback
    size_mb: int
    sha256: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    id: str
    capability: str          # one of CAPABILITIES
    tier: str                # "light" | "high" | "fixed"
    runtime: str             # "llama.cpp" | "whisperkit" | "whisper.cpp" | "onnx" | "vision" | "mlx"
    artifacts: tuple

    def artifact_for(self, platform: str):
        exact = None
        anyart = None
        for a in self.artifacts:
            if a.platform == platform:
                exact = a
            elif a.platform == "any":
                anyart = a
        return exact or anyart


MODELS = (
    # --- ASR ---
    ModelSpec(
        id="sensevoice-small-q8", capability="asr", tier="light", runtime="llama.cpp",
        artifacts=(
            Artifact("any",
                     ["modelscope://iic/SenseVoiceSmall-GGUF",
                      "https://huggingface.co/funasr/SenseVoiceSmall-GGUF"],
                     size_mb=254),
        ),
    ),
    ModelSpec(
        id="whisper-large-v3", capability="asr", tier="high", runtime="whisper.cpp",
        artifacts=(
            Artifact("mac-arm64",
                     ["modelscope://argmaxinc/whisperkit-coreml-large-v3",
                      "https://huggingface.co/argmaxinc/whisperkit-coreml"],
                     size_mb=600),
            Artifact("win-x64",
                     ["modelscope://ggerganov/whisper.cpp/ggml-large-v3-q5_0.bin",
                      "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin"],
                     size_mb=1080),
            Artifact("mac-x64",
                     ["https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin"],
                     size_mb=1080),
            Artifact("linux-x64",
                     ["https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin"],
                     size_mb=1080),
        ),
    ),
    # --- embedding ---
    ModelSpec(
        id="bge-small-zh-v1.5", capability="embedding", tier="light", runtime="onnx",
        artifacts=(
            Artifact("any",
                     ["modelscope://BAAI/bge-small-zh-v1.5",
                      "https://huggingface.co/BAAI/bge-small-zh-v1.5"],
                     size_mb=100),
        ),
    ),
    ModelSpec(
        id="bge-m3", capability="embedding", tier="high", runtime="onnx",
        artifacts=(
            Artifact("any",
                     ["modelscope://BAAI/bge-m3", "https://huggingface.co/BAAI/bge-m3"],
                     size_mb=2100),
        ),
    ),
    # --- VLM (high only; light == off, so no light spec) ---
    ModelSpec(
        id="paddleocr-vl", capability="vlm", tier="high", runtime="onnx",
        artifacts=(
            Artifact("any",
                     ["modelscope://PaddlePaddle/PaddleOCR-VL",
                      "https://huggingface.co/PaddlePaddle/PaddleOCR-VL"],
                     size_mb=1800),
        ),
    ),
    # --- OCR (fixed per-OS, not a user preset axis) ---
    ModelSpec(
        id="apple-vision", capability="ocr", tier="fixed", runtime="vision",
        artifacts=(Artifact("mac-arm64", [], size_mb=0), Artifact("mac-x64", [], size_mb=0)),
    ),
    ModelSpec(
        id="ppocr-v6-small", capability="ocr", tier="fixed", runtime="onnx",
        artifacts=(
            Artifact("win-x64",
                     ["modelscope://PaddlePaddle/PP-OCRv6-small",
                      "https://huggingface.co/PaddlePaddle/PP-OCRv6"],
                     size_mb=15),
            Artifact("linux-x64",
                     ["https://huggingface.co/PaddlePaddle/PP-OCRv6"], size_mb=15),
        ),
    ),
)


def by_id(model_id: str):
    for m in MODELS:
        if m.id == model_id:
            return m
    return None


def for_capability_tier(capability: str, tier: str):
    for m in MODELS:
        if m.capability == capability and m.tier == tier:
            return m
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/model-manager && python -m pytest tests/test_registry.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/model_manager/registry.py packages/model-manager/tests/test_registry.py
git commit -m "feat(model-manager): static model registry with per-OS artifacts"
```

---

### Task 3: User config (preset + per-capability overrides)

**Files:**
- Create: `packages/model-manager/model_manager/config.py`
- Test: `packages/model-manager/tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass class Config: preset: str = "light"; overrides: dict[str, str] = field(default_factory=dict)`
  - `config_path(state_dir: str | Path) -> Path` → `${state_dir}/models/config.json`
  - `load_config(state_dir) -> Config` (missing/corrupt file → default `Config()`)
  - `save_config(state_dir, config: Config) -> None` (atomic write, creates dirs)

- [ ] **Step 1: Write the failing test**

```python
# packages/model-manager/tests/test_config.py
from model_manager.config import Config, load_config, save_config, config_path

def test_default_config_when_missing(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.preset == "light"
    assert cfg.overrides == {}

def test_save_then_load_roundtrip(tmp_path):
    cfg = Config(preset="high", overrides={"asr": "sensevoice-small-q8"})
    save_config(tmp_path, cfg)
    assert config_path(tmp_path).exists()
    got = load_config(tmp_path)
    assert got.preset == "high"
    assert got.overrides == {"asr": "sensevoice-small-q8"}

def test_corrupt_file_falls_back_to_default(tmp_path):
    p = config_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.preset == "light"

def test_unknown_preset_normalized_to_light(tmp_path):
    p = config_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"preset": "ultra", "overrides": {}}', encoding="utf-8")
    assert load_config(tmp_path).preset == "light"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/model-manager && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'model_manager.config'`

- [ ] **Step 3: Write config.py**

```python
# packages/model-manager/model_manager/config.py
"""User model choices persisted under the plugin state dir."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .registry import PRESETS


@dataclass
class Config:
    preset: str = "light"
    overrides: dict = field(default_factory=dict)   # capability -> model_id


def config_path(state_dir) -> Path:
    return Path(state_dir) / "models" / "config.json"


def load_config(state_dir) -> Config:
    p = config_path(state_dir)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    preset = data.get("preset", "light")
    if preset not in PRESETS:
        preset = "light"
    overrides = data.get("overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    return Config(preset=preset, overrides={str(k): str(v) for k, v in overrides.items()})


def save_config(state_dir, config: Config) -> None:
    p = config_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"preset": config.preset, "overrides": config.overrides},
        ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/model-manager && python -m pytest tests/test_config.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/model_manager/config.py packages/model-manager/tests/test_config.py
git commit -m "feat(model-manager): user config (preset + overrides) with safe load"
```

---

### Task 4: Download / ensure (filesystem + injectable fetch + optional verify)

**Files:**
- Create: `packages/model-manager/model_manager/download.py`
- Test: `packages/model-manager/tests/test_download.py`

**Interfaces:**
- Consumes: `ModelSpec`, `Artifact` (Task 2).
- Produces:
  - `model_dir(models_root, spec) -> Path` → `${models_root}/<capability>/<id>/`
  - `is_present(models_root, spec) -> bool` (a `.done` marker exists)
  - `ensure(models_root, spec, platform, fetcher=None, confirm=None) -> Path` — returns model dir; downloads the platform artifact's `source_urls` (first that succeeds) into the dir if not present, writes `.done`, verifies sha256 when the artifact provides one. `fetcher(url, dest_path)` is injectable (default real). `confirm(size_mb)->bool` optional gate; if it returns False, raise `DownloadDeclined`.
  - Exceptions: `NoArtifactError`, `DownloadDeclined`, `DownloadFailed`, `ChecksumError`.

- [ ] **Step 1: Write the failing test**

```python
# packages/model-manager/tests/test_download.py
import hashlib
import pytest
from model_manager.registry import ModelSpec, Artifact
from model_manager.download import (
    ensure, is_present, model_dir,
    NoArtifactError, DownloadDeclined, DownloadFailed, ChecksumError,
)

def _spec(size=10, sha=None, urls=("modelscope://x", "https://hf/x")):
    return ModelSpec(id="m1", capability="asr", tier="light", runtime="llama.cpp",
                     artifacts=(Artifact("any", list(urls), size_mb=size, sha256=sha),))

def test_ensure_downloads_when_missing(tmp_path):
    calls = []
    def fake(url, dest):
        calls.append(url); dest.write_bytes(b"weights")
    d = ensure(tmp_path, _spec(), "win-x64", fetcher=fake)
    assert d == model_dir(tmp_path, _spec())
    assert (d / "model.bin").read_bytes() == b"weights"
    assert is_present(tmp_path, _spec())
    assert len(calls) == 1  # first URL succeeded

def test_ensure_skips_when_present(tmp_path):
    calls = []
    def fake(url, dest): calls.append(url); dest.write_bytes(b"w")
    ensure(tmp_path, _spec(), "win-x64", fetcher=fake)
    ensure(tmp_path, _spec(), "win-x64", fetcher=fake)  # second call
    assert len(calls) == 1  # not re-downloaded

def test_ensure_falls_back_to_next_url(tmp_path):
    def fake(url, dest):
        if url.startswith("modelscope"):
            raise OSError("modelscope down")
        dest.write_bytes(b"w")
    ensure(tmp_path, _spec(), "win-x64", fetcher=fake)
    assert is_present(tmp_path, _spec())

def test_ensure_raises_when_all_urls_fail(tmp_path):
    def fake(url, dest): raise OSError("nope")
    with pytest.raises(DownloadFailed):
        ensure(tmp_path, _spec(), "win-x64", fetcher=fake)

def test_ensure_verifies_sha256(tmp_path):
    good = hashlib.sha256(b"weights").hexdigest()
    def fake(url, dest): dest.write_bytes(b"weights")
    ensure(tmp_path, _spec(sha=good), "win-x64", fetcher=fake)  # passes
    def fake_bad(url, dest): dest.write_bytes(b"tampered")
    with pytest.raises(ChecksumError):
        ensure(tmp_path, _spec(sha=good), "win-x64", fetcher=fake_bad)

def test_ensure_respects_confirm_decline(tmp_path):
    def fake(url, dest): dest.write_bytes(b"w")
    with pytest.raises(DownloadDeclined):
        ensure(tmp_path, _spec(size=999), "win-x64", fetcher=fake, confirm=lambda mb: False)

def test_ensure_no_artifact_for_platform(tmp_path):
    spec = ModelSpec(id="m2", capability="ocr", tier="fixed", runtime="vision",
                     artifacts=(Artifact("mac-arm64", [], 0),))
    with pytest.raises(NoArtifactError):
        ensure(tmp_path, spec, "win-x64", fetcher=lambda u, d: None)

def test_ensure_zero_size_artifact_is_present_without_download(tmp_path):
    # e.g. Apple Vision: no files to fetch, but must count as present
    spec = ModelSpec(id="apple-vision", capability="ocr", tier="fixed", runtime="vision",
                     artifacts=(Artifact("mac-arm64", [], 0),))
    d = ensure(tmp_path, spec, "mac-arm64", fetcher=lambda u, dst: None)
    assert is_present(tmp_path, spec)
    assert d.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/model-manager && python -m pytest tests/test_download.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'model_manager.download'`

- [ ] **Step 3: Write download.py**

```python
# packages/model-manager/model_manager/download.py
"""Lazy, injectable, verified model download into the state dir."""
import hashlib
from pathlib import Path
from urllib.request import urlopen


class NoArtifactError(Exception): ...
class DownloadDeclined(Exception): ...
class DownloadFailed(Exception): ...
class ChecksumError(Exception): ...


def model_dir(models_root, spec) -> Path:
    return Path(models_root) / spec.capability / spec.id


def is_present(models_root, spec) -> bool:
    return (model_dir(models_root, spec) / ".done").exists()


def _default_fetcher(url: str, dest: Path) -> None:
    # ModelScope pseudo-URL "modelscope://<repo>/<file?>" -> resolve to https.
    real = _modelscope_to_https(url) if url.startswith("modelscope://") else url
    with urlopen(real, timeout=60) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def _modelscope_to_https(url: str) -> str:
    repo = url[len("modelscope://"):]
    return "https://modelscope.cn/models/%s/resolve/master" % repo


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure(models_root, spec, platform, fetcher=None, confirm=None) -> Path:
    art = spec.artifact_for(platform)
    if art is None:
        raise NoArtifactError("%s has no artifact for %s" % (spec.id, platform))
    d = model_dir(models_root, spec)
    if is_present(models_root, spec):
        return d
    d.mkdir(parents=True, exist_ok=True)

    # Zero-URL artifact (e.g. OS-provided Apple Vision): mark present, no fetch.
    if not art.source_urls:
        (d / ".done").write_text("ok", encoding="utf-8")
        return d

    if confirm is not None and not confirm(art.size_mb):
        raise DownloadDeclined("user declined download of %s (%d MB)" % (spec.id, art.size_mb))

    fetch = fetcher or _default_fetcher
    dest = d / "model.bin"
    last_err = None
    for url in art.source_urls:
        try:
            fetch(url, dest)
            break
        except Exception as e:  # try next mirror
            last_err = e
    else:
        raise DownloadFailed("all sources failed for %s: %s" % (spec.id, last_err))

    if art.sha256 is not None:
        got = _sha256(dest)
        if got != art.sha256:
            dest.unlink(missing_ok=True)
            raise ChecksumError("%s sha256 mismatch: %s != %s" % (spec.id, got, art.sha256))

    (d / ".done").write_text("ok", encoding="utf-8")
    return d
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/model-manager && python -m pytest tests/test_download.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/model_manager/download.py packages/model-manager/tests/test_download.py
git commit -m "feat(model-manager): lazy verified download with mirror fallback"
```

---

### Task 5: ModelManager (resolve + ensure + status + set + prefetch)

**Files:**
- Create: `packages/model-manager/model_manager/manager.py`
- Modify: `packages/model-manager/model_manager/__init__.py`
- Test: `packages/model-manager/tests/test_manager.py`

**Interfaces:**
- Consumes: `current_platform` (T1), `registry` (T2), `Config`/`load_config`/`save_config` (T3), `ensure`/`is_present`/`model_dir` (T4).
- Produces `class ModelManager`:
  - `__init__(self, state_dir, platform: str | None = None)` (platform defaults to `current_platform()`; models under `${state_dir}/models`)
  - `resolve(self, capability: str) -> ModelSpec | None` — override wins; else preset→tier; `vlm` light → `None` (off); `ocr` → the fixed spec whose artifact matches this platform.
  - `ensure(self, capability, fetcher=None, confirm=None) -> Path | None` — resolve then download; `None` if capability is off (vlm light).
  - `status(self) -> dict` — `{preset, platform, capabilities: {cap: {selected_id, tier, present, size_mb}}}`.
  - `set_choice(self, capability, tier_or_model_id) -> None` — validate against registry for this capability, persist as override; `"light"`/`"high"` accepted and mapped to that capability's tier model; `"off"` valid only for `vlm`.
  - `set_preset(self, preset) -> None`
  - `prefetch(self, fetcher=None, confirm=None) -> dict` — ensure all resolvable (non-off) capabilities; returns `{cap: "ok"|"declined"|"error:..."}`.

- [ ] **Step 1: Write the failing test**

```python
# packages/model-manager/tests/test_manager.py
import pytest
from model_manager.manager import ModelManager

def _fake_fetch(url, dest): dest.write_bytes(b"w")

def test_resolve_light_defaults(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    assert mm.resolve("asr").id == "sensevoice-small-q8"
    assert mm.resolve("embedding").id == "bge-small-zh-v1.5"
    assert mm.resolve("vlm") is None            # light == off
    assert mm.resolve("ocr").id == "ppocr-v6-small"

def test_resolve_ocr_is_apple_vision_on_mac(tmp_path):
    mm = ModelManager(tmp_path, platform="mac-arm64")
    assert mm.resolve("ocr").id == "apple-vision"

def test_high_preset_switches_all(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    mm.set_preset("high")
    assert mm.resolve("asr").id == "whisper-large-v3"
    assert mm.resolve("embedding").id == "bge-m3"
    assert mm.resolve("vlm").id == "paddleocr-vl"

def test_per_capability_override_wins(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")           # light preset
    mm.set_choice("asr", "high")                              # override just ASR
    assert mm.resolve("asr").id == "whisper-large-v3"
    assert mm.resolve("embedding").id == "bge-small-zh-v1.5"  # still light

def test_override_persists_across_instances(tmp_path):
    ModelManager(tmp_path, platform="win-x64").set_choice("embedding", "high")
    mm2 = ModelManager(tmp_path, platform="win-x64")
    assert mm2.resolve("embedding").id == "bge-m3"

def test_set_choice_off_only_valid_for_vlm(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    mm.set_preset("high")
    mm.set_choice("vlm", "off")
    assert mm.resolve("vlm") is None
    with pytest.raises(ValueError):
        mm.set_choice("asr", "off")

def test_set_choice_rejects_wrong_capability_model(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    with pytest.raises(ValueError):
        mm.set_choice("asr", "bge-m3")   # embedding model, not asr

def test_ensure_downloads_resolved_model(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    d = mm.ensure("asr", fetcher=_fake_fetch)
    assert (d / "model.bin").exists()

def test_ensure_off_capability_returns_none(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")   # vlm off in light
    assert mm.ensure("vlm", fetcher=_fake_fetch) is None

def test_status_reports_selection_and_presence(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    st = mm.status()
    assert st["preset"] == "light"
    assert st["platform"] == "win-x64"
    assert st["capabilities"]["asr"]["selected_id"] == "sensevoice-small-q8"
    assert st["capabilities"]["asr"]["present"] is False
    mm.ensure("asr", fetcher=_fake_fetch)
    assert mm.status()["capabilities"]["asr"]["present"] is True
    assert st["capabilities"]["vlm"]["selected_id"] is None   # off

def test_prefetch_ensures_all_non_off(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    res = mm.prefetch(fetcher=_fake_fetch)
    assert res["asr"] == "ok"
    assert res["embedding"] == "ok"
    assert res["ocr"] == "ok"
    assert res["vlm"] == "off"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/model-manager && python -m pytest tests/test_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'model_manager.manager'`

- [ ] **Step 3: Write manager.py and update `__init__.py`**

```python
# packages/model-manager/model_manager/manager.py
"""Orchestration: resolve (config+preset+platform) then lazily ensure downloads."""
from pathlib import Path

from .platform import current_platform
from .registry import CAPABILITIES, PRESETS, by_id, for_capability_tier
from .config import load_config, save_config
from .download import ensure as _ensure, is_present, model_dir, DownloadDeclined

USER_TIERED = ("asr", "embedding", "vlm")   # capabilities with a user preset axis


class ModelManager:
    def __init__(self, state_dir, platform: str | None = None):
        self.state_dir = Path(state_dir)
        self.models_root = self.state_dir / "models"
        self.platform = platform or current_platform()

    # --- resolution ---
    def resolve(self, capability: str):
        cfg = load_config(self.state_dir)
        if capability == "ocr":
            return self._resolve_ocr()
        override = cfg.overrides.get(capability)
        if override == "off":
            return None
        if override:
            spec = by_id(override)
            if spec and spec.capability == capability:
                return spec
        # fall back to preset tier
        tier = cfg.preset
        if capability == "vlm" and tier == "light":
            return None                      # vlm light == off
        return for_capability_tier(capability, tier)

    def _resolve_ocr(self):
        for tier in ("fixed",):
            for cap_model in (m for m in _ocr_models() if m.artifact_for(self.platform)):
                return cap_model
        return None

    # --- choices ---
    def set_preset(self, preset: str) -> None:
        if preset not in PRESETS:
            raise ValueError("unknown preset %r" % preset)
        cfg = load_config(self.state_dir)
        cfg.preset = preset
        save_config(self.state_dir, cfg)

    def set_choice(self, capability: str, tier_or_model_id: str) -> None:
        if capability not in USER_TIERED:
            raise ValueError("capability %r is not user-selectable" % capability)
        cfg = load_config(self.state_dir)
        val = tier_or_model_id
        if val == "off":
            if capability != "vlm":
                raise ValueError("only vlm may be turned off")
            cfg.overrides[capability] = "off"
        elif val in PRESETS:
            spec = for_capability_tier(capability, val)
            if spec is None:
                raise ValueError("no %s model for tier %r" % (capability, val))
            cfg.overrides[capability] = spec.id
        else:
            spec = by_id(val)
            if spec is None or spec.capability != capability:
                raise ValueError("%r is not a %s model" % (val, capability))
            cfg.overrides[capability] = spec.id
        save_config(self.state_dir, cfg)

    # --- download ---
    def ensure(self, capability, fetcher=None, confirm=None):
        spec = self.resolve(capability)
        if spec is None:
            return None
        return _ensure(self.models_root, spec, self.platform, fetcher=fetcher, confirm=confirm)

    def prefetch(self, fetcher=None, confirm=None) -> dict:
        out = {}
        for cap in CAPABILITIES:
            spec = self.resolve(cap)
            if spec is None:
                out[cap] = "off"
                continue
            try:
                self.ensure(cap, fetcher=fetcher, confirm=confirm)
                out[cap] = "ok"
            except DownloadDeclined:
                out[cap] = "declined"
            except Exception as e:
                out[cap] = "error:%s" % e
        return out

    # --- status ---
    def status(self) -> dict:
        cfg = load_config(self.state_dir)
        caps = {}
        for cap in CAPABILITIES:
            spec = self.resolve(cap)
            if spec is None:
                caps[cap] = {"selected_id": None, "tier": None, "present": False, "size_mb": 0}
                continue
            art = spec.artifact_for(self.platform)
            caps[cap] = {
                "selected_id": spec.id,
                "tier": spec.tier,
                "present": is_present(self.models_root, spec),
                "size_mb": art.size_mb if art else 0,
            }
        return {"preset": cfg.preset, "platform": self.platform, "capabilities": caps}


def _ocr_models():
    from .registry import MODELS
    return [m for m in MODELS if m.capability == "ocr"]
```

```python
# packages/model-manager/model_manager/__init__.py
from .platform import current_platform
from .registry import ModelSpec, Artifact, MODELS, by_id, for_capability_tier
from .manager import ModelManager

__all__ = [
    "current_platform", "ModelSpec", "Artifact", "MODELS",
    "by_id", "for_capability_tier", "ModelManager",
]
```

- [ ] **Step 4: Run the full suite**

Run: `cd packages/model-manager && python -m pytest -v`
Expected: PASS (all tests across the 5 files — platform 6, registry 6, config 4, download 8, manager 11 = 35)

- [ ] **Step 5: Commit**

```bash
git add packages/model-manager/model_manager/manager.py packages/model-manager/model_manager/__init__.py packages/model-manager/tests/test_manager.py
git commit -m "feat(model-manager): ModelManager resolve/ensure/status/set/prefetch"
```

---

### Task 6: README + editable install sanity

**Files:**
- Create: `packages/model-manager/README.md`
- Test: (manual smoke, no new pytest)

**Interfaces:** none new — documents the public API from Task 5.

- [ ] **Step 1: Write the README**

````markdown
# model-manager

Tiered local-model manager for the wechat-cc enrichment plugins. Picks, resolves
(per-OS), lazily downloads, and tracks models via a global preset (`light`/`high`)
plus per-capability overrides (`asr`, `embedding`, `vlm`).

```python
from model_manager import ModelManager
mm = ModelManager(state_dir)          # state_dir = ${dataDir}
mm.set_preset("high")                 # or leave default "light"
mm.set_choice("asr", "light")         # per-capability override; "off" only for vlm
spec = mm.resolve("asr")              # -> ModelSpec | None (None = off)
path = mm.ensure("asr", confirm=lambda mb: mb < 500)   # lazy download
mm.status()                           # selections + presence, for MCP tools
mm.prefetch()                         # download everything for current config
```

Models live under `${state_dir}/models/<capability>/<id>/`; choices in
`${state_dir}/models/config.json`. Downloads try ModelScope first, HuggingFace
fallback; sha256 verified when the registry pins it. No third-party runtime deps.
````

- [ ] **Step 2: Verify editable install + suite**

Run: `cd packages/model-manager && pip install -e ".[test]" && python -m pytest -v`
Expected: install succeeds; all 35 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/model-manager/README.md
git commit -m "docs(model-manager): usage README"
```

---

## Self-Review

**1. Spec coverage** (spec §5 model-manager): tier registry ✓ (T2), per-OS resolution ✓ (T5 `resolve`+`_resolve_ocr`), config in `${dataDir}/models/config.json` ✓ (T3), lazy download ModelScope-primary/HF-fallback with size-confirm ✓ (T4 `confirm`, mirror loop, `_modelscope_to_https`), sha verify-when-present ✓ (T4), `resolve/ensure/status/set/prefetch` interface ✓ (T5), two presets + override + vlm-off ✓ (T5), deps-follow-config → deferred to the wxmedia plan (model-manager itself has no runtime deps; installing per-config ML runtimes belongs to the consuming plugin's setup). Noted, not a gap in this package.

**2. Placeholder scan:** No TBD/TODO. `sha256=None` and best-effort `source_urls` are intentional, documented data (verified/pinned as models are chosen), and the code path handles both — not placeholders.

**3. Type consistency:** `ModelSpec.artifact_for`, `Artifact.source_urls/size_mb/sha256`, `Config.preset/overrides`, `ensure(models_root, spec, platform, fetcher, confirm)`, `ModelManager.resolve/ensure/status/set_choice/set_preset/prefetch` — names/signatures match across T2→T5 tests and impl. `USER_TIERED` vs `CAPABILITIES` used consistently.

**Out of scope (this plan):** wxmedia (#1 media→text — next plan), wxsearch (#3), wxgraph (#2), reranker, actual ML-runtime installation.
