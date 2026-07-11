"""Orchestrate the build pipeline and answer relationship queries."""
import glob
import os
import sqlite3
from collections import Counter
from pathlib import Path

from .source import iter_messages, detect_owner, _ro
from .profile import build_profiles, DEFAULT_WEIGHTS
from .edges import build_mention_edges
from .store import GraphStore


def load_display_map(state_dir):
    p = Path(state_dir) / "out" / "decrypted" / "contact.sqlite"
    if not p.exists():
        return {}
    con = _ro(p); con.row_factory = sqlite3.Row
    out = {}
    try:
        for r in con.execute("SELECT username, remark, nick_name, alias FROM contact"):
            un = r["username"]
            out[un] = r["remark"] or r["nick_name"] or r["alias"] or un
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    return out


def _source_max_mtime(state_dir):
    mt = 0.0
    for f in glob.glob(os.path.join(str(state_dir), "out", "decrypted", "message_*.sqlite")):
        mt = max(mt, os.path.getmtime(f))
    return mt


def _invert_display(display_map):
    """display -> username, DROPPING any display shared by >1 contact. Per spec §7 we
    do not disambiguate across identical nicknames: an ambiguous display resolves to
    nobody (its quote-edge is dropped) rather than being misattributed to one arbitrary
    contact. Exact signals (atuserlist wxids, refermsg chatusr) are unaffected."""
    counts = Counter(display_map.values())
    return {disp: un for un, disp in display_map.items() if counts[disp] == 1}


def build(state_dir, now, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    messages = list(iter_messages(state_dir))
    owner = detect_owner(messages)
    display_map = load_display_map(state_dir)
    profiles = build_profiles(messages, owner, now, weights)
    display_to_un = _invert_display(display_map)
    edges = build_mention_edges(messages, owner, display_to_un)
    store = GraphStore(state_dir)
    try:
        store.rebuild(profiles, display_map, owner, edges, now, weights, _source_max_mtime(state_dir))
    finally:
        store.close()
    return {"owner": owner, "contacts": len(profiles), "edges": len(edges), "built_at": now}


def resolve_name(store, name):
    if not name:
        return None, []
    contacts = store.all_contacts()
    for c in contacts:                       # username is a unique id -> exact match wins
        if c["username"] == name:
            return c["username"], []
    disp = [c for c in contacts if c["display"] == name]
    if len(disp) == 1:
        return disp[0]["username"], []
    if len(disp) > 1:                        # colliding display -> disambiguate, never guess
        return None, [{"username": c["username"], "display": c["display"]} for c in disp]
    subs = [c for c in contacts if name in (c["display"] or "") or name in c["username"]]
    if len(subs) == 1:
        return subs[0]["username"], []
    return None, [{"username": c["username"], "display": c["display"]} for c in subs]


def contact_profile(store, name):
    un, cands = resolve_name(store, name)
    if un is None:
        return {"resolved": False, "candidates": cands}
    c = store.get_contact(un)
    c["mention_partners"] = store.edges_for(un, "mention")
    c["resolved"] = True
    return c


_SORT = {"closeness": lambda c: c["closeness"], "volume": lambda c: c["total"],
         "recency": lambda c: c["last_ts"], "reciprocity": lambda c: c["s_reciprocity"],
         "neglected": lambda c: (c["s_volume"] + c["s_intimacy"]) / 2 * (1 - c["s_recency"])}


def top_contacts(store, by, limit=20, kind="person"):
    key = _SORT.get(by, _SORT["closeness"])
    want_group = (kind == "group")           # v1 profiles only persons -> group => []
    contacts = [c for c in store.all_contacts() if bool(c["is_group"]) == want_group]
    return sorted(contacts, key=key, reverse=True)[:limit]


def relationship_subgraph(store, center=None, limit=30):
    contacts = store.all_contacts()
    top = sorted(contacts, key=lambda c: c["closeness"], reverse=True)[:limit]
    keep = {c["username"] for c in top}
    owner = store.get_meta("owner")
    nodes = [{"username": c["username"], "display": c["display"], "closeness": c["closeness"]} for c in top]
    me_edges = [{"a": owner, "b": c["username"], "kind": "me", "weight": c["closeness"]} for c in top]
    ment = []
    for u in keep:
        for e in store.edges_for(u, "mention"):
            if e["a"] in keep and e["b"] in keep:
                ment.append(e)
    dedup = {(e["a"], e["b"]): e for e in ment}
    return {"owner": owner, "nodes": nodes, "edges": me_edges + list(dedup.values())}


def connectors(store, name_a, name_b):
    ua, _ = resolve_name(store, name_a)
    ub, _ = resolve_name(store, name_b)
    if not ua or not ub:
        return {"resolved": False}
    ca, cb = store.get_contact(ua), store.get_contact(ub)
    links = [e for e in store.edges_for(ua, "mention")
             if (e["a"] == ua and e["b"] == ub) or (e["a"] == ub and e["b"] == ua)]
    return {"resolved": True, "a": ua, "b": ub,
            "shared_groups_a": ca["shared_groups"], "shared_groups_b": cb["shared_groups"],
            "mention_edges": links}


def status(store, state_dir):
    # stale = a source message DB changed since we built. Compare current source
    # mtime against the STORED source_max_mtime (not built_at, which is wall-clock
    # `now` and would spuriously read stale when `now` and file mtimes differ in scale).
    built_at = store.get_meta("built_at")
    smt = store.get_meta("source_max_mtime")
    stale = smt is not None and _source_max_mtime(state_dir) > float(smt) + 1e-6
    return {"contacts": store.count(), "owner": store.get_meta("owner"),
            "built_at": int(built_at) if built_at else None, "stale": stale}
