"""MCP stdio server for wxgraph (same framing as wxmedia/wxsearch)."""
import json
import os
import sys

TOOLS = [
    {"name": "contact_profile", "description": "某个联系人的关系画像(分项分数+互动明细+提及伙伴)",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "top_contacts", "description": "按维度排序联系人:closeness/volume/recency/reciprocity/neglected",
     "inputSchema": {"type": "object", "properties": {
         "by": {"type": "string"}, "limit": {"type": "integer"}, "kind": {"type": "string"}}}},
    {"name": "relationship_subgraph", "description": "以我为中心的关系子图(节点+边),给 agent 推理/渲染",
     "inputSchema": {"type": "object", "properties": {
         "center": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "connectors", "description": "两个联系人在我世界里的连接(共群+互相提及)",
     "inputSchema": {"type": "object", "properties": {
         "name_a": {"type": "string"}, "name_b": {"type": "string"}}, "required": ["name_a", "name_b"]}},
    {"name": "rebuild", "description": "从解密库全量重算关系图", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "graph_status", "description": "联系人数/owner/是否需重建", "inputSchema": {"type": "object", "properties": {}}},
]


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _content(mid, obj):
    return _ok(mid, {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}]})


def _call_tool(mid, name, args, deps):
    from . import graph as G
    if name == "rebuild":
        return _content(mid, deps["do_build"]())
    if name == "graph_status":
        s = deps["open_store"]()
        try:
            return _content(mid, G.status(s, deps["state_dir"]))
        finally:
            s.close()
    if name == "contact_profile":
        n = args.get("name")
        if not n:
            return _err(mid, -32602, "contact_profile requires name")
        s = deps["open_store"]()
        try:
            return _content(mid, G.contact_profile(s, n))
        finally:
            s.close()
    if name == "top_contacts":
        s = deps["open_store"]()
        try:
            return _content(mid, G.top_contacts(s, args.get("by", "closeness"),
                                                args.get("limit", 20), args.get("kind", "person")))
        finally:
            s.close()
    if name == "relationship_subgraph":
        s = deps["open_store"]()
        try:
            return _content(mid, G.relationship_subgraph(s, args.get("center"), args.get("limit", 30)))
        finally:
            s.close()
    if name == "connectors":
        a, b = args.get("name_a"), args.get("name_b")
        if not a or not b:
            return _err(mid, -32602, "connectors requires name_a and name_b")
        s = deps["open_store"]()
        try:
            return _content(mid, G.connectors(s, a, b))
        finally:
            s.close()
    return _err(mid, -32601, "unknown tool: %s" % name)


def dispatch(req, deps):
    mid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        pv = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return _ok(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "wxgraph", "version": "0.1.0"}})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        p = req.get("params") or {}
        return _call_tool(mid, p.get("name"), p.get("arguments") or {}, deps)
    if mid is not None:
        return _err(mid, -32601, "method not found: %s" % method)
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    import time
    from . import graph as G
    from .store import GraphStore
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    deps = {
        "state_dir": state_dir,
        "do_build": lambda: G.build(state_dir, int(time.time())),
        "open_store": lambda: GraphStore(state_dir),
    }
    sys.stderr.write("[wxgraph] ready\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = dispatch(req, deps)
        except Exception as e:
            resp = _err(None, -32603, "internal: %s" % e)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
