"""Static catalogue of downloadable local models, per capability/tier/OS."""
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
