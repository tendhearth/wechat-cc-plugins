"""Yield searchable chunks: text messages (message_content) + wxmedia-derived media text."""
import glob
import hashlib
import io
import os
import sqlite3
from pathlib import Path

try:
    import zstandard as _zstd
except Exception:                       # zstandard optional; degrade to raw bytes
    _zstd = None

TEXT_TYPE = 1
ZMAGIC = b"\x28\xb5\x2f\xfd"            # WCDB compresses long message_content with dictionary-less zstd
_DCTX = _zstd.ZstdDecompressor() if _zstd else None


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def _to_text(content, sender_un):
    """Decode message_content (str, or zstd-compressed bytes) and strip the group
    sender prefix. Mirrors wxvault_mcp._to_text: prefix is stripped only when it
    exactly matches the resolved sender username, never on a bare colon."""
    if content is None:
        return ""
    if isinstance(content, (bytes, bytearray)):
        b = bytes(content)
        if b[:4] == ZMAGIC and _DCTX is not None:
            try:
                b = _DCTX.decompress(b)
            except Exception:
                try:
                    b = _DCTX.stream_reader(io.BytesIO(b)).read()
                except Exception:
                    pass
        s = b.decode("utf-8", "replace")
    else:
        s = content
    if sender_un:
        for pref in (sender_un + ":\n", sender_un + ":"):
            if s.startswith(pref):
                return s[len(pref):]
    return s


def _load_derived(state_dir):
    p = Path(state_dir) / "wxmedia" / "derived.sqlite"
    out = {}
    if not p.exists():
        return out
    con = _ro(p); con.row_factory = sqlite3.Row
    try:
        for r in con.execute("SELECT svr_id, kind, text FROM media_text WHERE length(text)>0"):
            out[str(r["svr_id"])] = (r["kind"], r["text"])
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    return out


def iter_chunks(state_dir):
    derived = _load_derived(state_dir)
    for dbpath in sorted(glob.glob(os.path.join(str(state_dir), "out", "decrypted", "message_*.sqlite"))):
        con = _ro(dbpath); con.row_factory = sqlite3.Row
        try:
            names = [x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            if "Name2Id" not in names:
                continue
            n2i = {r["rowid"]: r["user_name"]
                   for r in con.execute("SELECT rowid, user_name FROM Name2Id")}
            sessions = {r["user_name"] for r in con.execute(
                "SELECT user_name FROM Name2Id WHERE is_session=1")}
            table_conv = {"Msg_" + hashlib.md5(un.encode()).hexdigest(): un for un in sessions}
            for tbl in [n for n in names if n.startswith("Msg_")]:
                conv = table_conv.get(tbl, tbl)
                for r in con.execute(
                        'SELECT local_id, local_type, real_sender_id, create_time, server_id, '
                        'message_content FROM "%s"' % tbl):
                    ltype = (r["local_type"] or 0) & 0xFFFFFFFF
                    sid = r["real_sender_id"]
                    sender_un = n2i.get(sid)
                    if ltype == TEXT_TYPE:
                        text = _to_text(r["message_content"], sender_un).strip()
                        kind = "text"
                    else:
                        # match wxmedia's key scheme: real server_id, else synthetic local_<id>
                        mkey = str(r["server_id"]) if r["server_id"] else "local_%s" % r["local_id"]
                        if mkey not in derived:
                            continue
                        kind, dtext = derived[mkey]
                        text = (dtext or "").strip()
                    if not text:
                        continue
                    yield {
                        "msg_key": "%s:%s" % (tbl, r["local_id"]),
                        "conversation": conv,
                        "sender": sender_un or (str(sid) if sid else ""),
                        "time": int(r["create_time"] or 0),
                        "type": kind,
                        "text": text,
                    }
        finally:
            con.close()
