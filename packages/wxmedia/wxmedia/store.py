"""Idempotent store for derived media text (sidecar sqlite in state dir)."""
import sqlite3
from pathlib import Path


class DerivedStore:
    def __init__(self, state_dir):
        d = Path(state_dir) / "wxmedia"
        d.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(d / "derived.sqlite"))
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS media_text ("
            "svr_id TEXT PRIMARY KEY, kind TEXT, text TEXT, model_id TEXT, created_at INTEGER)")
        self.con.commit()

    def has(self, svr_id: str) -> bool:
        r = self.con.execute("SELECT 1 FROM media_text WHERE svr_id=?", (str(svr_id),)).fetchone()
        return r is not None

    def put(self, svr_id, kind, text, model_id, created_at) -> None:
        self.con.execute(
            "INSERT INTO media_text(svr_id, kind, text, model_id, created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(svr_id) DO UPDATE SET kind=excluded.kind, text=excluded.text, "
            "model_id=excluded.model_id, created_at=excluded.created_at",
            (str(svr_id), kind, text, model_id, int(created_at)))
        self.con.commit()

    def get(self, svr_id):
        r = self.con.execute("SELECT * FROM media_text WHERE svr_id=?", (str(svr_id),)).fetchone()
        return dict(r) if r else None

    def count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM media_text").fetchone()[0]

    def close(self) -> None:
        self.con.close()
