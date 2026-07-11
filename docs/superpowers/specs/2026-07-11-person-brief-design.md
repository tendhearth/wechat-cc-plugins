# Design: `wxperson` — person_brief assembly (unified person model, phase 2)

Date: 2026-07-11
Status: approved design → implementation
Origin: unified-person-model phase 2. Phase 1 (daemon-side) shipped a prompt section teaching the agent its knowledge landscape. Phase 2 gives the agent ONE call — `person_brief(name)` — that assembles the scattered per-person data (relationship + facts + obligations + recent messages) from the sibling plugins into a single view, so the agent stops hand-orchestrating 3 plugins per person. See [[architecture-direction-2026]].

## 1. What

A new bundled plugin `wxperson` exposing one MCP tool `person_brief(name)`. It resolves a WeChat contact by name and fans out to the sibling plugins' **Python functions** (not their MCP tools) to assemble `{name, resolved, wxid, relationship, facts, obligations, recent_messages}`. Pure local, no network (hard constraint, same as the whole suite).

## 2. Locked decisions

- **Data only — no `.md` notes.** person_brief assembles the plugin-computed **data view** of a person. It does NOT read the daemon's `.md` memory. The daemon already injects the chat's `profile.md` as core memory every turn, and the phase-1 orchestration section already tells the agent to compose "your take + the data." So unification happens in the agent's reasoning: person_brief = data, agent = the take. This keeps the plugin from reaching into daemon memory (clean layering).
- **Sibling reuse via `_deps.py`** (mirror `wxfacts/_deps.py`): put `packages/wxgraph`, `packages/wxfacts`, `packages/wxsearch` on `sys.path` (prefer an already-installed copy) so `import wxgraph`/`wxfacts`/`wxsearch` work with no install step. person_brief calls their functions directly.
- **Sources (all keyed off one `state_dir` = `WXVAULT_STATE_DIR` env, fallback = pkg dir, same convention as siblings):**
  - **Name→wxid + relationship** ← `wxgraph`: `GraphStore(state_dir)`, `resolve_name(store, name) -> (un, candidates)`; if `un is None` return `{resolved: False, candidates}`. Relationship = `contact_profile(store, name)` (the resolved contact dict: closeness / last_ts / reciprocity / mention_partners).
  - **Facts + obligations** ← `wxfacts`: `FactStore(state_dir)`; `contact_facts(store, state_dir, name)` for grouped facts; `find_facts(store, "obligation", None, None, "active", limit)` then keep only rows whose `related_contact` matches the resolved contact (by wxid or name) → the "ta 欠我 / 我欠 ta 的未了项" list.
  - **Recent messages** ← `wxsearch`: `IndexStore(state_dir)` opens `index.sqlite`; query `SELECT sender, time, text FROM docs WHERE conversation=? ORDER BY time DESC LIMIT N` with `conversation = un` (the resolved wxid). Decoded text, deterministic, **no embedding dependency** — a brief wants the latest exchange, not semantic recall. N default = 12.
- **Graceful degradation.** Each source is independent and wrapped: a missing/empty sibling store (e.g. wxsearch not indexed yet, wxfacts never extracted) yields that field empty (`[]`/`null`) with a per-source `available: false`/note — person_brief never crashes because one index is absent. Only `wxgraph` resolution failing → `{resolved: False}` (can't identify the person at all).
- **Name-centric, ambiguity-tolerant.** Reuses wxgraph's `resolve_name` exactly (same candidates behavior the other tools already expose). No new identity join.
- **Return shape** (JSON, the MCP `_content` convention):
  ```
  {
    "name": "<query>", "resolved": true, "wxid": "<un>",
    "relationship": { ...contact_profile fields... } | null,
    "facts": { ...contact_facts grouping... } | null,
    "obligations": [ {predicate, value, related_contact, time_ref, ...}, ... ],
    "recent_messages": [ {sender, time, text}, ... ]     // newest first, capped N
  }
  ```
  unresolved: `{ "name": "<query>", "resolved": false, "candidates": [ ... ] }`.

## 3. Packaging (mirror a sibling, e.g. wxgraph)

`packages/wxperson/` with: `pyproject.toml`, `setup.py`, `wechat-cc.plugin.json` (manifest — bundled, enabled; NOT hidden), `wxperson/__init__.py`, `wxperson/_deps.py`, `wxperson/brief.py` (assembly logic — the testable core), `wxperson/server.py` (MCP stdio: `TOOLS=[person_brief]`, `_call_tool` dispatch, deps-injected store openers + `state_dir`, `main()`), `tests/`.

## 4. Non-goals (phase 2)

The daemon-side prompt routing (one line in the knowledge-orchestration section pointing at `person_brief`, and the care/agenda obligation flow-back line) is a **separate change in the wechat-cc repo**, not in this plugin — tracked in its own tiny plan. NOT here: reading `.md`; a chat_id↔wxid deterministic join; facts→.md write-back; changing tier/loading; new extraction.

## 5. Testing

- **`brief.py` assembly** (unit, with tiny fixture sqlite dbs built in a tmp `state_dir`, mirroring how wxgraph/wxfacts tests build fixtures): resolve hit → returns `resolved:true` + wxid + relationship + recent_messages ordered newest-first and capped at N; obligations filtered to the resolved contact (an obligation for a DIFFERENT contact is excluded); resolve miss → `{resolved:false, candidates}` and no other source queried; **degradation** — with wxsearch `index.sqlite` absent, `recent_messages == []` + `available:false` note and relationship still returned (no crash); same for wxfacts store absent.
- **`_deps.py`**: `import wxgraph`/`wxfacts`/`wxsearch` succeed after the ensure call (siblings resolvable from the monorepo layout).
- **server**: `tools/list` returns `person_brief`; `tools/call person_brief {name}` returns the assembled JSON via `_content`; missing `name` → `-32602`.
- Suite green; each sibling's own suite untouched.
