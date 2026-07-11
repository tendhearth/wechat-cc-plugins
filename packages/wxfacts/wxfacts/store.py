"""facts.sqlite: a flexible claim table + per-contact extraction watermark."""
import json
import sqlite3
from pathlib import Path

_CONF = {"low": 0, "med": 1, "high": 2}


class FactStore:
    def __init__(self, state_dir):
        d = Path(state_dir) / "wxfacts"
        d.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(d / "facts.sqlite"))
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS facts ("
            "id INTEGER PRIMARY KEY, contact TEXT, kind TEXT, predicate TEXT, value TEXT, "
            "related_contact TEXT, time_ref TEXT, confidence TEXT, source_msg_keys TEXT, "
            "status TEXT, created_at INTEGER, updated_at INTEGER, "
            "UNIQUE(contact, predicate, value))")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS extraction_state ("
            "contact TEXT PRIMARY KEY, last_ts INTEGER, updated_at INTEGER)")
        self.con.commit()

    def _row(self, r):
        d = dict(r)
        d["source_msg_keys"] = json.loads(d["source_msg_keys"]) if d["source_msg_keys"] else []
        return d

    def upsert_fact(self, fact, now):
        contact, pred, val = fact["contact"], fact["predicate"], fact["value"]
        keys = list(fact.get("source_msg_keys") or [])
        conf = fact.get("confidence") or "med"
        cur = self.con.execute(
            "SELECT * FROM facts WHERE contact=? AND predicate=? AND value=?",
            (contact, pred, val)).fetchone()
        if cur is None:
            self.con.execute(
                "INSERT INTO facts(contact,kind,predicate,value,related_contact,time_ref,"
                "confidence,source_msg_keys,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (contact, fact.get("kind"), pred, val, fact.get("related_contact"),
                 fact.get("time_ref"), conf, json.dumps(keys, ensure_ascii=False),
                 "active", now, now))
            self.con.commit()
            return "inserted"
        prev = self._row(cur)
        merged = list(dict.fromkeys(prev["source_msg_keys"] + keys))     # ordered union
        best = conf if _CONF.get(conf, 1) > _CONF.get(prev["confidence"] or "med", 1) else prev["confidence"]
        rel = fact.get("related_contact") or prev["related_contact"]
        tref = fact.get("time_ref") or prev["time_ref"]
        self.con.execute(
            "UPDATE facts SET kind=?, related_contact=?, time_ref=?, confidence=?, "
            "source_msg_keys=?, updated_at=? WHERE id=?",                # status untouched
            (fact.get("kind") or prev["kind"], rel, tref, best,
             json.dumps(merged, ensure_ascii=False), now, prev["id"]))
        self.con.commit()
        return "merged"

    def get_watermark(self, contact):
        r = self.con.execute(
            "SELECT last_ts FROM extraction_state WHERE contact=?", (contact,)).fetchone()
        return r[0] if r else 0

    def advance_watermark(self, contact, ts, now):
        new = max(self.get_watermark(contact), int(ts))
        self.con.execute(
            "INSERT INTO extraction_state(contact,last_ts,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(contact) DO UPDATE SET last_ts=excluded.last_ts, updated_at=excluded.updated_at",
            (contact, new, now))
        self.con.commit()

    def all_watermarks(self):
        return {r["contact"]: r["last_ts"]
                for r in self.con.execute("SELECT contact,last_ts FROM extraction_state")}

    def facts_for(self, contact, status="active"):
        rows = self.con.execute(
            "SELECT * FROM facts WHERE contact=? AND status=? ORDER BY updated_at DESC",
            (contact, status)).fetchall()
        return [self._row(r) for r in rows]

    def find(self, kind, predicate, query, status, limit):
        sql = "SELECT * FROM facts WHERE status=?"
        args = [status]
        if kind:
            sql += " AND kind=?"; args.append(kind)
        if predicate:
            sql += " AND predicate=?"; args.append(predicate)
        if query:
            sql += " AND (predicate LIKE '%'||?||'%' OR value LIKE '%'||?||'%')"
            args += [query, query]
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [self._row(r) for r in self.con.execute(sql, args).fetchall()]

    def set_status(self, fid, status, now):
        cur = self.con.execute(
            "UPDATE facts SET status=?, updated_at=? WHERE id=?", (status, now, fid))
        self.con.commit()
        return cur.rowcount > 0

    def counts_by_kind(self):
        return {r["kind"]: r["n"] for r in self.con.execute(
            "SELECT kind, COUNT(*) n FROM facts GROUP BY kind")}

    def close(self):
        self.con.close()
