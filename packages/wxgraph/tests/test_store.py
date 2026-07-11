import json
from wxgraph.store import GraphStore

def _p(u, closeness=0.5, total=3):
    return {"username": u, "total": total, "sent": 1, "recv": 2, "first_ts": 1, "last_ts": 2,
            "known_days": 1, "active_days": 1, "initiations": 1, "transfer_in": 0, "transfer_out": 0,
            "shared_groups": 0, "types": {"text": total}, "s_volume": 0.1, "s_recency": 0.2,
            "s_reciprocity": 0.3, "s_intimacy": 0.4, "closeness": closeness}

def test_rebuild_writes_contacts_edges_meta(tmp_path):
    s = GraphStore(tmp_path)
    profs = [_p("a", 0.9), _p("b", 0.4)]
    s.rebuild(profs, {"a": "Alice", "b": "Bob"}, "me",
              [("a", "b", 3)], now=1000, weights={"recency": 0.35}, source_max_mtime=55.0)
    assert s.count() == 2
    a = s.get_contact("a")
    assert a["display"] == "Alice" and a["closeness"] == 0.9 and a["types"] == {"text": 3}
    me_edges = {e["b"]: e["weight"] for e in s.edges_for("me", "me")}
    assert me_edges == {"a": 0.9, "b": 0.4}
    ment = s.edges_for("a", "mention")
    assert ment == [{"a": "a", "b": "b", "kind": "mention", "weight": 3.0}]
    assert s.get_meta("owner") == "me"
    assert json.loads(s.get_meta("weights")) == {"recency": 0.35}
    assert s.get_meta("source_max_mtime") == "55.0"
    s.close()

def test_rebuild_is_idempotent(tmp_path):
    s = GraphStore(tmp_path)
    s.rebuild([_p("a")], {"a": "A"}, "me", [], 1, {}, 1.0)
    s.rebuild([_p("a")], {"a": "A"}, "me", [], 2, {}, 2.0)   # second rebuild clears first
    assert s.count() == 1
    assert s.get_meta("built_at") == "2"
    s.close()
