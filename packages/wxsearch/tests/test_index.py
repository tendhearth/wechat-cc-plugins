from wxsearch.index import IndexStore

def test_new_store_is_empty(tmp_path):
    s = IndexStore(tmp_path)
    assert s.count() == 0
    assert s.has("x:1") is False
    assert s.get_meta("embed_model") is None
    s.close()

def test_meta_roundtrip(tmp_path):
    s = IndexStore(tmp_path)
    s.set_meta("embed_model", "bge-small-zh-v1.5")
    assert s.get_meta("embed_model") == "bge-small-zh-v1.5"
    s.set_meta("embed_model", "bge-m3")           # upsert
    assert s.get_meta("embed_model") == "bge-m3"
    s.close()

def test_fts_table_created_and_queryable(tmp_path):
    s = IndexStore(tmp_path)
    # inserting into docs + docs_fts directly proves the FTS5 trigram table exists
    s.con.execute("INSERT INTO docs(msg_key, text) VALUES('a:1','响水石板大米')")
    rid = s.con.execute("SELECT rowid FROM docs WHERE msg_key='a:1'").fetchone()[0]
    s.con.execute("INSERT INTO docs_fts(rowid, text) VALUES(?, '响水石板大米')", (rid,))
    s.con.commit()
    hit = s.con.execute("SELECT rowid FROM docs_fts WHERE docs_fts MATCH '石板大'").fetchall()
    assert len(hit) == 1
    s.close()

def test_persists_and_clear(tmp_path):
    s = IndexStore(tmp_path)
    s.con.execute("INSERT INTO docs(msg_key, text) VALUES('a:1','hi')"); s.con.commit()
    assert s.count() == 1
    s.clear()
    assert s.count() == 0
    s.close()
