"""Orchestrate the candidate feed, record-and-advance, and fact queries."""
from collections import defaultdict
from pathlib import Path

from .source import iter_1to1_messages, encode_batch_id, decode_batch_id


def _grouped(state_dir):
    g = defaultdict(list)
    for m in iter_1to1_messages(state_dir):
        g[m["conversation"]].append(m)
    for c in g:
        g[c].sort(key=lambda x: (x["ts"], x["local_id"]))   # total order for the cursor
    return g


def _display_map(state_dir):
    try:
        from wxgraph.graph import load_display_map
        return load_display_map(state_dir)
    except Exception:
        return {}


def _resolve_contact(store, state_dir, name):
    """wxgraph graph.sqlite resolves display->username if present; else treat name as username."""
    try:
        gpath = Path(state_dir) / "wxgraph" / "graph.sqlite"
        if gpath.exists():
            from wxgraph.graph import resolve_name
            from wxgraph.store import GraphStore
            gs = GraphStore(state_dir)
            try:
                un, _cands = resolve_name(gs, name)
                if un:
                    return un
            finally:
                gs.close()
    except Exception:
        pass
    return name


def next_batch(store, state_dir, contact=None, limit=40):
    grouped = _grouped(state_dir)
    wms = store.all_watermarks()

    def backlog(c):
        wm = wms.get(c, (0, 0))
        return [m for m in grouped.get(c, []) if (m["ts"], m["local_id"]) > wm]

    if contact:
        contact = _resolve_contact(store, state_dir, contact)
        msgs = backlog(contact)
    else:
        contact, best_n = None, 0
        for c in grouped:
            n = len(backlog(c))
            if n > best_n:
                contact, best_n = c, n
        msgs = backlog(contact) if contact else []
    msgs = msgs[:limit]   # the (ts, local_id) cursor is exact — no same-ts extension needed
    if not msgs:
        return {"done": True}
    last = msgs[-1]
    covers_ts, covers_lid = last["ts"], last["local_id"]
    dmap = _display_map(state_dir)
    return {"batch_id": encode_batch_id(contact, covers_ts, covers_lid), "contact": contact,
            "display": dmap.get(contact, contact), "covers_until_ts": covers_ts,
            "messages": [{"msg_key": m["msg_key"], "sender": dmap.get(m["sender_un"], m["sender_un"]),
                          "time": m["ts"], "text": m["text"]} for m in msgs]}


def record(store, batch_id, facts, now):
    contact, covers_ts, covers_lid = decode_batch_id(batch_id)
    inserted = merged = 0
    for f in (facts or []):
        f = dict(f)
        f.setdefault("contact", contact)
        if store.upsert_fact(f, now) == "inserted":
            inserted += 1
        else:
            merged += 1
    store.advance_watermark(contact, covers_ts, covers_lid, now)
    return {"recorded": inserted, "merged": merged, "advanced_to": store.get_watermark(contact)[0]}


def contact_facts(store, state_dir, name):
    un = _resolve_contact(store, state_dir, name)
    by_kind = defaultdict(list)
    for f in store.facts_for(un, status="active"):
        by_kind[f["kind"]].append(f)
    return {"resolved": True, "contact": un,
            "display": _display_map(state_dir).get(un, un), "by_kind": dict(by_kind)}


def find_facts(store, kind, predicate, query, status, limit):
    return {"results": store.find(kind, predicate, query, status or "active", limit or 50)}


def set_fact_status(store, fid, status, now):
    return {"ok": store.set_status(fid, status, now)}


def extraction_status(store, state_dir):
    grouped = _grouped(state_dir)
    wms = store.all_watermarks()
    per, caught = [], 0
    for c, msgs in grouped.items():
        wm = wms.get(c, (0, 0))
        remaining = sum(1 for m in msgs if (m["ts"], m["local_id"]) > wm)
        if remaining == 0:
            caught += 1
        per.append({"contact": c, "extracted_until": wm[0], "remaining": remaining})
    per.sort(key=lambda x: -x["remaining"])
    return {"contacts": len(grouped), "caught_up": caught,
            "facts_by_kind": store.counts_by_kind(), "backlog": per[:50]}
