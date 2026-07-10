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
    need = []
    try:
        import pilk  # noqa: F401
    except ImportError:
        need.append("pilk")
    try:
        import model_manager  # noqa: F401
    except ImportError:
        need.append("model-manager")
    if need:
        print("安装依赖：%s" % " ".join(need))
        r = subprocess.run([sys.executable, "-m", "pip", "install", *need])
        if r.returncode != 0:
            sys.exit("!! 依赖安装失败")
    print("✓ 依赖就绪。ASR 模型在首次 voice_backfill 时按所选档懒下载（默认轻量 SenseVoice）。")


if __name__ == "__main__":
    main()
