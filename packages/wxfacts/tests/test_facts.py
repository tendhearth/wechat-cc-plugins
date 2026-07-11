import hashlib
import sqlite3
from pathlib import Path

from wxfacts.store import FactStore
from wxfacts import facts as F


def _tbl(u):
    return "Msg_" + hashlib.md5(u.encode()).hexdigest()


def _seed(tmp_path):
    dec = Path(tmp_path) / "out" / "decrypted"; dec.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dec / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id(rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id VALUES(?,?,?)",
                    [(1, "wxid_me", 0), (2, "wxid_a", 1), (3, "wxid_b", 1)])
    for conv, rows in {
        "wxid_a": [(10, 1, 1, 100, 0, "a-one"), (11, 1, 2, 110, 0, "a-two"), (12, 1, 2, 120, 0, "a-three")],
        "wxid_b": [(20, 1, 1, 200, 0, "b-one")],
    }.items():
        con.execute('CREATE TABLE "%s"(local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, '
                    'create_time INTEGER, server_id INTEGER, message_content)' % _tbl(conv))
        con.executemany('INSERT INTO "%s" VALUES(?,?,?,?,?,?)' % _tbl(conv), rows)
    con.commit(); con.close()


def test_batch_picks_largest_backlog_and_windows(tmp_path):
    _seed(tmp_path)
    s = FactStore(tmp_path)
    b = F.next_batch(s, tmp_path, contact=None, limit=2)     # wxid_a has 3 (largest), limit 2
    assert b["contact"] == "wxid_a"
    assert [m["msg_key"] for m in b["messages"]] == ["%s:10" % _tbl("wxid_a"), "%s:11" % _tbl("wxid_a")]
    assert b["covers_until_ts"] == 110
    s.close()


def test_record_advances_watermark_and_dedups(tmp_path):
    _seed(tmp_path)
    s = FactStore(tmp_path)
    b = F.next_batch(s, tmp_path, "wxid_a", 40)
    res = F.record(s, b["batch_id"], [
        {"kind": "attribute", "predicate": "likes", "value": "茶", "source_msg_keys": ["%s:10" % _tbl("wxid_a")]},
    ], now=500)
    assert res == {"recorded": 1, "merged": 0, "advanced_to": 120}     # covers all 3 (max ts 120)
    # next batch for a is now empty; global backlog shifts to b
    assert F.next_batch(s, tmp_path, "wxid_a", 40) == {"done": True}
    assert F.next_batch(s, tmp_path, None, 40)["contact"] == "wxid_b"
    # fact recorded, defaulted contact = wxid_a
    assert F.contact_facts(s, tmp_path, "wxid_a")["by_kind"]["attribute"][0]["value"] == "茶"
    s.close()


def test_record_empty_still_advances(tmp_path):
    _seed(tmp_path)
    s = FactStore(tmp_path)
    b = F.next_batch(s, tmp_path, "wxid_b", 40)
    assert F.record(s, b["batch_id"], [], now=1)["advanced_to"] == 200
    assert F.next_batch(s, tmp_path, "wxid_b", 40) == {"done": True}   # empty window not re-served
    s.close()


def test_find_and_status(tmp_path):
    _seed(tmp_path)
    s = FactStore(tmp_path)
    b = F.next_batch(s, tmp_path, "wxid_a", 40)
    F.record(s, b["batch_id"], [{"kind": "obligation", "predicate": "owes_me", "value": "500元"}], now=1)
    hit = F.find_facts(s, "obligation", None, None, "active", 50)
    assert hit["results"][0]["value"] == "500元"
    fid = hit["results"][0]["id"]
    assert F.set_fact_status(s, fid, "resolved", now=2)["ok"] is True
    assert F.find_facts(s, "obligation", None, None, "active", 50)["results"] == []
    st = F.extraction_status(s, tmp_path)
    assert st["facts_by_kind"] == {"obligation": 1}
    s.close()


def test_same_ts_at_limit_boundary_not_dropped(tmp_path):
    # two messages share ts at the limit cut -> the batch must extend to include the
    # same-ts message, else advancing the watermark to covers_until_ts drops it forever.
    dec = Path(tmp_path) / "out" / "decrypted"; dec.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dec / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id(rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id VALUES(?,?,?)", [(1, "wxid_me", 0), (2, "wxid_a", 1)])
    con.execute('CREATE TABLE "%s"(local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, '
                'create_time INTEGER, server_id INTEGER, message_content)' % _tbl("wxid_a"))
    con.executemany('INSERT INTO "%s" VALUES(?,?,?,?,?,?)' % _tbl("wxid_a"),
                    [(10, 1, 1, 100, 0, "m1"), (11, 1, 2, 110, 0, "m2"), (12, 1, 2, 110, 0, "m3")])
    con.commit(); con.close()
    s = FactStore(tmp_path)
    b = F.next_batch(s, tmp_path, "wxid_a", 2)          # limit 2 lands mid-110-run
    keys = [m["msg_key"] for m in b["messages"]]
    assert "%s:12" % _tbl("wxid_a") in keys              # same-ts msg included, not dropped
    assert b["covers_until_ts"] == 110
    F.record(s, b["batch_id"], [], now=1)
    assert F.next_batch(s, tmp_path, "wxid_a", 2) == {"done": True}   # nothing skipped
    s.close()
