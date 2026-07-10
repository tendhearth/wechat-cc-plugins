"""Resolve the sibling `model-manager` package from the monorepo.

wxmedia depends on the `model_manager` package, which lives at
`packages/model-manager` in the same monorepo — not on PyPI. When the two
plugins are run/bundled side by side, this puts the sibling on sys.path so
`import model_manager` works without an install step.
"""
import importlib.util
import os
import sys
from pathlib import Path


def model_manager_dir() -> str:
    # this file: packages/wxmedia/wxmedia/_deps.py -> packages/model-manager
    return str(Path(__file__).resolve().parents[2] / "model-manager")


def ensure_model_manager() -> None:
    """Make `model_manager` importable, preferring an already-installed copy."""
    if importlib.util.find_spec("model_manager") is not None:
        return
    p = model_manager_dir()
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)
