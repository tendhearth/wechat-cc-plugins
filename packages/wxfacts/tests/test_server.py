from wxfacts.server import dispatch


def _deps(**over):
    d = {"extraction_batch": lambda contact, limit: {"contact": contact or "big", "messages": []},
         "record_facts": lambda batch_id, facts: {"recorded": len(facts), "merged": 0, "advanced_to": 9},
         "contact_facts": lambda name: {"resolved": True, "contact": name, "by_kind": {}},
         "find_facts": lambda kind, predicate, query, status, limit: {"results": [{"value": "500元"}]},
         "set_fact_status": lambda fid, status: {"ok": True},
         "extraction_status": lambda: {"contacts": 2, "caught_up": 1}}
    d.update(over); return d


def _call(name, args, deps):
    return dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, deps)


def test_initialize_name():
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _deps())
    assert r["result"]["serverInfo"]["name"] == "wxfacts"


def test_notification_returns_none():
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, _deps()) is None


def test_tools_list_has_all():
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _deps())
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"extraction_batch", "record_facts", "contact_facts", "find_facts",
            "set_fact_status", "extraction_status"} <= names


def test_find_facts_tool_routes():
    r = _call("find_facts", {"kind": "obligation"}, _deps())
    assert "500元" in r["result"]["content"][0]["text"]


def test_record_facts_requires_batch_id():
    r = _call("record_facts", {"facts": []}, _deps())
    assert r["error"]["code"] == -32602


def test_contact_facts_requires_name():
    r = _call("contact_facts", {}, _deps())
    assert r["error"]["code"] == -32602


def test_set_fact_status_requires_id_and_status():
    r = _call("set_fact_status", {"id": 5}, _deps())
    assert r["error"]["code"] == -32602


def test_unknown_tool():
    r = _call("nope", {}, _deps())
    assert r["error"]["code"] == -32601
