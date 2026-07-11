import hashlib
import sqlite3
from pathlib import Path

import zstandard

from wxsearch.text_source import iter_chunks, _to_text


def _tbl(username):
    return "Msg_" + hashlib.md5(username.encode()).hexdigest()


def _setup(tmp_path, name2id, tables):
    """name2id: list of (rowid, user_name, is_session).
    tables: {table_name: [(local_id, local_type, real_sender_id, create_time, server_id, message_content), ...]}."""
    dec = tmp_path / "out" / "decrypted"
    dec.mkdir(parents=True)
    con = sqlite3.connect(str(dec / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id(rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id(rowid,user_name,is_session) VALUES(?,?,?)", name2id)
    for t, rows in tables.items():
        con.execute('CREATE TABLE "%s"(local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, '
                    'create_time INTEGER, server_id INTEGER, message_content)' % t)
        con.executemany('INSERT INTO "%s" VALUES(?,?,?,?,?,?)' % t, rows)
    con.commit(); con.close()


def _derived(tmp_path, rows):
    """rows: list of (svr_id, kind, text)."""
    d = tmp_path / "wxmedia"
    d.mkdir(parents=True)
    con = sqlite3.connect(str(d / "derived.sqlite"))
    con.execute("CREATE TABLE media_text(svr_id TEXT, kind TEXT, text TEXT, model_id TEXT, created_at INTEGER)")
    con.executemany("INSERT INTO media_text(svr_id,kind,text) VALUES(?,?,?)", rows)
    con.commit(); con.close()


def test_no_dbs_yields_nothing(tmp_path):
    assert list(iter_chunks(tmp_path)) == []


def test_to_text_strips_exact_sender_only():
    assert _to_text("alice:\nhi", "alice") == "hi"
    assert _to_text("alice:hi", "alice") == "hi"
    assert _to_text("18:30\nhi", "alice") == "18:30\nhi"   # bare colon is NOT a sender prefix
    assert _to_text(None, "alice") == ""


def test_text_prefix_stripped_with_exact_sender(tmp_path):
    grp = "grp@chatroom"
    _setup(tmp_path,
           [(1, grp, 1), (2, "alice", 0)],
           {_tbl(grp): [(10, 1, 2, 1000, None, "alice:\n大家好")]})
    chunks = list(iter_chunks(tmp_path))
    assert len(chunks) == 1
    c = chunks[0]
    assert c["conversation"] == grp          # exercises the real Msg_<md5> -> Name2Id mapping
    assert c["sender"] == "alice"
    assert c["text"] == "大家好"
    assert c["type"] == "text"
    assert c["msg_key"] == "%s:10" % _tbl(grp)
    assert c["time"] == 1000


def test_colon_in_body_not_stripped(tmp_path):
    grp = "grp@chatroom"
    _setup(tmp_path,
           [(1, grp, 1), (2, "alice", 0)],
           {_tbl(grp): [(10, 1, 2, 1000, None, "18:30\n开会")]})
    c = list(iter_chunks(tmp_path))[0]
    assert c["text"] == "18:30\n开会"


def test_message_with_no_prefix_preserved(tmp_path):
    un = "bob"
    _setup(tmp_path,
           [(1, un, 1)],
           {_tbl(un): [(10, 1, 1, 1000, None, "你好\n第二行")]})
    c = list(iter_chunks(tmp_path))[0]
    assert c["text"] == "你好\n第二行"


def test_zstd_compressed_content_decoded(tmp_path):
    un = "bob"
    body = "这是一条被压缩的长消息" * 20
    comp = zstandard.ZstdCompressor().compress(body.encode())
    _setup(tmp_path,
           [(1, un, 1)],
           {_tbl(un): [(10, 1, 1, 1000, None, sqlite3.Binary(comp))]})
    c = list(iter_chunks(tmp_path))[0]
    assert c["text"] == body


def test_media_joined_by_server_id(tmp_path):
    un = "bob"
    _setup(tmp_path,
           [(1, un, 1)],
           {_tbl(un): [(10, 34, 1, 1000, 999, None)]})     # voice, real server_id
    _derived(tmp_path, [("999", "voice", "语音转写内容")])
    c = list(iter_chunks(tmp_path))[0]
    assert c["type"] == "voice"
    assert c["text"] == "语音转写内容"


def test_media_joined_by_local_fallback(tmp_path):
    un = "bob"
    _setup(tmp_path,
           [(1, un, 1)],
           {_tbl(un): [(10, 3, 1, 1000, None, None)]})      # image, no server_id
    _derived(tmp_path, [("local_10", "image", "OCR文本")])
    c = list(iter_chunks(tmp_path))[0]
    assert c["type"] == "image"
    assert c["text"] == "OCR文本"


def test_media_without_derived_skipped(tmp_path):
    un = "bob"
    _setup(tmp_path,
           [(1, un, 1)],
           {_tbl(un): [(10, 34, 1, 1000, 999, None)]})      # no derived db at all
    assert list(iter_chunks(tmp_path)) == []


def test_empty_text_skipped(tmp_path):
    un = "bob"
    _setup(tmp_path,
           [(1, un, 1)],
           {_tbl(un): [(10, 1, 1, 1000, None, "   "), (11, 1, 1, 1000, None, "有效")]})
    texts = [c["text"] for c in iter_chunks(tmp_path)]
    assert texts == ["有效"]
