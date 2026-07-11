"""wxmedia setup: install deps + choose ASR model tier (per-OS via model-manager)."""
import subprocess
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxmedia setup ==")
    # pilk is on PyPI — pip-install if missing
    try:
        import pilk  # noqa: F401
    except ImportError:
        print("安装依赖：pilk")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "pilk"])
        if r.returncode != 0:
            sys.exit("!! pilk 安装失败")
    # faster-whisper is on PyPI — pip-install if missing
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("安装依赖：faster-whisper（本地语音转文字，含 ctranslate2 + av）")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper"])
        if r.returncode != 0:
            sys.exit("!! faster-whisper 安装失败")
    # model-manager is a monorepo sibling (packages/model-manager), NOT on PyPI —
    # resolve it via sys.path rather than pip.
    from wxmedia._deps import ensure_model_manager, model_manager_dir
    ensure_model_manager()
    try:
        import model_manager  # noqa: F401
    except ImportError:
        sys.exit("!! 找不到 model-manager（应在 %s）。确认它与 wxmedia 一同放在 monorepo/打包中。"
                 % model_manager_dir())
    print("✓ 依赖就绪。ASR 模型在首次 voice_backfill 时按所选档懒下载（默认轻量 SenseVoice）。")


if __name__ == "__main__":
    main()
