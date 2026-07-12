"""Shared helper: give an ML plugin its own Python 3.10+ virtualenv.

wxsearch (fastembed) and wxmedia (faster-whisper) need Python 3.10+ — their
ML deps don't run on 3.9, and the daemon commonly spawns plugins with a system
`python3` that is 3.9. So each such plugin owns a `<pluginDir>/.venv` built from
a 3.10+ interpreter (found on PATH), with its PyPI deps installed there. The
plugin's manifest then spawns `<pluginDir>/.venv/bin/python` instead of the bare
`python3`. `model_manager` itself is still resolved from source via sys.path at
runtime (it's pure-Python + 3.9-safe), so it does NOT need installing here.

POSIX layout only (`.venv/bin/python`) — these plugins read wxvault's decrypted
output, which is itself platform-specific; Windows ML support is out of scope.
"""
import os
import subprocess
import sys

MIN = (3, 10)
# Interpreters to try, best (newest) first. The bare `python3` is last: it only
# qualifies if it happens to already be >= 3.10.
CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10", "python3")


def venv_python(plugin_dir):
    """Absolute path to the plugin venv's interpreter (may not exist yet)."""
    return os.path.join(plugin_dir, ".venv", "bin", "python")


def _interp_version(path):
    try:
        out = subprocess.run(
            [path, "-c", "import sys;print('%d %d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=15)
        major, minor = (int(x) for x in out.stdout.split())
        return (major, minor)
    except Exception:
        return None


def _find_interpreter():
    """A Python >= 3.10 on PATH (or the current one if it already qualifies)."""
    if sys.version_info[:2] >= MIN:
        return sys.executable
    import shutil
    for name in CANDIDATES:
        p = shutil.which(name)
        if p and (_interp_version(p) or (0, 0)) >= MIN:
            return p
    return None


def ensure_plugin_venv(plugin_dir, deps, log=print):
    """Create `<plugin_dir>/.venv` (Python 3.10+) if absent and install `deps`
    into it (idempotent — pip is a no-op when already satisfied). Returns the
    venv interpreter path. Exits with a clear message if no 3.10+ is found."""
    vpy = venv_python(plugin_dir)
    if not os.path.exists(vpy):
        interp = _find_interpreter()
        if not interp:
            sys.exit("!! 需要 Python 3.10+（此插件的 ML 依赖不支持 3.9）。"
                     "请安装 python3.12（macOS: brew install python@3.12）后重跑 setup。")
        ver = _interp_version(interp)
        log("用 %s (%s) 创建 venv…" % (interp, "%d.%d" % ver if ver else "?"))
        subprocess.run([interp, "-m", "venv", os.path.join(plugin_dir, ".venv")], check=True)
        subprocess.run([vpy, "-m", "pip", "install", "-q", "-U", "pip"], check=True)
    if deps:
        log("安装依赖到 venv：%s" % " ".join(deps))
        r = subprocess.run([vpy, "-m", "pip", "install", *deps])
        if r.returncode != 0:
            sys.exit("!! venv 依赖安装失败：%s" % " ".join(deps))
    return vpy
