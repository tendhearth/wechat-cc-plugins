"""Resolve sibling packages (wxgraph/wxfacts/wxsearch) from the monorepo.

wxperson assembles a person view from the sibling plugins' functions. They live
at `packages/<name>` — not on PyPI — and ship co-located with wxperson. This
puts each sibling on sys.path so `import wxgraph`/`wxfacts`/`wxsearch` work
without an install step, preferring an already-installed copy.
"""
import importlib.util
import os
import sys
from pathlib import Path

_SIBLINGS = ("wxgraph", "wxfacts", "wxsearch")


def sibling_dir(name: str) -> str:
    # this file: packages/wxperson/wxperson/_deps.py -> packages/<name>
    return str(Path(__file__).resolve().parents[2] / name)


def ensure_siblings() -> None:
    """Make each sibling importable, preferring an already-installed copy."""
    for name in _SIBLINGS:
        if importlib.util.find_spec(name) is not None:
            continue
        p = sibling_dir(name)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
