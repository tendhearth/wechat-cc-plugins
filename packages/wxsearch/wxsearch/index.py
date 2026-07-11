"""Sidecar search index: docs + FTS5(trigram) + meta, in the state dir."""
import sqlite3
from pathlib import Path


class IndexStore:
    def __init__(self, state_dir):
        d = Path(state_dir) / "wxsearch"
        d.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(d / "index.sqlite"))
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS docs ("
            "rowid INTEGER PRIMARY KEY, msg_key TEXT UNIQUE, conversation TEXT, "
            "sender TEXT, time INTEGER, type TEXT, text TEXT, vector BLOB, model_id TEXT)")
        self.con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5("
            "text, tokenize='trigram')")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.con.commit()

    def has(self, msg_key: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM docs WHERE msg_key=?", (msg_key,)).fetchone() is not None

    def count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]

    def get_meta(self, key: str):
        r = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self.con.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.con.commit()

    def clear(self) -> None:
        self.con.execute("DELETE FROM docs")
        self.con.execute("DELETE FROM docs_fts")
        self.con.execute("DELETE FROM meta")
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def upsert(self, chunk, vector, model_id) -> None:
        import numpy as np
        blob = None if vector is None else np.asarray(vector, dtype=np.float32).tobytes()
        cur = self.con.execute("SELECT rowid FROM docs WHERE msg_key=?", (chunk["msg_key"],)).fetchone()
        if cur is not None:
            rid = cur[0]
            self.con.execute(
                "UPDATE docs SET conversation=?, sender=?, time=?, type=?, text=?, vector=?, model_id=? "
                "WHERE rowid=?",
                (chunk["conversation"], chunk["sender"], chunk["time"], chunk["type"],
                 chunk["text"], blob, model_id, rid))
            self.con.execute("DELETE FROM docs_fts WHERE rowid=?", (rid,))
        else:
            cur = self.con.execute(
                "INSERT INTO docs(msg_key, conversation, sender, time, type, text, vector, model_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (chunk["msg_key"], chunk["conversation"], chunk["sender"], chunk["time"],
                 chunk["type"], chunk["text"], blob, model_id))
            rid = cur.lastrowid
        self.con.execute("INSERT INTO docs_fts(rowid, text) VALUES(?, ?)", (rid, chunk["text"]))
        self.con.commit()

    def load_vectors(self, model_id=None):
        import numpy as np
        if model_id is None:
            rows = self.con.execute(
                "SELECT rowid, vector FROM docs WHERE vector IS NOT NULL ORDER BY rowid").fetchall()
        else:   # defense-in-depth: stack only the requested model's vectors -> never mixed dims
            rows = self.con.execute(
                "SELECT rowid, vector FROM docs WHERE vector IS NOT NULL AND model_id = ? "
                "ORDER BY rowid", (model_id,)).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        rowids = [r["rowid"] for r in rows]
        mat = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        return rowids, mat

    def keyword_search(self, query, k):
        q = (query or "").strip()
        if not q:
            return []
        if len(q) >= 3:
            # Wrap as a single FTS5 phrase literal so user punctuation / operator words
            # (AND, -, ", *, :, ...) are matched literally instead of raising a MATCH syntax error.
            fq = '"' + q.replace('"', '""') + '"'
            rows = self.con.execute(
                "SELECT rowid FROM docs_fts WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts) LIMIT ?",
                (fq, k)).fetchall()
        else:
            rows = self.con.execute(
                "SELECT rowid FROM docs WHERE text LIKE '%'||?||'%' ORDER BY length(text) ASC LIMIT ?",
                (q, k)).fetchall()
        return [r["rowid"] for r in rows]

    def get_docs(self, rowids):
        out = {}
        for rid in rowids:
            r = self.con.execute(
                "SELECT conversation, sender, time, type, text FROM docs WHERE rowid=?", (rid,)).fetchone()
            if r:
                out[rid] = dict(r)
        return out
