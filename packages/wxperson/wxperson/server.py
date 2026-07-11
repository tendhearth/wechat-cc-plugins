"""MCP stdio server for wxperson (same framing as wxgraph/wxfacts/wxsearch)."""
import json
import os
import sys

TOOLS = [
    {"name": "person_brief",
     "description": "一次组装某人的统一简报:关系画像 + 结构化事实 + 未了义务 + 近期消息(按人名解析,同名会给候选)。想整体了解一个人时先用它,再叠上你自己的看法。",
     "inputSchema": {"type": "object",
                     "properties": {"name": {"type": "string"},
                                    "recent_n": {"type": "integer"}},
                     "required": ["name"]}},
]


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _content(mid, obj):
    return _ok(mid, {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}]})


def _call_tool(mid, name, args, deps):
    if name == "person_brief":
        n = args.get("name")
        if not n:
            return _err(mid, -32602, "person_brief requires name")
        return _content(mid, deps["person_brief"](n, args.get("recent_n", 12)))
    return _err(mid, -32601, "unknown tool: %s" % name)


def dispatch(req, deps):
    mid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        pv = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return _ok(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "wxperson", "version": "0.1.0"}})
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
    from . import brief as B
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    deps = {
        "person_brief": lambda name, n: B.person_brief(state_dir, name, n),
    }
    sys.stderr.write("[wxperson] ready\n")
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
