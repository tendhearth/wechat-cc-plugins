from wxmedia.server import dispatch
from wxmedia.store import DerivedStore

class FakeMM:
    def __init__(self): self._preset = "light"
    def status(self): return {"preset": self._preset, "platform": "win-x64", "capabilities": {}}
    def set_choice(self, cap, tier): self._set = (cap, tier)

def _deps(tmp_path, mm=None, transcribe=None):
    return {"state_dir": tmp_path, "manager": mm or FakeMM(),
            "transcribe": transcribe or (lambda: {"processed": 3, "skipped": 0, "failed": 0})}

def _call(name, args, deps):
    return dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": name, "arguments": args}}, deps)

def test_get_media_text(tmp_path):
    DerivedStore(tmp_path).put("100", "voice", "你好", "m", 1)
    r = _call("get_media_text", {"svr_id": "100"}, _deps(tmp_path))
    assert "你好" in r["result"]["content"][0]["text"]

def test_voice_backfill_reports_counts(tmp_path):
    r = _call("voice_backfill", {}, _deps(tmp_path))
    assert "3" in r["result"]["content"][0]["text"]

def test_models_status(tmp_path):
    r = _call("models_status", {}, _deps(tmp_path))
    assert "light" in r["result"]["content"][0]["text"]

def test_set_model(tmp_path):
    mm = FakeMM()
    _call("set_model", {"capability": "asr", "tier": "high"}, _deps(tmp_path, mm=mm))
    assert mm._set == ("asr", "high")

def test_unknown_tool_is_error(tmp_path):
    r = _call("nope", {}, _deps(tmp_path))
    assert r["error"]["code"] == -32601

def test_initialize_returns_server_info(tmp_path):
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18"}}, _deps(tmp_path))
    assert r["result"]["serverInfo"]["name"] == "wxmedia"
    assert "protocolVersion" in r["result"]

def test_tools_list(tmp_path):
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _deps(tmp_path))
    tools = r["result"]["tools"]
    assert len(tools) == 4
    names = {t["name"] for t in tools}
    assert names == {"voice_backfill", "get_media_text", "models_status", "set_model"}

def test_notification_returns_none(tmp_path):
    r = dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}, _deps(tmp_path))
    assert r is None

def test_ping(tmp_path):
    r = dispatch({"jsonrpc": "2.0", "id": 1, "method": "ping"}, _deps(tmp_path))
    assert r["result"] == {}

def test_set_model_missing_args_is_error(tmp_path):
    r = _call("set_model", {}, _deps(tmp_path))
    assert r["error"]["code"] == -32602
