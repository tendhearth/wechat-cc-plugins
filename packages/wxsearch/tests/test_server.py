import json
from wxsearch.server import dispatch
from wxsearch.index import IndexStore

class FakeMM:
    def status(self): return {"preset": "light", "platform": "mac-arm64", "capabilities": {}}
    def set_choice(self, cap, tier): self._set = (cap, tier)
    def resolve(self, cap):
        class S: id = "bge-small-zh-v1.5"
        return S()

def _deps(**over):
    d = {"state_dir": "/tmp/x", "manager": FakeMM(),
         "do_search": lambda q, limit, conv: {"vectors_stale": False,
             "results": [{"conversation": "c", "sender": "s", "time": 1, "type": "text",
                          "text": "响水石板大米", "score": 3}]},
         "do_index_update": lambda: {"indexed": 5, "skipped": 0},
         "do_reindex": lambda: {"indexed": 5, "skipped": 0}}
    d.update(over); return d

def _call(name, args, deps):
    return dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, deps)

def test_initialize():
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, _deps())
    assert r["result"]["serverInfo"]["name"] == "wxsearch"

def test_notification_returns_none():
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, _deps()) is None

def test_tools_list_has_all():
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _deps())
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"search", "index_update", "reindex", "index_status", "models_status", "set_model"} <= names

def test_search_tool():
    r = _call("search", {"query": "大米", "limit": 5}, _deps())
    assert "响水石板大米" in r["result"]["content"][0]["text"]

def test_index_update_tool():
    r = _call("index_update", {}, _deps())
    assert "5" in r["result"]["content"][0]["text"]

def test_set_model_missing_args_is_error():
    r = _call("set_model", {}, _deps())
    assert r["error"]["code"] == -32602

def test_unknown_tool():
    r = _call("nope", {}, _deps())
    assert r["error"]["code"] == -32601

def test_index_status_reports_stale(tmp_path):
    # index built under "old-model"; FakeMM.resolve returns a different current model
    # -> index_status must surface vectors_stale so a UI knows to reindex after set_model.
    s = IndexStore(str(tmp_path)); s.set_meta("embed_model", "old-model"); s.close()
    r = _call("index_status", {}, _deps(state_dir=str(tmp_path)))
    body = json.loads(r["result"]["content"][0]["text"])
    assert body["embed_model"] == "old-model"
    assert body["vectors_stale"] is True
