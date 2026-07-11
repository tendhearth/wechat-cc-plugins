"""wxperson setup: resolve the sibling wxgraph/wxfacts/wxsearch packages.

wxperson has no PyPI dependencies of its own — it only reads the stores the
siblings already build (via stdlib sqlite3). Setup just verifies the siblings
are resolvable so person_brief can assemble from them.
"""
import sys


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("== wxperson setup ==")
    from wxperson._deps import ensure_siblings, sibling_dir
    ensure_siblings()
    missing = []
    for name in ("wxgraph", "wxfacts", "wxsearch"):
        try:
            __import__(name)
        except ImportError:
            missing.append("%s(应在 %s)" % (name, sibling_dir(name)))
    if missing:
        sys.exit("!! 找不到兄弟插件:%s。确认它们与 wxperson 一同放在 monorepo/打包中。"
                 % ", ".join(missing))
    print("✓ 兄弟就绪(wxgraph/wxfacts/wxsearch)。用 person_brief(名字) 拿某人的统一简报。")


if __name__ == "__main__":
    main()
