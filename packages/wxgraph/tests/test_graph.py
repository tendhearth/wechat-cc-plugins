import hashlib, sqlite3
from pathlib import Path
from wxgraph.graph import (build, load_display_map, resolve_name, contact_profile,
                           top_contacts, relationship_subgraph, connectors, status)
from wxgraph.store import GraphStore

DAY = 86400

def _tbl(u): return "Msg_" + hashlib.md5(u.encode()).hexdigest()

def _seed(tmp_path):
    dec = Path(tmp_path) / "out" / "decrypted"; dec.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dec / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id(rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id VALUES(?,?,?)",
                    [(1, "wxid_me", 0), (2, "wxid_a", 1), (3, "wxid_b", 1), (4, "g@chatroom", 1)])
    for conv, rows in {
        "wxid_a": [(10, 1, 1, 90 * DAY, 0, "hi"), (11, 1, 2, 90 * DAY, 0, "yo"), (12, 34, 2, 91 * DAY, 0, "v")],
        "wxid_b": [(13, 1, 1, 50 * DAY, 0, "hey")],
        "g@chatroom": [(20, 1, 1, 92 * DAY, 0, "me in grp"),
                       (21, 49, 3, 92 * DAY, 0, "<msg><appmsg><refermsg><chatusr>wxid_a</chatusr></refermsg></appmsg></msg>")],
    }.items():
        con.execute('CREATE TABLE "%s"(local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, '
                    'create_time INTEGER, server_id INTEGER, message_content)' % _tbl(conv))
        con.executemany('INSERT INTO "%s" VALUES(?,?,?,?,?,?)' % _tbl(conv), rows)
    con.commit(); con.close()
    cc = sqlite3.connect(str(dec / "contact.sqlite"))
    cc.execute("CREATE TABLE contact(username TEXT, remark TEXT, nick_name TEXT, alias TEXT)")
    cc.executemany("INSERT INTO contact VALUES(?,?,?,?)",
                   [("wxid_a", "阿友", "Ah", ""), ("wxid_b", "", "Bob", "")])
    cc.commit(); cc.close()

def test_load_display_map(tmp_path):
    _seed(tmp_path)
    m = load_display_map(tmp_path)
    assert m["wxid_a"] == "阿友" and m["wxid_b"] == "Bob"

def test_build_end_to_end(tmp_path):
    _seed(tmp_path)
    res = build(tmp_path, now=92 * DAY)
    assert res["owner"] == "wxid_me"
    assert res["contacts"] == 2
    s = GraphStore(tmp_path)
    assert contact_profile(s, "阿友")["username"] == "wxid_a"                 # fuzzy by display
    # wxid_b spoke to wxid_a via quote in group -> mention edge b->a
    assert relationship_subgraph(s, None, 30)["edges"]
    conn = connectors(s, "阿友", "Bob")
    assert any(e["b"] == "wxid_a" or e["a"] == "wxid_a" for e in conn["mention_edges"])
    s.close()

def test_top_contacts_neglected_ordering(tmp_path):
    _seed(tmp_path)
    build(tmp_path, now=92 * DAY)
    s = GraphStore(tmp_path)
    # wxid_b last spoke day 50 (older) vs wxid_a day 91 -> b more "neglected"
    neg = top_contacts(s, "neglected", 10, "person")
    assert neg[0]["username"] == "wxid_b"
    closest = top_contacts(s, "closeness", 10, "person")
    assert closest[0]["username"] == "wxid_a"
    s.close()

def test_resolve_name_ambiguous_returns_candidates(tmp_path):
    _seed(tmp_path)
    build(tmp_path, now=92 * DAY)
    s = GraphStore(tmp_path)
    un, cands = resolve_name(s, "zzz-nomatch")
    assert un is None and cands == []
    s.close()

def test_resolve_name_multi_candidate_lists_all(tmp_path):
    _seed(tmp_path)
    build(tmp_path, now=92 * DAY)
    s = GraphStore(tmp_path)
    un, cands = resolve_name(s, "wxid_")            # substring matches both wxid_a and wxid_b
    assert un is None and {c["username"] for c in cands} == {"wxid_a", "wxid_b"}
    s.close()

def test_build_drops_edges_on_ambiguous_displayname(tmp_path):
    # two contacts share nickname "同名"; a group quote by displayname must NOT be
    # misattributed — it resolves to nobody, producing no mention edge.
    dec = Path(tmp_path) / "out" / "decrypted"; dec.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dec / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id(rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.executemany("INSERT INTO Name2Id VALUES(?,?,?)",
                    [(1, "wxid_me", 0), (2, "wxid_x", 1), (3, "wxid_y", 1), (4, "g@chatroom", 1)])
    for conv, rows in {
        "wxid_x": [(1, 1, 1, 10 * DAY, 0, "a")],
        "wxid_y": [(2, 1, 1, 10 * DAY, 0, "b")],
        "g@chatroom": [(3, 49, 2, 11 * DAY, 0,
                        "<msg><appmsg><refermsg><displayname>同名</displayname></refermsg></appmsg></msg>")],
    }.items():
        con.execute('CREATE TABLE "%s"(local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, '
                    'create_time INTEGER, server_id INTEGER, message_content)' % _tbl(conv))
        con.executemany('INSERT INTO "%s" VALUES(?,?,?,?,?,?)' % _tbl(conv), rows)
    con.commit(); con.close()
    cc = sqlite3.connect(str(dec / "contact.sqlite"))
    cc.execute("CREATE TABLE contact(username TEXT, remark TEXT, nick_name TEXT, alias TEXT)")
    cc.executemany("INSERT INTO contact VALUES(?,?,?,?)",
                   [("wxid_x", "同名", "", ""), ("wxid_y", "同名", "", "")])
    cc.commit(); cc.close()
    res = build(tmp_path, now=12 * DAY)
    assert res["edges"] == 0

def test_status_reports_stale(tmp_path):
    _seed(tmp_path)
    build(tmp_path, now=92 * DAY)
    s = GraphStore(tmp_path)
    st = status(s, tmp_path)
    assert st["contacts"] == 2 and st["owner"] == "wxid_me"
    assert st["stale"] is False       # nothing changed since build
    s.close()
