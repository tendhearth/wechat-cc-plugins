from wxmedia.asr import SenseVoiceRunner, _parse_output


class FakeMM:
    def resolve(self, cap):
        class S:
            id = "sensevoice-small-q8"
            runtime = "llama.cpp"
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

        class R:
            returncode = 0
            stdout = "transcript: 你好世界\n"
            stderr = ""

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
        class R:
            returncode = 1
            stdout = ""
            stderr = "err"

        return R()

    monkeypatch.setattr("wxmedia.asr.subprocess.run", fake_run)
    r = SenseVoiceRunner(FakeMM(), runner_cmd=lambda d, w: ["x"])
    import pytest

    with pytest.raises(RuntimeError):
        r.transcribe("/tmp/1.wav")
