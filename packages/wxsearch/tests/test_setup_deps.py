"""Dry-run tests for setup.py's embedding-runtime dep install logic.
Never actually pip-installs — subprocess.run is monkeypatched to record calls."""
import builtins
import importlib.util
import sys
from pathlib import Path

from wxsearch._deps import ensure_model_manager

ensure_model_manager()

SETUP_PATH = Path(__file__).resolve().parents[1] / "setup.py"


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("wxsearch_setup_under_test", SETUP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_installs_onnxruntime_and_tokenizers_when_missing(monkeypatch):
    setup = _load_setup_module()

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("onnxruntime", "tokenizers"):
            raise ImportError("simulated: %s not installed" % name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        class R: returncode = 0
        return R()

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    monkeypatch.delenv("WXVAULT_STATE_DIR", raising=False)

    setup._ensure_embedding_runtime_deps()

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "pip"]
    assert "install" in cmd
    assert "onnxruntime" in cmd
    assert "tokenizers" in cmd


def test_skips_install_when_already_present(monkeypatch):
    setup = _load_setup_module()

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("onnxruntime", "tokenizers"):
            return object()  # pretend it's importable
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    calls = []
    monkeypatch.setattr(setup.subprocess, "run", lambda cmd: calls.append(cmd))
    monkeypatch.delenv("WXVAULT_STATE_DIR", raising=False)

    setup._ensure_embedding_runtime_deps()

    assert calls == []
