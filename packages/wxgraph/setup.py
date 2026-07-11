"""wxgraph setup: install zstandard (the only dependency)."""
import subprocess
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxgraph setup ==")
    try:
        import zstandard  # noqa: F401
    except ImportError:
        print("安装依赖:zstandard")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "zstandard"])
        if r.returncode != 0:
            sys.exit("!! zstandard 安装失败")
    print("✓ 依赖就绪。跑 rebuild 建关系图(先确保 wxvault 已解密 out/decrypted)。")


if __name__ == "__main__":
    main()
