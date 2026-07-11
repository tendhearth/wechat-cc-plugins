"""Read-only readers over wxvault's decrypted contact.sqlite + message_*.sqlite."""
import glob
import hashlib
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

try:
    import zstandard as _zstd
except Exception:                       # optional; degrade to raw bytes
    _zstd = None

ZMAGIC = b"\x28\xb5\x2f\xfd"
_DCTX = _zstd.ZstdDecompressor() if _zstd else None

# local_type -> coarse tag (mirrors wxvault_mcp._decode_body)
_SIMPLE = {1: "text", 3: "image", 34: "voice", 43: "video", 44: "video", 47: "sticker",
           42: "card", 67: "card", 48: "location", 50: "call", 10000: "system", 10002: "system"}
# type=49 <type> subtype -> tag (mirrors wxvault_mcp._decode_app)
_APPSUB = {2: "miniprogram", 4: "link", 5: "link", 33: "link", 36: "link", 6: "file", 8: "sticker",
           19: "chatlog", 51: "channel", 63: "channel", 53: "solitaire", 62: "pat", 87: "notice",
           2000: "transfer", 2001: "redpacket"}


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def zstd_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
        if b[:4] == ZMAGIC and _DCTX is not None:
            try:
                b = _DCTX.decompress(b)
            except Exception:
                pass
        return b.decode("utf-8", "replace")
    return value


def _xml_int(content, tag):
    m = re.search(r"<%s>\s*(-?\d+)\s*</%s>" % (tag, tag), content or "")
    return int(m.group(1)) if m else 0


def classify_type(ltype, content) -> str:
    if ltype in _SIMPLE:
        return _SIMPLE[ltype]
    if ltype == 49:
        if content and "<refermsg>" in content:
            return "quote"
        sub = _xml_int(content, "type")
        if sub in _APPSUB:
            return _APPSUB[sub]
        return "app"
    return "other"


def iter_messages(state_dir):
    """Yield one record per Msg_* row across all decrypted message DBs."""
    pattern = os.path.join(str(state_dir), "out", "decrypted", "message_*.sqlite")
    for dbpath in sorted(glob.glob(pattern)):
        con = _ro(dbpath); con.row_factory = sqlite3.Row
        try:
            names = [x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            if "Name2Id" not in names:
                continue
            n2i = {r["rowid"]: r["user_name"]
                   for r in con.execute("SELECT rowid, user_name FROM Name2Id")}
            sessions = [r["user_name"] for r in con.execute(
                "SELECT user_name FROM Name2Id WHERE is_session=1")]
            table_conv = {"Msg_" + hashlib.md5(u.encode()).hexdigest(): u for u in sessions}
            for tbl in [n for n in names if n.startswith("Msg_")]:
                conv = table_conv.get(tbl)
                if conv is None:
                    continue
                is_group = conv.endswith("@chatroom")
                for r in con.execute(
                        'SELECT local_type, real_sender_id, create_time, message_content FROM "%s"' % tbl):
                    ltype = (r["local_type"] or 0) & 0xFFFFFFFF
                    content = None
                    if ltype == 49 or is_group:
                        content = zstd_text(r["message_content"])
                    yield {
                        "conversation": conv,
                        "is_group": is_group,
                        "sender_un": n2i.get(r["real_sender_id"], ""),
                        "ltype": ltype,
                        "ts": int(r["create_time"] or 0),
                        "content": content,
                    }
        finally:
            con.close()


def detect_owner(messages, env=None):
    """My own username. Override via env/WXGRAPH_OWNER; else the most common
    non-conversation sender across 1:1 chats (in a 1:1 with X, a sender != X is me).
    VERIFY-AGAINST-REAL: confirmed against fixture 1:1 tables; on real data the
    env override is the escape hatch if inference is ever wrong."""
    ov = env or os.environ.get("WXGRAPH_OWNER")
    if ov:
        return ov
    votes = Counter()
    for m in messages:
        if m["is_group"] or not m["sender_un"]:
            continue
        if m["sender_un"] != m["conversation"]:
            votes[m["sender_un"]] += 1
    return votes.most_common(1)[0][0] if votes else None
