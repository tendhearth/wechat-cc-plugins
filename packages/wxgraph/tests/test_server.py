import json
from wxgraph.server import dispatch

class FakeStore:
    def __init__(self): self._closed = False
    def close(self): self._closed = True

def _deps(**over):
    d = {"state_dir": "/tmp/x",
         "do_build": lambda: {"owner": "me", "contacts": 3, "edges": 1, "built_at": 5},
         "open_store": lambda: FakeStore()}
    d.update(over); return d

def _call(name, args, deps):
    return dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, deps)

def test_initialize_name():
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _deps())
    assert r["result"]["serverInfo"]["name"] == "wxgraph"

def test_notification_returns_none():
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, _deps()) is None

def test_tools_list_has_all():
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _deps())
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"contact_profile", "top_contacts", "relationship_subgraph",
            "connectors", "rebuild", "graph_status"} <= names

def test_rebuild_tool_reports_counts():
    r = _call("rebuild", {}, _deps())
    assert "3" in r["result"]["content"][0]["text"]

def test_contact_profile_requires_name():
    r = _call("contact_profile", {}, _deps())
    assert r["error"]["code"] == -32602

def test_unknown_tool():
    r = _call("nope", {}, _deps())
    assert r["error"]["code"] == -32601
