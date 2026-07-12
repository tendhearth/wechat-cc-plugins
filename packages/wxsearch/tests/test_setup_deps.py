"""setup.py delegates venv creation to model_manager.plugin_venv. Verify the
deps it requests + that it resolves model-manager — without building a venv or
installing anything (ensure_plugin_venv is monkeypatched)."""
import importlib.util
from pathlib import Path

from wxsearch._deps import ensure_model_manager

ensure_model_manager()

SETUP_PATH = Path(__file__).resolve().parents[1] / "setup.py"


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("wxsearch_setup_under_test", SETUP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_main_builds_venv_with_numpy_and_fastembed(monkeypatch):
    import model_manager.plugin_venv as pv
    calls = []

    def fake_ensure(plugin_dir, deps, log=print):
        calls.append((plugin_dir, deps))
        return "/fake/.venv/bin/python"

    monkeypatch.setattr(pv, "ensure_plugin_venv", fake_ensure)

    setup = _load_setup_module()
    setup.main()

    assert len(calls) == 1
    plugin_dir, deps = calls[0]
    assert plugin_dir.endswith("wxsearch")
    assert deps == ["numpy", "fastembed"]   # fastembed pulls onnxruntime + tokenizers
