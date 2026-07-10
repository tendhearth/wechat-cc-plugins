import numpy as np
from wxsearch.index import IndexStore

def _chunk(mk, text, conv="c", sender="s", t=1, typ="text"):
    return {"msg_key": mk, "conversation": conv, "sender": sender, "time": t, "type": typ, "text": text}

def test_upsert_and_load_vectors(tmp_path):
    s = IndexStore(tmp_path)
    s.upsert(_chunk("a:1", "你好世界"), np.array([1.0, 0.0], np.float32), "m1")
    s.upsert(_chunk("a:2", "响水石板大米"), np.array([0.0, 1.0], np.float32), "m1")
    rowids, mat = s.load_vectors()
    assert mat.shape == (2, 2)
    assert len(rowids) == 2
    assert s.count() == 2
    s.close()

def test_upsert_is_idempotent_on_msg_key(tmp_path):
    s = IndexStore(tmp_path)
    s.upsert(_chunk("a:1", "old"), np.array([1.0, 0.0], np.float32), "m1")
    s.upsert(_chunk("a:1", "new"), np.array([0.0, 1.0], np.float32), "m1")
    assert s.count() == 1
    rowids, mat = s.load_vectors()
    docs = s.get_docs(rowids)
    assert docs[rowids[0]]["text"] == "new"
    s.close()

def test_keyword_search_trigram_and_like_fallback(tmp_path):
    s = IndexStore(tmp_path)
    s.upsert(_chunk("a:1", "响水石板大米很好吃"), None, "m1")
    s.upsert(_chunk("a:2", "今天天气不错"), None, "m1")
    assert s.keyword_search("石板大", 10) == [   # 3-char: FTS5 trigram
        s.con.execute("SELECT rowid FROM docs WHERE msg_key='a:1'").fetchone()[0]]
    hit2 = s.keyword_search("石板", 10)          # 2-char: LIKE fallback
    assert len(hit2) == 1
    assert s.keyword_search("找不到xyz", 10) == []
    s.close()

def test_keyword_search_tolerates_fts_special_chars(tmp_path):
    s = IndexStore(tmp_path)
    s.upsert(_chunk("a:1", "讨论 项目 预算 安排"), None, "m1")
    rid = s.con.execute("SELECT rowid FROM docs WHERE msg_key='a:1'").fetchone()[0]
    assert s.keyword_search("项目 预算", 10) == [rid]   # space is not treated as implicit-AND operator
    assert s.keyword_search('未闭合"引号', 10) == []      # unbalanced quote must not raise a MATCH syntax error
    s.close()

def test_load_vectors_empty(tmp_path):
    s = IndexStore(tmp_path)
    s.upsert(_chunk("a:1", "hi"), None, "m1")   # no vector
    rowids, mat = s.load_vectors()
    assert rowids == [] and mat.shape == (0, 0)
    s.close()

def test_get_docs(tmp_path):
    s = IndexStore(tmp_path)
    s.upsert(_chunk("a:1", "hi", conv="grp", sender="bob", t=99, typ="voice"), None, "m1")
    rid = s.con.execute("SELECT rowid FROM docs WHERE msg_key='a:1'").fetchone()[0]
    d = s.get_docs([rid])[rid]
    assert d["conversation"] == "grp" and d["sender"] == "bob" and d["type"] == "voice"
    s.close()
