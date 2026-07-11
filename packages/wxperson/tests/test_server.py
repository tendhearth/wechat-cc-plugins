import json

from wxperson.server import _call_tool, dispatch


def _stub_deps(seen):
    def person_brief(name, n):
        seen["name"] = name
        seen["n"] = n
        return {"name": name, "resolved": True}
    return {"person_brief": person_brief}


def test_tools_list_exposes_person_brief():
    resp = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["person_brief"]


def test_call_returns_assembled_json_with_default_n():
    seen = {}
    resp = _call_tool(2, "person_brief", {"name": "张三"}, _stub_deps(seen))
    obj = json.loads(resp["result"]["content"][0]["text"])
    assert obj["resolved"] is True
    assert seen == {"name": "张三", "n": 12}


def test_call_passes_recent_n_through():
    seen = {}
    _call_tool(3, "person_brief", {"name": "张三", "recent_n": 5}, _stub_deps(seen))
    assert seen["n"] == 5


def test_call_without_name_is_invalid_params():
    resp = _call_tool(4, "person_brief", {}, _stub_deps({}))
    assert resp["error"]["code"] == -32602
