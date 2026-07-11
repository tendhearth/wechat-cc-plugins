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
