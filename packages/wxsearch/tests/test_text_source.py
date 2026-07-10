import sqlite3
from pathlib import Path
from wxsearch.text_source import iter_chunks

def _msg_db(state_dir, table, name2id_rows, msg_rows):
    d = Path(state_dir) / "out" / "decrypted"; d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id (rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id(rowid,user_name,is_session) VALUES(?,?,?)", name2id_rows)
    con.execute("CREATE TABLE '%s' (local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, "
                "create_time INTEGER, server_id INTEGER, message_content TEXT)" % table)
    con.executemany("INSERT INTO '%s' VALUES(?,?,?,?,?,?)" % table, msg_rows)
    con.commit(); con.close()

def _derived(state_dir, rows):
    d = Path(state_dir) / "wxmedia"; d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "derived.sqlite"))
    con.execute("CREATE TABLE media_text (svr_id TEXT PRIMARY KEY, kind TEXT, text TEXT, model_id TEXT, created_at INTEGER)")
    con.executemany("INSERT INTO media_text VALUES(?,?,?,?,?)", rows)
    con.commit(); con.close()

TBL = "Msg_" + "a"*32

def test_text_message_content_and_prefix_strip(tmp_path):
    _msg_db(tmp_path, TBL,
            [(1, "grp@chatroom", 1), (2, "alice", 0)],
            [(10, 1, 2, 1720000000, 100, "alice:\n你好世界"),   # text, group prefix
             (11, 3, 2, 1720000001, 101, "<img/>")])            # non-text (type 3) -> skipped w/o derived
    got = {c["msg_key"]: c for c in iter_chunks(tmp_path)}
    assert (TBL + ":10") in got
    c = got[TBL + ":10"]
    assert c["text"] == "你好世界"          # sender prefix stripped
    assert c["conversation"] == "grp@chatroom"
    assert c["sender"] == "alice"           # real_sender_id 2 -> Name2Id
    assert c["time"] == 1720000000
    assert c["type"] == "text"
    assert (TBL + ":11") not in got         # non-text w/o derived text skipped

def test_media_message_uses_wxmedia_derived_text(tmp_path):
    _msg_db(tmp_path, TBL, [(1,"grp@chatroom",1)],
            [(20, 34, 1, 1720000005, 500, "")])   # type 34 = voice, empty content
    _derived(tmp_path, [("500", "voice", "这是语音转录", "m", 1)])
    got = {c["msg_key"]: c for c in iter_chunks(tmp_path)}
    c = got[TBL + ":20"]
    assert c["text"] == "这是语音转录"
    assert c["type"] == "voice"

def test_empty_text_skipped(tmp_path):
    _msg_db(tmp_path, TBL, [(1,"grp@chatroom",1)], [(30, 1, 1, 1, 600, "x:\n   ")])
    assert list(iter_chunks(tmp_path)) == []    # whitespace-only text dropped

def test_no_dbs_empty(tmp_path):
    assert list(iter_chunks(tmp_path)) == []
