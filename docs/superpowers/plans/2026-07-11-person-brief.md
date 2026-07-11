# `wxperson` / person_brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** A bundled plugin `wxperson` with one MCP tool `person_brief(name)` that assembles a contact's relationship (wxgraph) + facts/obligations (wxfacts) + recent messages (wxsearch) into one JSON view.

**Architecture:** New `packages/wxperson` mirroring the sibling plugins. `_deps.py` puts siblings on sys.path; `brief.py` is the testable assembly (opens each sibling store off one `state_dir`, degrades gracefully if a store is absent); `server.py` is the MCP stdio shell. Data-only — never reads daemon `.md`.

**Tech Stack:** Python 3, stdlib sqlite3, MCP stdio JSON-RPC (same framing as wxgraph/wxfacts/wxsearch), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-11-person-brief-design.md`.
- **Pure local, no network** (hard constraint for the whole suite).
- `state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))` — same convention as siblings' `server.py`.
- Sibling functions (call verbatim — do not reimplement):
  - `from wxgraph.store import GraphStore`; `from wxgraph.graph import resolve_name, contact_profile`. `resolve_name(store, name) -> (un|None, candidates)`; `contact_profile(store, name) -> dict` (has `resolved`, and on hit the contact fields).
  - `from wxfacts.store import FactStore`; `from wxfacts.facts import contact_facts, find_facts`. `contact_facts(store, state_dir, name) -> dict`; `find_facts(store, kind, predicate, query, status, limit) -> {"results":[...]}`.
  - `from wxsearch.index import IndexStore` — opens `<state_dir>/index.sqlite`; table `docs(msg_key, conversation, sender, time, type, text, vector, model_id)`.
- Return shapes exactly per spec §2. Newest-first recent_messages, default N=12.
- Manifest bundled + enabled, NOT hidden.
- TDD; explicit `git add`; each task ends green.

---

### Task 1: package scaffold + `_deps.py`

**Files:**
- Create: `packages/wxperson/pyproject.toml`, `packages/wxperson/setup.py`, `packages/wxperson/wechat-cc.plugin.json`, `packages/wxperson/wxperson/__init__.py`, `packages/wxperson/wxperson/_deps.py`
- Test: `packages/wxperson/tests/test_deps.py`

**Interfaces:**
- Produces: `wxperson._deps.ensure_siblings() -> None` — after calling it, `import wxgraph`, `import wxfacts`, `import wxsearch` all succeed.

- [ ] **Step 1: Copy a sibling's packaging as the template.** Read `packages/wxgraph/pyproject.toml`, `setup.py`, `wechat-cc.plugin.json` and produce the `wxperson` equivalents: package name `wxperson`, description "统一人物简报:一次组装某人的关系/事实/近期消息", entry/console-script matching the sibling convention (a `wxperson.server:main` stdio entry if the sibling defines one — match exactly what wxgraph does). Manifest: same fields as wxgraph's, `name: "wxperson"`, an MCP command that runs the server the same way wxgraph's does, bundled+enabled, no `hidden` key.

- [ ] **Step 2: Write `_deps.py`** mirroring `packages/wxfacts/wxfacts/_deps.py` but for THREE siblings. Pattern:
```python
"""Resolve sibling packages (wxgraph/wxfacts/wxsearch) from the monorepo so
`import wxgraph`/`wxfacts`/`wxsearch` work without an install step."""
import importlib.util, os, sys
from pathlib import Path

_SIBLINGS = ("wxgraph", "wxfacts", "wxsearch")

def _sibling_dir(name):
    # this file: packages/wxperson/wxperson/_deps.py -> packages/<name>
    return str(Path(__file__).resolve().parents[2] / name)

def ensure_siblings():
    for name in _SIBLINGS:
        if importlib.util.find_spec(name) is not None:
            continue
        p = _sibling_dir(name)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
