def test_ensure_siblings_makes_them_importable():
    from wxperson._deps import ensure_siblings
    ensure_siblings()
    import wxgraph  # noqa: F401
    import wxfacts  # noqa: F401
    import wxsearch  # noqa: F401
    assert wxgraph and wxfacts and wxsearch
