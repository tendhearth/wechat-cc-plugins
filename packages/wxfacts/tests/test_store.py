from wxfacts.store import FactStore


def _f(contact="a", kind="obligation", predicate="owes_me", value="500元", **kw):
    d = {"contact": contact, "kind": kind, "predicate": predicate, "value": value}
    d.update(kw); return d


def test_insert_then_merge_dedup(tmp_path):
    s = FactStore(tmp_path)
    assert s.upsert_fact(_f(confidence="low", source_msg_keys=["k1"]), now=10) == "inserted"
    # same (contact,predicate,value) -> merge: union keys, keep higher confidence, add time_ref
    assert s.upsert_fact(_f(confidence="high", source_msg_keys=["k2"], time_ref="2026-08"), now=20) == "merged"
    rows = s.facts_for("a")
    assert len(rows) == 1
    r = rows[0]
    assert r["confidence"] == "high"                      # low < high
    assert sorted(r["source_msg_keys"]) == ["k1", "k2"]   # union
    assert r["time_ref"] == "2026-08"
    assert r["updated_at"] == 20 and r["created_at"] == 10
    s.close()


def test_merge_does_not_overwrite_status(tmp_path):
    s = FactStore(tmp_path)
    s.upsert_fact(_f(), now=1)
    rid = s.facts_for("a")[0]["id"]
    assert s.set_status(rid, "resolved", now=2) is True
    s.upsert_fact(_f(confidence="high"), now=3)           # merge must NOT revive status
    assert s.facts_for("a", status="active") == []
    assert s.facts_for("a", status="resolved")[0]["confidence"] == "high"
    s.close()


def test_watermark_monotonic(tmp_path):
    s = FactStore(tmp_path)
    assert s.get_watermark("a") == 0
    s.advance_watermark("a", 100, now=1)
    s.advance_watermark("a", 50, now=2)                   # lower -> ignored
    assert s.get_watermark("a") == 100
    assert s.all_watermarks() == {"a": 100}
    s.close()


def test_find_by_kind_and_substring(tmp_path):
    s = FactStore(tmp_path)
    s.upsert_fact(_f(contact="a", predicate="owes_me", value="500元"), now=1)
    s.upsert_fact(_f(contact="b", kind="attribute", predicate="works_at", value="阿里"), now=1)
    assert [r["contact"] for r in s.find("obligation", None, None, "active", 50)] == ["a"]
    assert [r["contact"] for r in s.find(None, None, "阿里", "active", 50)] == ["b"]     # value substring
    assert s.counts_by_kind() == {"obligation": 1, "attribute": 1}
    s.close()
