"""Candidate feed: readable 1:1 message text (via wxgraph's decode helpers) + batch tokens."""
import glob
import hashlib
import json
import os
import sqlite3

from ._deps import ensure_wxgraph

ensure_wxgraph()                                  # put sibling wxgraph on sys.path FIRST
from wxgraph.source import _ro, zstd_text          # noqa: E402  (reuse proven read-only + zstd decode)

TEXT_TYPE = 1


def iter_1to1_messages(state_dir):
    """Yield readable text of each 1:1 (non-group) TEXT message with a cross-referenceable
    msg_key ('Msg_<md5>:<local_id>')."""
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
                if conv is None or conv.endswith("@chatroom"):   # 1:1 only
                    continue
                for r in con.execute(
                        'SELECT local_id, local_type, real_sender_id, create_time, '
                        'message_content FROM "%s"' % tbl):
                    ltype = (r["local_type"] or 0) & 0xFFFFFFFF
                    if ltype != TEXT_TYPE:                        # v1: pure text messages only
                        continue
                    text = zstd_text(r["message_content"]).strip()
                    if not text:
                        continue
                    yield {"msg_key": "%s:%s" % (tbl, r["local_id"]), "conversation": conv,
                           "sender_un": n2i.get(r["real_sender_id"], ""),
                           "ts": int(r["create_time"] or 0), "local_id": int(r["local_id"] or 0),
                           "text": text}
        finally:
            con.close()


def encode_batch_id(contact, covers_ts, covers_local_id):
    return json.dumps({"c": contact, "u": int(covers_ts), "l": int(covers_local_id)}, ensure_ascii=False)


def decode_batch_id(batch_id):
    d = json.loads(batch_id)
    return d["c"], int(d["u"]), int(d.get("l", 0))   # "l" optional for pre-cursor batch_ids
