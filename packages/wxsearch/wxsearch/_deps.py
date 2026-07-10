"""Resolve the sibling `model-manager` package from the monorepo (same as wxmedia)."""
import importlib.util
import os
import sys
from pathlib import Path


def model_manager_dir() -> str:
    # this file: packages/wxsearch/wxsearch/_deps.py -> packages/model-manager
    return str(Path(__file__).resolve().parents[2] / "model-manager")


def ensure_model_manager() -> None:
    if importlib.util.find_spec("model_manager") is not None:
        return
    p = model_manager_dir()
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)
