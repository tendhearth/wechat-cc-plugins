"""Static catalogue of downloadable local models, per capability/tier/OS."""
from __future__ import annotations   # defer PEP-604 (str | None) so this imports under Python 3.9 too
from dataclasses import dataclass

from .platform import PLATFORMS

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
    artifacts: tuple[Artifact, ...]

    def artifact_for(self, platform: str) -> Artifact | None:
        exact = None
        anyart = None
        for a in self.artifacts:
            if a.platform == platform:
                exact = a
            elif a.platform == "any" and platform in PLATFORMS:
                anyart = a
        return exact or anyart


MODELS = (
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


def by_id(model_id: str) -> ModelSpec | None:
    for m in MODELS:
        if m.id == model_id:
            return m
    return None


def for_capability_tier(capability: str, tier: str) -> ModelSpec | None:
    for m in MODELS:
        if m.capability == capability and m.tier == tier:
            return m
    return None
