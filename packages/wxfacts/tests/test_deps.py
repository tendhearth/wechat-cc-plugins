import importlib.util
import os

from wxfacts._deps import wxgraph_dir, ensure_wxgraph


def test_wxgraph_dir_points_at_sibling():
    p = wxgraph_dir()
    assert p.replace(os.sep, "/").endswith("packages/wxgraph")


def test_wxgraph_dir_exists_in_monorepo():
    assert os.path.isdir(wxgraph_dir())


def test_ensure_makes_wxgraph_importable():
    ensure_wxgraph()
    assert importlib.util.find_spec("wxgraph") is not None
