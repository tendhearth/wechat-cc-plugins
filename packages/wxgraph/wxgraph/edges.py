"""Extract strong-signal contact->contact mention/quote edges from group messages."""
import re
from collections import defaultdict


def _targets(content, display_to_un):
    """Yield resolved target usernames from one group message's content."""
    out = []
    m = re.search(r"<atuserlist>(.*?)</atuserlist>", content or "", re.S)
    if m:
        raw = m.group(1).replace("<![CDATA[", "").replace("]]>", "")
        for u in re.split(r"[,\s]+", raw.strip()):
            if u:
                out.append(u)
    rm = re.search(r"<refermsg>(.*?)</refermsg>", content or "", re.S)
    if rm:
        block = rm.group(1)
        cu = re.search(r"<chatusr>(.*?)</chatusr>", block, re.S)
        if cu and cu.group(1).strip():
            out.append(cu.group(1).strip())
        else:
            dn = re.search(r"<displayname>(.*?)</displayname>", block, re.S)
            if dn and dn.group(1).strip():
                mapped = (display_to_un or {}).get(dn.group(1).strip())
                if mapped:
                    out.append(mapped)
    return out


def build_mention_edges(messages, owner, display_to_un=None):
    counts = defaultdict(int)
    for msg in messages:
        if not msg["is_group"] or not msg["content"]:
            continue
        a = msg["sender_un"]
        if not a or a == owner:
            continue
        for b in _targets(msg["content"], display_to_un):
            if not b or b == owner or b == a or b.endswith("@chatroom"):
                continue
            counts[(a, b)] += 1
    return [(a, b, w) for (a, b), w in counts.items()]
