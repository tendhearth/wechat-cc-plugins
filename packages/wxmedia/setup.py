"""wxmedia setup: build a Python 3.10+ venv with pilk + faster-whisper.

faster-whisper (local ASR; pulls ctranslate2 + av) needs Python 3.10+, which the
daemon's system `python3` often isn't. So wxmedia owns `<pluginDir>/.venv`
(created here from a 3.10+ interpreter) and its manifest spawns that venv's
python. model-manager is resolved from source via sys.path at runtime (3.9-safe),
so it is not installed into the venv.
"""
import os
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxmedia setup ==")

    # model-manager is a monorepo sibling (not on PyPI) — resolve from source.
    from wxmedia._deps import ensure_model_manager, model_manager_dir
    ensure_model_manager()
    try:
        import model_manager  # noqa: F401  (3.9-safe; imports fine under the setup python)
    except ImportError:
        sys.exit("!! 找不到 model-manager（应在 %s）。确认它与 wxmedia 一同放在 monorepo/打包中。"
                 % model_manager_dir())

    # Build the 3.10+ venv with the ASR runtime. faster-whisper pulls
    # ctranslate2 + av; pilk decodes WeChat SILK voice.
    from model_manager.plugin_venv import ensure_plugin_venv
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    vpy = ensure_plugin_venv(plugin_dir, ["pilk", "faster-whisper"])
    print("✓ venv 就绪：%s" % vpy)
    print("✓ 依赖就绪。ASR 模型在首次 voice_backfill 时按所选档懒下载（默认轻量 whisper-small via faster-whisper）。")


if __name__ == "__main__":
    main()
