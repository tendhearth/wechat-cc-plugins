"""wxsearch setup: build a Python 3.10+ venv with numpy + fastembed.

fastembed (the local embedding runtime; bundles onnxruntime + tokenizers) needs
Python 3.10+, which the daemon's system `python3` often isn't. So wxsearch owns
`<pluginDir>/.venv` (created here from a 3.10+ interpreter) and its manifest
spawns that venv's python. model-manager is resolved from source via sys.path at
runtime (3.9-safe), so it is not installed into the venv. See
docs/specs/2026-07-10-tiered-model-manager-design.md §5.7.
"""
import os
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxsearch setup ==")
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # default; daemon env HF_ENDPOINT overrides

    # model-manager is a monorepo sibling (not on PyPI) — resolve from source.
    from wxsearch._deps import ensure_model_manager, model_manager_dir
    ensure_model_manager()
    try:
        import model_manager  # noqa: F401  (3.9-safe; imports fine under the setup python)
    except ImportError:
        sys.exit("!! 找不到 model-manager（应在 %s）。确认它与 wxsearch 一同放在 monorepo/打包中。"
                 % model_manager_dir())

    # Build the 3.10+ venv with the embedding runtime. fastembed pulls
    # onnxruntime + tokenizers, so numpy + fastembed covers every current
    # embedding tier (all runtime == "onnx").
    from model_manager.plugin_venv import ensure_plugin_venv
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    vpy = ensure_plugin_venv(plugin_dir, ["numpy", "fastembed"])
    print("✓ venv 就绪：%s" % vpy)
    print("✓ 依赖就绪。跑 index_update 建索引；embedding 模型首次索引时按档懒下载（默认 bge-small-zh）。")


if __name__ == "__main__":
    main()