```

- [ ] **Step 3: Write the failing test** `tests/test_deps.py`:
```python
def test_ensure_siblings_makes_them_importable():
    from wxperson._deps import ensure_siblings
    ensure_siblings()
    import wxgraph, wxfacts, wxsearch  # noqa: F401
    assert wxgraph and wxfacts and wxsearch
```

- [ ] **Step 4: Run — expect PASS** (deps resolvable from the monorepo). Run: `cd packages/wxperson && python3 -m pytest tests/test_deps.py -q`. If it fails on import, fix `parents[N]` depth against the real layout.

- [ ] **Step 5: Commit.** `git add packages/wxperson/pyproject.toml packages/wxperson/setup.py packages/wxperson/wechat-cc.plugin.json packages/wxperson/wxperson/__init__.py packages/wxperson/wxperson/_deps.py packages/wxperson/tests/test_deps.py` then `git commit -m "feat(wxperson): package scaffold + sibling resolution"`.

---

### Task 2: `brief.py` assembly core

**Files:**
- Create: `packages/wxperson/wxperson/brief.py`
- Test: `packages/wxperson/tests/test_brief.py`

**Interfaces:**
- Consumes: `ensure_siblings()` from Task 1; the sibling functions in Global Constraints.
- Produces: `wxperson.brief.person_brief(state_dir, name, recent_n=12) -> dict` (the shape in spec §2).

- [ ] **Step 1: Write `brief.py`.** `ensure_siblings()` at import time (top of module, after stdlib imports) so the sibling imports below resolve. Signature `def person_brief(state_dir, name, recent_n=12)`.
  1. Open `GraphStore(state_dir)`; `un, cands = resolve_name(store, name)`. If `un is None`: `return {"name": name, "resolved": False, "candidates": cands}`.
  2. `relationship = _safe(lambda: contact_profile(store, name))` — on the resolved path `contact_profile` returns the contact dict; keep it as-is (it already carries `resolved:true`).
  3. `facts = _safe(lambda: contact_facts(FactStore(state_dir), state_dir, name))`.
  4. `obligations`: `_safe(lambda: find_facts(FactStore(state_dir), "obligation", None, None, "active", 100))` → from `.get("results", [])` keep rows where `r.get("related_contact") in (un, name)` (match resolved wxid OR the queried name). Empty list if the store is absent.
  5. `recent_messages = _recent(state_dir, un, recent_n)` (Step 2).
  6. `return {"name": name, "resolved": True, "wxid": un, "relationship": relationship, "facts": facts, "obligations": obligations, "recent_messages": recent_messages}`.
  `_safe(fn)` runs `fn()` and returns its result, or `None`/`[]` on any `Exception` (missing store, missing table) — a helper so one absent sibling never breaks the whole brief. Use `None` for dict sources (relationship/facts), `[]` for list sources (obligations).

- [ ] **Step 2: `_recent(state_dir, un, n)`** in `brief.py` — open `index.sqlite` read-only directly (don't depend on IndexStore having a recent-query method; a plain read-only connect is enough and avoids write-path side effects):
```python
def _recent(state_dir, un, n):
    import os, sqlite3
    path = os.path.join(str(state_dir), "index.sqlite")
    if not os.path.exists(path):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT sender, time, text FROM docs WHERE conversation=? "
            "ORDER BY time DESC LIMIT ?", (un, n)).fetchall()
        return [{"sender": r["sender"], "time": r["time"], "text": r["text"]} for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()
```

- [ ] **Step 3: Write failing tests** `tests/test_brief.py`. Build a tmp `state_dir` fixture: create `graph.sqlite` via `GraphStore` populated so `resolve_name` finds "张三" → `wxid_zhang`; create `index.sqlite` with a `docs` table holding 15 messages for `conversation="wxid_zhang"` at increasing `time`, plus a few for another contact; create a wxfacts store with one active obligation `related_contact="wxid_zhang"` and one for `"wxid_li"`. (Mirror how `packages/wxgraph/tests` and `packages/wxfacts/tests` build their fixtures — reuse their store constructors/insert helpers; read those test files first.) Assertions:
  - `person_brief(state_dir, "张三")["resolved"] is True` and `["wxid"] == "wxid_zhang"`.
  - `recent_messages` has length 12 (capped from 15) and is newest-first (`times` descending); every row's message belongs to zhang (none from the other contact).
  - `obligations` contains the zhang obligation and NOT the `wxid_li` one.
  - resolve miss: `person_brief(state_dir, "查无此人")["resolved"] is False` and has `candidates`.
  - degradation: delete `index.sqlite` → `recent_messages == []` and `resolved` still True with relationship present (no exception).

- [ ] **Step 4: RED→GREEN.** Run: `cd packages/wxperson && python3 -m pytest tests/test_brief.py -q`. Fix until green.

- [ ] **Step 5: Commit.** `git add packages/wxperson/wxperson/brief.py packages/wxperson/tests/test_brief.py` then `git commit -m "feat(wxperson): person_brief assembly (relationship+facts+obligations+recent)"`.

---

### Task 3: MCP server

**Files:**
- Create: `packages/wxperson/wxperson/server.py`
- Test: `packages/wxperson/tests/test_server.py`

**Interfaces:**
- Consumes: `person_brief(state_dir, name, recent_n)` from Task 2.

- [ ] **Step 1: Write `server.py`** mirroring `packages/wxgraph/wxgraph/server.py` (same `_ok`/`_err`/`_content`/`_call_tool` framing, same stdin/stdout JSON-RPC loop, same `initialize`/`tools/list`/`tools/call` handling — read wxgraph's server.py and copy its structure exactly). Specifics:
```python
TOOLS = [
    {"name": "person_brief",
     "description": "一次组装某人的统一简报:关系画像+结构化事实+未了义务+近期消息(按人名解析)。想整体了解一个人时先用它。",
     "inputSchema": {"type": "object",
        "properties": {"name": {"type": "string"},
                       "recent_n": {"type": "integer"}},
        "required": ["name"]}},
]
```
  In `_call_tool`, for `person_brief`: require `name` (`-32602` "person_brief requires name" if absent); call `deps["person_brief"](args["name"], args.get("recent_n", 12))`; wrap in `_content`. In `main()`: `state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))`; `deps = {"person_brief": lambda name, n: B.person_brief(state_dir, name, n)}` where `from . import brief as B`.

- [ ] **Step 2: Write failing tests** `tests/test_server.py` (mirror `packages/wxgraph/tests/test_server.py`): drive `_call_tool` directly with a stub `deps={"person_brief": lambda name, n: {"name": name, "resolved": True}}`.
  - `tools/list` includes a tool named `person_brief`.
  - `tools/call` with `{"name":"张三"}` → result `content[0].text` parses to JSON with `resolved: true`; the stub received `n == 12`.
  - `tools/call` with no `name` → error code `-32602`.
  - `recent_n` passed through: `{"name":"张三","recent_n":5}` → stub received `n == 5`.

- [ ] **Step 3: RED→GREEN.** Run: `cd packages/wxperson && python3 -m pytest tests/test_server.py -q`.

- [ ] **Step 4: Full package suite + import smoke.** Run: `cd packages/wxperson && python3 -m pytest -q` (all green) and `python3 -c "from wxperson import server, brief, _deps; print('ok')"`.

- [ ] **Step 5: Commit.** `git add packages/wxperson/wxperson/server.py packages/wxperson/tests/test_server.py` then `git commit -m "feat(wxperson): MCP stdio server exposing person_brief"`.

## Self-Review notes

Spec §2 → T2 (assembly + degradation) / §3 packaging → T1 / server → T3. Sibling reuse (no reimplementation) pinned in Global Constraints with verbatim signatures. Degradation tested in T2 (absent index.sqlite). Data-only (no `.md`) is structural — brief.py has no daemon-memory path. Daemon-side prompt routing + obligation flow-back is a SEPARATE wechat-cc change (spec §4 non-goal here). resolve_name/contact_profile/contact_facts/find_facts names consistent T-to-T.
