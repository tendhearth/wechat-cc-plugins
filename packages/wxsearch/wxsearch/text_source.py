"""Yield searchable chunks: text messages (message_content) + wxmedia-derived media text."""
import glob
import os
import sqlite3
from pathlib import Path

TEXT_TYPE = 1
KIND_BY_TYPE = {34: "voice", 3: "image"}   # WeChat local_type -> media kind


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


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


def _strip_sender_prefix(content):
    # group messages store "<sender_id>:\n<body>"
    nl = content.find("\n")
    if nl != -1 and ":" in content[:nl]:
        return content[nl + 1:]
    return content


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
            import hashlib
            table_conv = {}
            for un in sessions:
                table_conv["Msg_" + hashlib.md5(un.encode()).hexdigest()] = un
            for tbl in [n for n in names if n.startswith("Msg_")]:
                conv = table_conv.get(tbl, tbl)
                # Fallback: if table not in mapping and there's only one session, use it
                if conv == tbl and len(sessions) == 1:
                    conv = next(iter(sessions))
                for r in con.execute(
                        'SELECT local_id, local_type, real_sender_id, create_time, server_id, '
                        'message_content FROM "%s"' % tbl):
                    ltype = (r["local_type"] or 0) & 0xFFFFFFFF
                    svr = str(r["server_id"]) if r["server_id"] else ""
                    if ltype == TEXT_TYPE:
                        text = _strip_sender_prefix(r["message_content"] or "").strip()
                        kind = "text"
                    elif svr in derived:
                        kind, text = derived[svr]
                        text = (text or "").strip()
                    else:
                        continue
                    if not text:
                        continue
                    yield {
                        "msg_key": "%s:%s" % (tbl, r["local_id"]),
                        "conversation": conv,
                        "sender": n2i.get(r["real_sender_id"], str(r["real_sender_id"])),
                        "time": int(r["create_time"] or 0),
                        "type": kind,
                        "text": text,
                    }
        finally:
            con.close()
