"""Minimal MCP stdio server for wxmedia (same framing as wxvault_mcp.py)."""
import json
import os
import sys

from .store import DerivedStore


def _ok(mid, text):
    return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}


def _err(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def dispatch(req: dict, deps: dict) -> dict:
    mid = req.get("id")
    if req.get("method") != "tools/call":
        return _err(mid, -32601, "only tools/call")
    p = req.get("params") or {}
    name = p.get("name")
    args = p.get("arguments") or {}
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
        deps["manager"].set_choice(args["capability"], args["tier"])
        return _ok(mid, "ok")
    return _err(mid, -32601, "unknown tool: %s" % name)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    from model_manager import ModelManager
    from .pipeline import transcribe_all
    from .asr import SenseVoiceRunner
    manager = ModelManager(state_dir)
    deps = {
        "state_dir": state_dir,
        "manager": manager,
        "transcribe": lambda: transcribe_all(state_dir, SenseVoiceRunner(manager)),
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
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
