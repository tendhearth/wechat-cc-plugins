"""Assemble one person's unified brief from the sibling plugins — DATA ONLY.

person_brief(name) resolves a WeChat contact by name and fans out to the
sibling plugins' functions to gather the *computed data* about that person:
relationship stats (wxgraph), structured facts + open obligations (wxfacts),
and recent messages (wxsearch's decoded index, via a plain read-only query).
It deliberately does NOT read the daemon's .md memory — the daemon already
injects the chat's profile as core memory, and the agent composes "its take +
this data". Each source is independent and degrades gracefully: a missing or
empty sibling store yields an empty field, never a crash.
"""
import os
import sqlite3

from ._deps import ensure_siblings

ensure_siblings()

from wxgraph.store import GraphStore  # noqa: E402
from wxgraph.graph import resolve_name, contact_profile  # noqa: E402


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _facts(state_dir, name):
    """Grouped active facts for this contact (wxfacts). None if store absent."""
    def run():
        from wxfacts.store import FactStore
        from wxfacts.facts import contact_facts
        store = FactStore(state_dir)
        try:
            return contact_facts(store, state_dir, name)
        finally:
            store.close()
    return _safe(run, None)


def _obligations(state_dir, un, name):
    """Active obligations touching this person (as subject or related party)."""
    def run():
        from wxfacts.store import FactStore
        from wxfacts.facts import find_facts
        store = FactStore(state_dir)
        try:
            results = find_facts(store, "obligation", None, None, "active", 100).get("results", [])
        finally:
            store.close()
        return [r for r in results
                if r.get("contact") == un or r.get("related_contact") in (un, name)]
    return _safe(run, [])


def _recent(state_dir, un, n):
    """Newest-first recent messages in this contact's conversation (wxsearch
    index). Plain read-only sqlite — no embedding, no write-path side effects."""
    path = os.path.join(str(state_dir), "index.sqlite")
    if not os.path.exists(path):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT sender, time, text FROM docs WHERE conversation=? "
            "ORDER BY time DESC LIMIT ?", (un, n)).fetchall()
        return [{"sender": r["sender"], "time": r["time"], "text": r["text"]} for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def person_brief(state_dir, name, recent_n=12):
    """One assembled view of a person, keyed by name. See module docstring."""
    store = GraphStore(state_dir)
    try:
        un, cands = resolve_name(store, name)
        if un is None:
            return {"name": name, "resolved": False, "candidates": cands}
        relationship = _safe(lambda: contact_profile(store, name))
    finally:
        store.close()
    return {
        "name": name,
        "resolved": True,
        "wxid": un,
        "relationship": relationship,
        "facts": _facts(state_dir, name),
        "obligations": _obligations(state_dir, un, name),
        "recent_messages": _recent(state_dir, un, recent_n),
    }
