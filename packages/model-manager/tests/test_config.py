from model_manager.config import Config, load_config, save_config, config_path

def test_default_config_when_missing(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.preset == "light"
    assert cfg.overrides == {}

def test_save_then_load_roundtrip(tmp_path):
    cfg = Config(preset="high", overrides={"asr": "whisper-small"})
    save_config(tmp_path, cfg)
    assert config_path(tmp_path).exists()
    got = load_config(tmp_path)
    assert got.preset == "high"
    assert got.overrides == {"asr": "whisper-small"}

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

import pytest

@pytest.mark.parametrize("bad", ["[1,2,3]", "null", "42", '"hello"'])
def test_non_dict_json_falls_back_to_default(tmp_path, bad):
    p = config_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(bad, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.preset == "light"
    assert cfg.overrides == {}
