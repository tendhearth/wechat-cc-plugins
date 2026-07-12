"""Minimal MCP stdio server for wxmedia (same framing as wxvault_mcp.py)."""
import json
import os
import sys

from .store import DerivedStore


SERVER_NAME = "wxmedia"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "voice_backfill",
        "description": "把尚未转写的语音消息批量跑一遍 SILK→ASR，回填文本。",
        "inputSchema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "最多处理多少条，可空"},
        }},
    },
    {
        "name": "get_media_text",
        "description": "按消息 server_id 取已转写/派生的文本。",
        "inputSchema": {"type": "object", "properties": {
            "svr_id": {"type": "string", "description": "消息 server_id"},
        }, "required": ["svr_id"]},
    },
    {
        "name": "models_status",
        "description": "查看当前模型档位（轻量/高精度）与各平台可用性。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_model",
        "description": "设置某项能力（如 asr）使用的模型档位。",
        "inputSchema": {"type": "object", "properties": {
            "capability": {"type": "string", "description": "能力名，如 asr"},
            "tier": {"type": "string", "description": "档位，如 light/high"},
        }, "required": ["capability", "tier"]},
    },
]


def _ok(mid, text):
    return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}


def _ok_result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _call_tool(mid, name, args, deps):
    sd = deps["state_dir"]
    if name == "voice_backfill":
        res = deps["transcribe"]()
        return _ok(mid, json.dumps(res, ensure_ascii=False))
    if name == "get_media_text":
        store = DerivedStore(sd)
        row = store.get(str(args.get("svr_id", "")))
        store.close()
        return _ok(mid, json.dumps(row or {"note": "no text for this id"}, ensure_ascii=False))
    if name == "models_status":
        return _ok(mid, json.dumps(deps["manager"].status(), ensure_ascii=False))
    if name == "set_model":
        capability = args.get("capability")
        tier = args.get("tier")
        if not capability or not tier:
            return _err(mid, -32602, "set_model requires capability and tier")
        deps["manager"].set_choice(capability, tier)
        return _ok(mid, "ok")
    return _err(mid, -32601, "unknown tool: %s" % name)


def dispatch(req: dict, deps: dict):
    mid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        pv = (req.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return _ok_result(mid, {"protocolVersion": pv, "capabilities": {"tools": {}},
                                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None                      # notification: no response
    if method == "ping":
        return _ok_result(mid, {})
    if method == "tools/list":
        return _ok_result(mid, {"tools": TOOLS})
    if method == "tools/call":
        p = req.get("params") or {}
        name = p.get("name")
        args = p.get("arguments") or {}
        return _call_tool(mid, name, args, deps)
    if mid is not None:
        return _err(mid, -32601, "method not found: %s" % method)
    return None                          # unknown notification: no response


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    # HF mirror default (China-friendly); a HF_ENDPOINT set in the daemon env now
    # WINS (the manifest no longer hardcodes it) so users on a network that blocks
    # hf-mirror can override to https://huggingface.co.
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    from ._deps import ensure_model_manager
    ensure_model_manager()          # resolve the sibling model-manager package from the monorepo
    from model_manager import ModelManager
    from .pipeline import transcribe_all
    from .asr import FasterWhisperRunner
    manager = ModelManager(state_dir)
    deps = {
        "state_dir": state_dir,
        "manager": manager,
        "transcribe": lambda: transcribe_all(state_dir, FasterWhisperRunner(manager)),
    }
    sys.stderr.write("[wxmedia] ready\n")
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
