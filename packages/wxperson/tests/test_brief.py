import os
import sqlite3

from wxperson._deps import ensure_siblings

ensure_siblings()

from wxgraph.store import GraphStore  # noqa: E402
from wxfacts.store import FactStore  # noqa: E402
from wxperson.brief import person_brief  # noqa: E402

NOW = 1_700_000_000


def _seed(state_dir):
    # wxgraph: two contacts resolvable by display name
    gs = GraphStore(state_dir)
    for un, disp in (("wxid_zhang", "张三"), ("wxid_li", "李四")):
        gs.con.execute(
            "INSERT INTO contacts(username,display,is_group,types) VALUES(?,?,?,?)",
            (un, disp, 0, "{}"))
    gs.con.commit()
    gs.close()

    # wxfacts: one obligation for zhang, one for li
    fs = FactStore(state_dir)
    fs.upsert_fact({"contact": "wxid_zhang", "kind": "obligation",
                    "predicate": "我答应", "value": "帮他改简历"}, NOW)
    fs.upsert_fact({"contact": "wxid_li", "kind": "obligation",
                    "predicate": "欠我", "value": "200块"}, NOW)
    fs.close()

    # wxsearch index: 15 msgs in zhang's conversation + 3 in li's
    con = sqlite3.connect(os.path.join(str(state_dir), "index.sqlite"))
    con.execute("CREATE TABLE docs (rowid INTEGER PRIMARY KEY, msg_key TEXT UNIQUE, "
                "conversation TEXT, sender TEXT, time INTEGER, type TEXT, text TEXT, "
                "vector BLOB, model_id TEXT)")
    for i in range(15):
        con.execute("INSERT INTO docs(msg_key,conversation,sender,time,text) VALUES(?,?,?,?,?)",
                    ("z%d" % i, "wxid_zhang", "wxid_zhang" if i % 2 else "me", 1000 + i, "msg %d" % i))
    for i in range(3):
        con.execute("INSERT INTO docs(msg_key,conversation,sender,time,text) VALUES(?,?,?,?,?)",
                    ("l%d" % i, "wxid_li", "me", 500 + i, "other %d" % i))
    con.commit()
    con.close()


def test_resolved_brief_assembles_all_sources(tmp_path):
    _seed(tmp_path)
    b = person_brief(str(tmp_path), "张三")
    assert b["resolved"] is True
    assert b["wxid"] == "wxid_zhang"
    assert b["relationship"] and b["relationship"].get("resolved") is True
    assert b["facts"] and b["facts"].get("resolved") is True


def test_recent_messages_newest_first_capped_and_scoped(tmp_path):
    _seed(tmp_path)
    msgs = person_brief(str(tmp_path), "张三", recent_n=12)["recent_messages"]
    assert len(msgs) == 12                                  # capped from 15
    times = [m["time"] for m in msgs]
    assert times == sorted(times, reverse=True)             # newest first
    assert all(m["text"].startswith("msg") for m in msgs)   # only zhang's conversation


def test_obligations_filtered_to_this_person(tmp_path):
    _seed(tmp_path)
    obs = person_brief(str(tmp_path), "张三")["obligations"]
    vals = {o["value"] for o in obs}
    assert "帮他改简历" in vals          # zhang's obligation kept
    assert "200块" not in vals           # li's obligation excluded


def test_unresolved_name_returns_candidates(tmp_path):
    _seed(tmp_path)
    b = person_brief(str(tmp_path), "查无此人")
    assert b["resolved"] is False
    assert "candidates" in b
    assert "wxid" not in b


def test_degrades_when_index_absent(tmp_path):
    _seed(tmp_path)
    os.remove(os.path.join(str(tmp_path), "index.sqlite"))
    b = person_brief(str(tmp_path), "张三")
    assert b["resolved"] is True                # still resolves
    assert b["relationship"] is not None        # relationship still there
    assert b["recent_messages"] == []           # missing source degrades, no crash
