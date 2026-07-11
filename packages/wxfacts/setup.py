"""wxfacts setup: install zstandard + resolve the sibling wxgraph package."""
import subprocess
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxfacts setup ==")
    try:
        import zstandard  # noqa: F401
    except ImportError:
        print("安装依赖:zstandard")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "zstandard"])
        if r.returncode != 0:
            sys.exit("!! zstandard 安装失败")
    from wxfacts._deps import ensure_wxgraph, wxgraph_dir
    ensure_wxgraph()
    try:
        import wxgraph  # noqa: F401
    except ImportError:
        sys.exit("!! 找不到兄弟 wxgraph(应在 %s)。确认它与 wxfacts 一同放在 monorepo/打包中。" % wxgraph_dir())
    print("✓ 依赖就绪。用 extraction_batch/record_facts 由 agent 驱动抽取(先确保 wxvault 已解密 out/decrypted)。")


if __name__ == "__main__":
    main()
