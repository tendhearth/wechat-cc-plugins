import hashlib
import sqlite3
import zstandard
from pathlib import Path

from wxfacts.source import iter_1to1_messages, encode_batch_id, decode_batch_id


def _tbl(u):
    return "Msg_" + hashlib.md5(u.encode()).hexdigest()


def _make_db(dirpath, name2id, tables):
    dec = Path(dirpath) / "out" / "decrypted"
    dec.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dec / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id(rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id(rowid,user_name,is_session) VALUES(?,?,?)", name2id)
    for conv, rows in tables.items():
        t = _tbl(conv)
        con.execute('CREATE TABLE "%s"(local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, '
                    'create_time INTEGER, server_id INTEGER, message_content)' % t)
        con.executemany('INSERT INTO "%s" VALUES(?,?,?,?,?,?)' % t, rows)
    con.commit(); con.close()


def test_batch_id_roundtrip():
    bid = encode_batch_id("wxid_a", 12345, 7)
    assert decode_batch_id(bid) == ("wxid_a", 12345, 7)
    # pre-cursor batch_ids (no "l") decode with local_id 0
    assert decode_batch_id('{"c": "wxid_a", "u": 12345}') == ("wxid_a", 12345, 0)


def test_yields_text_1to1_with_msg_key_and_skips_group_and_nontext(tmp_path):
    me, a, grp = "wxid_me", "wxid_a", "room@chatroom"
    blob = zstandard.ZstdCompressor().compress("压缩的一句话".encode())
    _make_db(tmp_path,
             [(1, me, 0), (2, a, 1), (3, grp, 1)],
             {a: [(10, 1, 1, 100, 0, "hello there"),        # 1:1 text (from me)
                  (11, 1, 2, 101, 0, sqlite3.Binary(blob)),  # 1:1 text (zstd, from a)
                  (12, 3, 2, 102, 0, "x"),                   # image -> skipped
                  (13, 1, 2, 103, 0, "   ")],                # blank -> skipped
              grp: [(20, 1, 2, 200, 0, "group talk")]})      # group -> skipped
    msgs = {m["msg_key"]: m for m in iter_1to1_messages(tmp_path)}
    assert set(msgs) == {"%s:10" % _tbl(a), "%s:11" % _tbl(a)}
    assert msgs["%s:10" % _tbl(a)] == {"msg_key": "%s:10" % _tbl(a), "conversation": a,
                                       "sender_un": me, "ts": 100, "local_id": 10, "text": "hello there"}
    assert msgs["%s:11" % _tbl(a)]["text"] == "压缩的一句话"   # zstd decoded
    assert msgs["%s:11" % _tbl(a)]["sender_un"] == a
