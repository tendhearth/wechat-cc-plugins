import importlib.util
import os

from wxmedia._deps import model_manager_dir, ensure_model_manager


def test_model_manager_dir_points_at_sibling_package():
    p = model_manager_dir()
    # this test file lives in packages/wxmedia; sibling is packages/model-manager
    assert p.replace(os.sep, "/").endswith("packages/model-manager")


def test_model_manager_dir_exists_in_monorepo():
    assert os.path.isdir(model_manager_dir())


def test_ensure_makes_model_manager_importable():
    ensure_model_manager()
    assert importlib.util.find_spec("model_manager") is not None
