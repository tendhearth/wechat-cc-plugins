"""MCP stdio server for wxsearch (same framing as wxmedia/wxvault)."""
import json
import os
import sys

TOOLS = [
    {"name": "search", "description": "语义+关键词混合检索本地微信历史",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "limit": {"type": "integer"},
                                    "conversation": {"type": "string"}},
                     "required": ["query"]}},
    {"name": "index_update", "description": "增量索引新消息",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "reindex", "description": "清空重建索引（换 embedding 档后用）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "index_status", "description": "索引条数/模型/是否需重建",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "models_status", "description": "当前模型档与下载状态",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "set_model", "description": "切换 embedding 档（light/high）",
     "inputSchema": {"type": "object",
                     "properties": {"capability": {"type": "string"}, "tier": {"type": "string"}},
                     "required": ["capability", "tier"]}},
]


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _content(mid, obj):
    return _ok(mid, {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}]})


def dispatch(req, deps):
    mid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        pv = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return _ok(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "wxsearch", "version": "0.1.0"}})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        p = req.get("params") or {}
        name = p.get("name")
        args = p.get("arguments") or {}
        if name == "search":
            q = args.get("query")
            if not q:
                return _err(mid, -32602, "search requires query")
            return _content(mid, deps["do_search"](q, args.get("limit", 10), args.get("conversation")))
        if name == "index_update":
            return _content(mid, deps["do_index_update"]())
        if name == "reindex":
            return _content(mid, deps["do_reindex"]())
        if name == "index_status":
            from .index import IndexStore
            s = IndexStore(deps["state_dir"])
            st = {"docs": s.count(), "embed_model": s.get_meta("embed_model")}
            s.close()
            return _content(mid, st)
        if name == "models_status":
            return _content(mid, deps["manager"].status())
        if name == "set_model":
            cap, tier = args.get("capability"), args.get("tier")
            if not cap or not tier:
                return _err(mid, -32602, "set_model requires capability and tier")
            deps["manager"].set_choice(cap, tier)
            return _ok(mid, {"content": [{"type": "text", "text": "ok"}]})
        return _err(mid, -32601, "unknown tool: %s" % name)
    if mid is not None:
        return _err(mid, -32601, "method not found: %s" % method)
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    from ._deps import ensure_model_manager
    ensure_model_manager()
    from model_manager import ModelManager
    from .embed import OnnxEmbedRunner
    from . import search as S
    manager = ModelManager(state_dir)
    deps = {
        "state_dir": state_dir,
        "manager": manager,
        "do_search": lambda q, limit, conv: S.search(state_dir, q, OnnxEmbedRunner(manager),
                                                      limit=limit, conversation=conv),
        "do_index_update": lambda: S.index_update(state_dir, OnnxEmbedRunner(manager)),
        "do_reindex": lambda: S.reindex(state_dir, OnnxEmbedRunner(manager)),
    }
    sys.stderr.write("[wxsearch] ready\n")
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
