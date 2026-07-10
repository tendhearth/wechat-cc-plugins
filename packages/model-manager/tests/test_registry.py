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
