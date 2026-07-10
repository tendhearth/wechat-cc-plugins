"""wxsearch setup: install numpy + resolve sibling model-manager."""
import subprocess
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxsearch setup ==")
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("安装依赖：numpy")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "numpy"])
        if r.returncode != 0:
            sys.exit("!! numpy 安装失败")
    from wxsearch._deps import ensure_model_manager, model_manager_dir
    ensure_model_manager()
    try:
        import model_manager  # noqa: F401
    except ImportError:
        sys.exit("!! 找不到 model-manager（应在 %s）。确认它与 wxsearch 一同放在 monorepo/打包中。"
                 % model_manager_dir())
    print("✓ 依赖就绪。跑 index_update 建索引；embedding 模型首次索引时按档懒下载（默认 bge-small-zh）。")


if __name__ == "__main__":
    main()
