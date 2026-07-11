"""Sidecar graph.sqlite: contacts + edges + meta."""
import json
import sqlite3
from pathlib import Path

_CONTACT_COLS = ["username", "display", "is_group", "total", "sent", "recv", "first_ts", "last_ts",
                 "known_days", "active_days", "initiations", "transfer_in", "transfer_out",
                 "shared_groups", "types", "s_volume", "s_recency", "s_reciprocity", "s_intimacy",
                 "closeness"]


class GraphStore:
    def __init__(self, state_dir):
        d = Path(state_dir) / "wxgraph"
        d.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(d / "graph.sqlite"))
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS contacts ("
            "username TEXT PRIMARY KEY, display TEXT, is_group INTEGER, total INTEGER, sent INTEGER, "
            "recv INTEGER, first_ts INTEGER, last_ts INTEGER, known_days INTEGER, active_days INTEGER, "
            "initiations INTEGER, transfer_in INTEGER, transfer_out INTEGER, shared_groups INTEGER, "
            "types TEXT, s_volume REAL, s_recency REAL, s_reciprocity REAL, s_intimacy REAL, closeness REAL)")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS edges (a TEXT, b TEXT, kind TEXT, weight REAL, "
            "PRIMARY KEY(a, b, kind))")
        self.con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.con.commit()

    def rebuild(self, profiles, display_map, owner, mention_edges, now, weights, source_max_mtime):
        self.con.execute("DELETE FROM contacts")
        self.con.execute("DELETE FROM edges")
        self.con.execute("DELETE FROM meta")
        for p in profiles:
            row = dict(p)
            row["display"] = display_map.get(p["username"], p["username"])
            row["is_group"] = 0
            row["types"] = json.dumps(p.get("types", {}), ensure_ascii=False)
            self.con.execute(
                "INSERT INTO contacts (%s) VALUES (%s)" % (
                    ",".join(_CONTACT_COLS), ",".join("?" * len(_CONTACT_COLS))),
                [row[c] for c in _CONTACT_COLS])
            self.con.execute("INSERT INTO edges(a,b,kind,weight) VALUES(?,?,?,?)",
                             (owner, p["username"], "me", float(p["closeness"])))
        for a, b, w in mention_edges:
            self.con.execute(
                "INSERT OR REPLACE INTO edges(a,b,kind,weight) VALUES(?,?,?,?)",
                (a, b, "mention", float(w)))
        for k, v in (("owner", owner), ("built_at", str(now)),
                     ("weights", json.dumps(weights, ensure_ascii=False)),
                     ("source_max_mtime", str(source_max_mtime))):
            self.con.execute("INSERT INTO meta(key,value) VALUES(?,?)", (k, v))
        self.con.commit()

    def _contact_row(self, r):
        d = dict(r)
        d["types"] = json.loads(d["types"]) if d["types"] else {}
        return d

    def get_contact(self, username):
        r = self.con.execute("SELECT * FROM contacts WHERE username=?", (username,)).fetchone()
        return self._contact_row(r) if r else None

    def all_contacts(self):
        return [self._contact_row(r) for r in self.con.execute("SELECT * FROM contacts")]

    def edges_for(self, username, kind):
        rows = self.con.execute(
            "SELECT a,b,kind,weight FROM edges WHERE kind=? AND (a=? OR b=?) ORDER BY weight DESC",
            (kind, username, username)).fetchall()
        return [dict(r) for r in rows]

    def get_meta(self, key):
        r = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def count(self):
        return self.con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    def close(self):
        self.con.close()
