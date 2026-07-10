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
            "text, content='docs', content_rowid='rowid', tokenize='trigram')")
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
