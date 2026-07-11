from model_manager.registry import (
    by_id, for_capability_tier, MODELS, ModelSpec, CAPABILITIES, PRESETS,
)

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
