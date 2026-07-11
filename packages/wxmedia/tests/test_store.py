from wxmedia.store import DerivedStore

def test_put_then_get_and_has(tmp_path):
    s = DerivedStore(tmp_path)
    assert s.has("100") is False
    s.put("100", "voice", "你好", "whisper-small", 1720000000)
    assert s.has("100") is True
    row = s.get("100")
    assert row["text"] == "你好"
    assert row["kind"] == "voice"
    assert row["model_id"] == "whisper-small"
    s.close()

def test_put_is_upsert(tmp_path):
    s = DerivedStore(tmp_path)
    s.put("1", "voice", "old", "m", 1)
    s.put("1", "voice", "new", "m", 2)
    assert s.get("1")["text"] == "new"
    assert s.count() == 1
    s.close()

def test_persists_across_instances(tmp_path):
    DerivedStore(tmp_path).put("7", "voice", "hi", "m", 1)
    assert DerivedStore(tmp_path).get("7")["text"] == "hi"

def test_get_missing_is_none(tmp_path):
    assert DerivedStore(tmp_path).get("nope") is None
