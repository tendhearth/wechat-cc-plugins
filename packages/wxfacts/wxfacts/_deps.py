"""Resolve the sibling `wxgraph` package from the monorepo.

wxfacts reuses `wxgraph`'s message-decode helpers (and, optionally, its
contact graph). `wxgraph` lives at `packages/wxgraph` — not on PyPI. This puts
the sibling on sys.path so `import wxgraph` works without an install step.
"""
import importlib.util
import os
import sys
from pathlib import Path


def wxgraph_dir() -> str:
    # this file: packages/wxfacts/wxfacts/_deps.py -> packages/wxgraph
    return str(Path(__file__).resolve().parents[2] / "wxgraph")


def ensure_wxgraph() -> None:
    """Make `wxgraph` importable, preferring an already-installed copy."""
    if importlib.util.find_spec("wxgraph") is not None:
        return
    p = wxgraph_dir()
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)
