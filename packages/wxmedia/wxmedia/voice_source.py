"""Read WeChat voice blobs from wxvault's decrypted media_*.sqlite (read-only)."""
import glob
import os
import sqlite3
from pathlib import Path


def find_media_dbs(state_dir) -> list:
    pat = os.path.join(str(state_dir), "out", "decrypted", "media_*.sqlite")
    return [Path(p) for p in sorted(glob.glob(pat))]


def iter_voice(state_dir):
    for db in find_media_dbs(state_dir):
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        con.row_factory = sqlite3.Row
        try:
            names = [x[0] for x in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            if "VoiceInfo" not in names:
                continue
            for r in con.execute(
                    "SELECT svr_id, local_id, voice_data FROM VoiceInfo WHERE length(voice_data)>0"):
                svr = str(r["svr_id"]) if r["svr_id"] else "local_%s" % r["local_id"]
                yield {"svr_id": svr, "voice_data": bytes(r["voice_data"])}
        finally:
            con.close()
