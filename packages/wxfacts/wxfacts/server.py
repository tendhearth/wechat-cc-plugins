"""MCP stdio server for wxfacts (same framing as wxmedia/wxsearch/wxgraph)."""
import json
import os
import sys

TOOLS = [
    {"name": "extraction_batch",
     "description": "取下一批未抽取的 1:1 消息(不给 contact 则选积压最多的联系人)。你(agent)据此抽取实体/关系/义务,再调 record_facts 回写。",
     "inputSchema": {"type": "object", "properties": {
         "contact": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "record_facts",
     "description": "回写你抽取到的结构化断言并推进该批水位(facts 可空,只推进)。fact: {kind,predicate,value,related_contact?,time_ref?,confidence?,source_msg_keys?}。confidence=low|med|high;kind 建议 entity|relation|obligation|attribute|event。",
     "inputSchema": {"type": "object", "properties": {
         "batch_id": {"type": "string"}, "facts": {"type": "array"}}, "required": ["batch_id"]}},
    {"name": "contact_facts", "description": "某联系人已抽取的事实(按 kind 分组)。",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "find_facts", "description": "跨联系人查事实(query 子串匹配 predicate/value)。如 kind=obligation 查未了义务。",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string"}, "predicate": {"type": "string"}, "query": {"type": "string"},
         "status": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "set_fact_status", "description": "改事实状态:resolved(如义务已还)/superseded(过时纠正)。",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["id", "status"]}},
    {"name": "extraction_status", "description": "抽取进度:每联系人已抽取到/剩余、按 kind 的事实总数。",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _content(mid, obj):
    return _ok(mid, {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False, indent=2)}]})


def _call_tool(mid, name, args, deps):
    if name == "extraction_batch":
        return _content(mid, deps["extraction_batch"](args.get("contact"), args.get("limit", 40)))
    if name == "record_facts":
        bid = args.get("batch_id")
        if not bid:
            return _err(mid, -32602, "record_facts requires batch_id")
        return _content(mid, deps["record_facts"](bid, args.get("facts") or []))
    if name == "contact_facts":
        n = args.get("name")
        if not n:
            return _err(mid, -32602, "contact_facts requires name")
        return _content(mid, deps["contact_facts"](n))
    if name == "find_facts":
        return _content(mid, deps["find_facts"](args.get("kind"), args.get("predicate"),
                                                args.get("query"), args.get("status", "active"),
                                                args.get("limit", 50)))
    if name == "set_fact_status":
        fid, status = args.get("id"), args.get("status")
        if fid is None or not status:
            return _err(mid, -32602, "set_fact_status requires id and status")
        return _content(mid, deps["set_fact_status"](fid, status))
    if name == "extraction_status":
        return _content(mid, deps["extraction_status"]())
    return _err(mid, -32601, "unknown tool: %s" % name)


def dispatch(req, deps):
    mid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        pv = (req.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return _ok(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                         "serverInfo": {"name": "wxfacts", "version": "0.1.0"}})
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
    from ._deps import ensure_wxgraph
    ensure_wxgraph()
    from .store import FactStore
    from . import facts as F
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))

    def with_store(fn):
        s = FactStore(state_dir)
        try:
            return fn(s)
        finally:
            s.close()

    deps = {
        "extraction_batch": lambda contact, limit: with_store(
            lambda s: F.next_batch(s, state_dir, contact, limit)),
        "record_facts": lambda bid, fs: with_store(
            lambda s: F.record(s, bid, fs, int(time.time()))),
        "contact_facts": lambda name: with_store(
            lambda s: F.contact_facts(s, state_dir, name)),
        "find_facts": lambda kind, predicate, query, status, limit: with_store(
            lambda s: F.find_facts(s, kind, predicate, query, status, limit)),
        "set_fact_status": lambda fid, status: with_store(
            lambda s: F.set_fact_status(s, fid, status, int(time.time()))),
        "extraction_status": lambda: with_store(
            lambda s: F.extraction_status(s, state_dir)),
    }
    sys.stderr.write("[wxfacts] ready\n")
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
