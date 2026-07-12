"""ensure_plugin_venv: venv bootstrap logic (subprocess mocked — never really
creates a venv or pip-installs)."""
import os
import sys

import model_manager.plugin_venv as pv


def test_venv_python_path():
    assert pv.venv_python("/x/plug").replace(os.sep, "/") == "/x/plug/.venv/bin/python"


def test_creates_venv_and_installs_when_absent(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pv.subprocess, "run", lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0})())
    # current interpreter is >= 3.10 in CI-of-record, but force the path anyway
    monkeypatch.setattr(pv, "_find_interpreter", lambda: "/opt/py312")

    vpy = pv.ensure_plugin_venv(str(tmp_path), ["numpy", "fastembed"], log=lambda *a: None)

    assert vpy == pv.venv_python(str(tmp_path))
    # venv created with the found interpreter, then deps installed with the venv python
    assert any(c[:3] == ["/opt/py312", "-m", "venv"] for c in calls)
    assert any(c[:3] == [vpy, "-m", "pip"] and "install" in c and "fastembed" in c for c in calls)


def test_skips_venv_creation_when_present_but_still_installs(monkeypatch, tmp_path):
    # pre-create the venv python path so ensure_plugin_venv sees it as existing
    vbin = tmp_path / ".venv" / "bin"
    vbin.mkdir(parents=True)
    (vbin / "python").write_text("#!/bin/sh\n")

    calls = []
    monkeypatch.setattr(pv.subprocess, "run", lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(pv, "_find_interpreter", lambda: (_ for _ in ()).throw(AssertionError("should not look for an interpreter")))

    pv.ensure_plugin_venv(str(tmp_path), ["numpy"], log=lambda *a: None)

    # no `-m venv` call (venv already there); only the pip install
    assert not any("venv" in c for c in calls)
    assert any("install" in c and "numpy" in c for c in calls)


def test_exits_when_no_310_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(pv, "_find_interpreter", lambda: None)
    try:
        pv.ensure_plugin_venv(str(tmp_path), ["numpy"], log=lambda *a: None)
        assert False, "should have exited"
    except SystemExit as e:
        assert "3.10" in str(e.code)


def test_find_interpreter_uses_current_when_new_enough(monkeypatch):
    if sys.version_info[:2] >= (3, 10):
        assert pv._find_interpreter() == sys.executable
