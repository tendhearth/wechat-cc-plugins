import sqlite3
from pathlib import Path
from wxmedia.voice_source import find_media_dbs, iter_voice

def _make_media_db(state_dir, name, rows):
    d = Path(state_dir) / "out" / "decrypted"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / name))
    con.execute("CREATE TABLE VoiceInfo (svr_id INTEGER, local_id INTEGER, voice_data BLOB)")
    con.executemany("INSERT INTO VoiceInfo VALUES (?,?,?)", rows)
    con.commit(); con.close()

def test_find_media_dbs(tmp_path):
    _make_media_db(tmp_path, "media_0.sqlite", [])
    _make_media_db(tmp_path, "media_1.sqlite", [])
    assert len(find_media_dbs(tmp_path)) == 2

def test_iter_voice_yields_nonempty(tmp_path):
    _make_media_db(tmp_path, "media_0.sqlite",
                   [(100, 1, b"\x02silkdata"), (0, 0, b""), (200, 2, b"\x02more")])
    got = list(iter_voice(tmp_path))
    assert {g["svr_id"] for g in got} == {"100", "200"}
    assert got[0]["voice_data"].startswith(b"\x02")

def test_iter_voice_local_fallback_id(tmp_path):
    _make_media_db(tmp_path, "media_0.sqlite", [(0, 42, b"\x02x")])
    got = list(iter_voice(tmp_path))
    assert got[0]["svr_id"] == "local_42"

def test_iter_voice_no_dbs_is_empty(tmp_path):
    assert list(iter_voice(tmp_path)) == []
