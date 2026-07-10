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
