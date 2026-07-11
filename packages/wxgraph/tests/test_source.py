import hashlib
import sqlite3
import zstandard
from pathlib import Path

from wxgraph.source import iter_messages, detect_owner, classify_type, zstd_text


def _tbl(username):
    return "Msg_" + hashlib.md5(username.encode()).hexdigest()


def _make_db(dirpath, name2id, tables):
    """name2id: [(rowid, user_name, is_session)]; tables: {conv_username: [(local_id, local_type, real_sender_id, create_time, server_id, message_content)]}."""
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


def test_zstd_text_variants():
    assert zstd_text(None) == ""
    assert zstd_text("hi") == "hi"
    blob = zstandard.ZstdCompressor().compress("压缩正文".encode())
    assert zstd_text(blob) == "压缩正文"


def test_classify_type_basic_and_app_subtypes():
    assert classify_type(1, None) == "text"
    assert classify_type(34, None) == "voice"
    assert classify_type(50, None) == "call"
    assert classify_type(49, "<msg><appmsg><type>2000</type></appmsg></msg>") == "transfer"
    assert classify_type(49, "<msg><appmsg><type>2001</type></appmsg></msg>") == "redpacket"
    assert classify_type(49, "<msg><appmsg><type>6</type></appmsg></msg>") == "file"
    assert classify_type(49, "<msg><appmsg><refermsg>x</refermsg><type>57</type></appmsg></msg>") == "quote"


def test_iter_messages_resolves_conv_sender_and_group_flag(tmp_path):
    me, friend, grp = "wxid_me", "wxid_friend", "room1@chatroom"
    _make_db(tmp_path,
             [(1, me, 0), (2, friend, 1), (3, grp, 1)],
             {friend: [(10, 1, 1, 100, 0, "hi from me"), (11, 1, 2, 101, 0, "hi back")],
              grp:    [(20, 1, 2, 200, 0, "in group")]})
    msgs = list(iter_messages(tmp_path))
    by_ts = {m["ts"]: m for m in msgs}
    assert by_ts[100]["conversation"] == friend and by_ts[100]["sender_un"] == me and by_ts[100]["is_group"] is False
    assert by_ts[101]["sender_un"] == friend
    assert by_ts[200]["is_group"] is True and by_ts[200]["sender_un"] == friend
    # non-group text: content not needed -> None
    assert by_ts[100]["content"] is None


def test_iter_messages_decodes_content_for_group_and_app(tmp_path):
    friend, grp = "wxid_friend", "room1@chatroom"
    blob = zstandard.ZstdCompressor().compress("<msg>群里说的</msg>".encode())
    _make_db(tmp_path,
             [(1, "wxid_me", 0), (2, friend, 1), (3, grp, 1)],
             {friend: [(10, 49, 1, 100, 0, "<msg><appmsg><type>6</type></appmsg></msg>")],
              grp:    [(20, 1, 2, 200, 0, sqlite3.Binary(blob))]})
    by_ts = {m["ts"]: m for m in iter_messages(tmp_path)}
    assert by_ts[100]["content"] is not None and "<type>6" in by_ts[100]["content"]   # ltype 49 -> decoded
    assert by_ts[200]["content"] == "<msg>群里说的</msg>"                              # group -> decoded (zstd)


def test_detect_owner_infers_from_one_to_one(tmp_path):
    me, a, b = "wxid_me", "wxid_a", "wxid_b"
    _make_db(tmp_path,
             [(1, me, 0), (2, a, 1), (3, b, 1)],
             {a: [(10, 1, 1, 100, 0, "m"), (11, 1, 2, 101, 0, "r")],   # senders {me,a} in conv a
              b: [(12, 1, 1, 102, 0, "m2")]})                          # sender {me} in conv b
    msgs = list(iter_messages(tmp_path))
    assert detect_owner(msgs) == me
    assert detect_owner(msgs, env="override_id") == "override_id"
