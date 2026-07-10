import sqlite3
import numpy as np
from pathlib import Path
from wxsearch.search import rrf, index_update, reindex, search

def _msg_db(state_dir, rows):
    d = Path(state_dir) / "out" / "decrypted"; d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(d / "message_0.sqlite"))
    con.execute("CREATE TABLE Name2Id (rowid INTEGER PRIMARY KEY, user_name TEXT, is_session INTEGER)")
    con.execute("INSERT INTO Name2Id VALUES (1,'grp@chatroom',1)")
    con.execute("INSERT INTO Name2Id VALUES (2,'grp',0)")
    import hashlib
    tbl = "Msg_" + hashlib.md5(b"grp@chatroom").hexdigest()
    con.execute("CREATE TABLE '%s' (local_id INTEGER, local_type INTEGER, real_sender_id INTEGER, "
                "create_time INTEGER, server_id INTEGER, message_content TEXT)" % tbl)
    con.executemany("INSERT INTO '%s' VALUES(?,?,?,?,?,?)" % tbl, rows)
    con.commit(); con.close()
    return tbl

class KwEmbedder:
    """Deterministic fake: vector = per-keyword one-hot so cosine is meaningful."""
    model_id = "fake-embed"
    VOCAB = ["大米", "天气", "会议"]
    def embed(self, texts):
        v = np.zeros((len(texts), len(self.VOCAB)), np.float32)
        for i, t in enumerate(texts):
            for j, w in enumerate(self.VOCAB):
                if w in t: v[i, j] = 1.0
            if v[i].sum() == 0: v[i, 0] = 0.01
        n = np.linalg.norm(v, axis=1, keepdims=True); n[n == 0] = 1
        return (v / n).astype(np.float32)

def test_rrf_orders_by_fused_score():
    # id 2 appears high in both lists -> should rank first
    assert rrf([1, 2, 3], [2, 4], k=60)[0] == 2

def test_index_update_incremental(tmp_path):
    _msg_db(tmp_path, [(10,1,2,1,100,"grp:\n响水石板大米"), (11,1,2,2,101,"grp:\n今天天气不错")])
    r1 = index_update(tmp_path, KwEmbedder())
    assert r1 == {"indexed": 2, "skipped": 0}
    r2 = index_update(tmp_path, KwEmbedder())     # nothing new
    assert r2 == {"indexed": 0, "skipped": 2}

def test_search_finds_semantic_and_keyword(tmp_path):
    _msg_db(tmp_path, [(10,1,2,1,100,"grp:\n响水石板大米"), (11,1,2,2,101,"grp:\n今天天气不错")])
    index_update(tmp_path, KwEmbedder())
    out = search(tmp_path, "大米", KwEmbedder(), limit=5)
    assert out["vectors_stale"] is False
    assert out["results"][0]["text"] == "响水石板大米"

def test_model_switch_marks_vectors_stale_but_keyword_works(tmp_path):
    _msg_db(tmp_path, [(10,1,2,1,100,"grp:\n响水石板大米")])
    index_update(tmp_path, KwEmbedder())                 # indexed under "fake-embed"
    class Other(KwEmbedder): model_id = "other-model"
    out = search(tmp_path, "石板大", Other(), limit=5)   # different model
    assert out["vectors_stale"] is True
    assert any("石板" in r["text"] for r in out["results"])   # keyword half still works

def test_reindex_rebuilds(tmp_path):
    _msg_db(tmp_path, [(10,1,2,1,100,"grp:\n响水石板大米")])
    index_update(tmp_path, KwEmbedder())
    r = reindex(tmp_path, KwEmbedder())
    assert r["indexed"] == 1

def test_index_update_refuses_on_model_switch(tmp_path):
    _msg_db(tmp_path, [(10,1,2,1,100,"grp:\n响水石板大米")])
    index_update(tmp_path, KwEmbedder())                 # indexed under "fake-embed"
    class Other(KwEmbedder): model_id = "other-model"
    r = index_update(tmp_path, Other())                  # different model must NOT corrupt the index
    assert r.get("model_mismatch") is True and r["indexed"] == 0
    # original index stays intact & queryable under its own model — no mixed-dim crash
    out = search(tmp_path, "石板大", KwEmbedder(), limit=5)
    assert out["vectors_stale"] is False and out["results"]
