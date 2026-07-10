import importlib.util, os
from wxsearch._deps import model_manager_dir, ensure_model_manager

def test_dir_points_at_sibling():
    assert model_manager_dir().replace(os.sep, "/").endswith("packages/model-manager")

def test_dir_exists_in_monorepo():
    assert os.path.isdir(model_manager_dir())

def test_ensure_makes_importable():
    ensure_model_manager()
    assert importlib.util.find_spec("model_manager") is not None
