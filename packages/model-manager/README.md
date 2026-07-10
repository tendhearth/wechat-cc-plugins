# model-manager

Tiered local-model manager for the wechat-cc enrichment plugins. Picks, resolves
(per-OS), lazily downloads, and tracks models via a global preset (`light`/`high`)
plus per-capability overrides (`asr`, `embedding`, `vlm`).

```python
from model_manager import ModelManager
mm = ModelManager(state_dir)          # state_dir = ${dataDir}
mm.set_preset("high")                 # or leave default "light"
mm.set_choice("asr", "light")         # per-capability override; "off" (or "light") only for vlm
spec = mm.resolve("asr")              # -> ModelSpec | None (None = off)
path = mm.ensure("asr", confirm=lambda mb: mb < 500)   # lazy download
mm.status()                           # selections + presence, for MCP tools
mm.prefetch()                         # download everything for current config
```

- Models live under `${state_dir}/models/<capability>/<id>/`; choices in
  `${state_dir}/models/config.json`.
- Downloads try ModelScope first, HuggingFace fallback; sha256 verified when the
  registry pins it. Zero-URL entries (e.g. macOS Apple Vision OCR) count as
  present without a download.
- No third-party runtime deps. Python 3.10+.

## Tests

Requires a Python **3.10+** interpreter (uses `X | Y` unions). With pytest available:

```bash
python3.12 -m pytest        # from packages/model-manager/
```

Keep any virtualenv **outside** this repo (or rely on the root `.gitignore`,
which excludes `venv*/`, `__pycache__/`, `*.egg-info/`).
