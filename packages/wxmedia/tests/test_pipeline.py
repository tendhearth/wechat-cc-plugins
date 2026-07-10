import sqlite3
from pathlib import Path
from wxmedia.pipeline import transcribe_all
from wxmedia.store import DerivedStore

def _media_db(state_dir, rows):
    d = Path(state_dir) / "out" / "decrypted"; d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "media_0.sqlite"))
    con.execute("CREATE TABLE VoiceInfo (svr_id INTEGER, local_id INTEGER, voice_data BLOB)")
    con.executemany("INSERT INTO VoiceInfo VALUES (?,?,?)", rows); con.commit(); con.close()

class FakePilk:
    @staticmethod
    def silk_to_wav(silk, wav, rate): Path(wav).write_bytes(b"RIFF")

class FakeRunner:
    model_id = "fake-asr"
    def __init__(self, mapping=None, fail_on=()): self.mapping = mapping or {}; self.fail_on = fail_on
    def transcribe(self, wav_path):
        name = Path(wav_path).stem
        if name in self.fail_on: raise RuntimeError("boom")
        return self.mapping.get(name, "text-%s" % name)

def test_transcribes_and_stores(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a"), (200, 2, b"\x02b")])
    res = transcribe_all(tmp_path, FakeRunner({"100": "你好", "200": "在吗"}), pilk_mod=FakePilk)
    assert res == {"processed": 2, "skipped": 0, "failed": 0}
    s = DerivedStore(tmp_path)
    assert s.get("100")["text"] == "你好"
    assert s.get("200")["model_id"] == "fake-asr"

def test_incremental_skips_existing(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a")])
    transcribe_all(tmp_path, FakeRunner(), pilk_mod=FakePilk)
    res = transcribe_all(tmp_path, FakeRunner(), pilk_mod=FakePilk)  # second run
    assert res == {"processed": 0, "skipped": 1, "failed": 0}

def test_single_failure_does_not_abort(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a"), (200, 2, b"\x02b")])
    res = transcribe_all(tmp_path, FakeRunner(fail_on=("100",)), pilk_mod=FakePilk)
    assert res == {"processed": 1, "skipped": 0, "failed": 1}
    assert DerivedStore(tmp_path).get("200") is not None
    assert DerivedStore(tmp_path).get("100") is None

def test_work_wavs_cleaned_up(tmp_path):
    _media_db(tmp_path, [(100, 1, b"\x02a")])
    transcribe_all(tmp_path, FakeRunner(), pilk_mod=FakePilk)
    work = tmp_path / "wxmedia" / "work"
    assert not list(work.glob("*.wav")) if work.exists() else True
