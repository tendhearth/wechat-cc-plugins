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

def test_set_choice_vlm_light_means_off(tmp_path):
    mm = ModelManager(tmp_path, platform="win-x64")
    mm.set_preset("high")            # vlm would be paddleocr-vl
    mm.set_choice("vlm", "light")    # light == off for vlm
    assert mm.resolve("vlm") is None

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
