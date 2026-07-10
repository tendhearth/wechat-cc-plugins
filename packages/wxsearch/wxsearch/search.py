"""Hybrid search (cosine + BM25 via RRF) and the incremental index pipeline."""
import numpy as np

from .index import IndexStore
from .text_source import iter_chunks


def rrf(*ranked_lists, k=60):
    scores = {}
    for lst in ranked_lists:
        for rank, rowid in enumerate(lst):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (k + rank)
    return [rid for rid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


def index_update(state_dir, runner, batch=64) -> dict:
    store = IndexStore(state_dir)
    indexed = skipped = 0
    try:
        existing = store.get_meta("embed_model")
        if existing is not None and existing != runner.model_id:
            # Model changed since the index was built. Incrementally embedding now
            # would store vectors of a different dimension alongside the old ones,
            # so load_vectors' np.stack would later crash. Refuse and require reindex.
            return {"indexed": 0, "skipped": 0, "model_mismatch": True}
        pending = []   # (chunk,)
        def flush():
            nonlocal indexed
            if not pending:
                return
            vecs = runner.embed([c["text"] for c in pending])
            for c, v in zip(pending, vecs):
                store.upsert(c, v, runner.model_id)
                indexed += 1
            pending.clear()
        for chunk in iter_chunks(state_dir):
            if store.has(chunk["msg_key"]):
                skipped += 1
                continue
            pending.append(chunk)
            if len(pending) >= batch:
                flush()
        flush()
        if indexed:
            store.set_meta("embed_model", runner.model_id)
    finally:
        store.close()
    return {"indexed": indexed, "skipped": skipped}


def reindex(state_dir, runner, batch=64) -> dict:
    s = IndexStore(state_dir)
    s.clear()
    s.close()
    return index_update(state_dir, runner, batch=batch)


def _cosine_topk(store, runner, query, k):
    rowids, mat = store.load_vectors()
    if not rowids:
        return []
    q = runner.embed([query])[0]
    sims = mat @ q
    order = np.argsort(-sims)[:k]
    return [rowids[i] for i in order]


def search(state_dir, query, runner, limit=10, conversation=None) -> dict:
    store = IndexStore(state_dir)
    try:
        pool = max(limit * 5, 50)
        kw = store.keyword_search(query, pool)
        indexed_model = store.get_meta("embed_model")
        vectors_stale = indexed_model is not None and indexed_model != runner.model_id
        vec = [] if vectors_stale else _cosine_topk(store, runner, query, pool)
        fused = rrf(vec, kw) if vec else kw
        docs = store.get_docs(fused)
        results = []
        for rank, rid in enumerate(fused):
            d = docs.get(rid)
            if not d:
                continue
            if conversation and d["conversation"] != conversation:
                continue
            results.append({**d, "score": len(fused) - rank})
            if len(results) >= limit:
                break
        return {"vectors_stale": vectors_stale, "results": results}
    finally:
        store.close()
