"""wxsearch setup: install numpy + resolve sibling model-manager + install the
current embedding tier's runtime deps ("只装当前 config 需要的" — see
docs/specs/2026-07-10-tiered-model-manager-design.md §5.7)."""
import os
import subprocess
import sys


def _pip_install(*packages):
    r = subprocess.run([sys.executable, "-m", "pip", "install", *packages])
    if r.returncode != 0:
        sys.exit("!! %s 安装失败" % " ".join(packages))


def _ensure_embedding_runtime_deps():
    """Resolve the currently-configured embedding model and install its
    runtime's deps. Every embedding tier today is runtime=="onnx" (bge-small-zh
    light / jina-embeddings-v2-base-zh high), so this installs onnxruntime + tokenizers — but it
    goes through resolve() rather than hardcoding, so a future non-onnx tier
    (or an "off" override, if one is ever added for embedding) doesn't drag
    them in unnecessarily."""
    from model_manager import ModelManager
    state_dir = os.environ.get("WXVAULT_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    spec = ModelManager(state_dir).resolve("embedding")
    if spec is None or spec.runtime != "onnx":
        return
    missing = []
    for mod, pkg in (("onnxruntime", "onnxruntime"), ("tokenizers", "tokenizers")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("安装依赖：%s（embedding 档 %s，runtime=onnx）" % (" ".join(missing), spec.id))
        _pip_install(*missing)


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
        _pip_install("numpy")
    try:
        import fastembed  # noqa: F401
    except ImportError:
        print("安装依赖：fastembed（本地嵌入运行时，含 onnxruntime）")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "fastembed"])
        if r.returncode != 0:
            sys.exit("!! fastembed 安装失败")
    from wxsearch._deps import ensure_model_manager, model_manager_dir
    ensure_model_manager()
    try:
        import model_manager  # noqa: F401
    except ImportError:
        sys.exit("!! 找不到 model-manager（应在 %s）。确认它与 wxsearch 一同放在 monorepo/打包中。"
                 % model_manager_dir())
    try:
        _ensure_embedding_runtime_deps()
    except Exception as e:
        sys.exit("!! embedding 运行时依赖检查/安装失败：%s" % e)
    print("✓ 依赖就绪。跑 index_update 建索引；embedding 模型首次索引时按档懒下载（默认 bge-small-zh）。")


if __name__ == "__main__":
    main()
