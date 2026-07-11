import pytest

from wxsearch.embed import _default_embed_fn, _FE


def test_default_embed_fn_unmapped_model_raises(tmp_path):
    # An embedding model id with no fastembed mapping must fail clearly BEFORE any
    # fastembed import/download — so this runs even without fastembed installed.
    d = tmp_path / "nope-model"
    d.mkdir()
    with pytest.raises(ValueError, match="no fastembed mapping"):
        _default_embed_fn(d, ["hi"])


def test_fe_map_covers_every_registry_embedding_tier():
    # Guards the "added/renamed a tier, forgot the fastembed mapping" drift.
    from wxsearch._deps import ensure_model_manager
    ensure_model_manager()
    from model_manager.registry import for_capability_tier
    for tier in ("light", "high"):
        spec = for_capability_tier("embedding", tier)
        assert spec is not None
        assert spec.id in _FE, "embedding %s tier id %r missing from wxsearch.embed._FE" % (tier, spec.id)
