"""Aggregate messages into per-contact profiles with transparent sub-scores."""
import math
from collections import defaultdict

from .source import classify_type

DAY = 86400
GAP = 6 * 3600            # >6h since previous message => a fresh initiation
TAU_DAYS = 90.0

DEFAULT_WEIGHTS = {"recency": 0.35, "volume": 0.30, "intimacy": 0.20, "reciprocity": 0.15}


def percentile(values, p):
    s = sorted(values)
    if not s:
        return 0.0
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    return s[f] * (c - k) + s[c] * (k - f)


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def build_profiles(messages, owner, now, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    # group speaker sets, for shared_groups
    group_speakers = defaultdict(set)
    # per 1:1 contact accumulator
    acc = {}
    for m in messages:
        if m["is_group"]:
            if m["sender_un"]:
                group_speakers[m["conversation"]].add(m["sender_un"])
            continue
        contact = m["conversation"]
        if contact == owner:            # self-chat / filehelper edge: skip
            continue
        a = acc.get(contact)
        if a is None:
            a = acc[contact] = {"msgs": [], "types": defaultdict(int),
                                "sent": 0, "recv": 0, "transfer_in": 0, "transfer_out": 0}
        a["msgs"].append(m)
        if m["sender_un"] == owner:
            a["sent"] += 1
        else:
            a["recv"] += 1
        tag = classify_type(m["ltype"], m["content"])
        a["types"][tag] += 1
        if tag in ("transfer", "redpacket"):
            if m["sender_un"] == owner:
                a["transfer_out"] += 1
            else:
                a["transfer_in"] += 1

    # groups where BOTH owner and the contact spoke
    def shared_groups(contact):
        return sum(1 for spk in group_speakers.values() if owner in spk and contact in spk)

    rows = []
    for contact, a in acc.items():
        msgs = sorted(a["msgs"], key=lambda x: x["ts"])
        first_ts, last_ts = msgs[0]["ts"], msgs[-1]["ts"]
        active_days = len({m["ts"] // DAY for m in msgs})
        initiations = 0
        prev_ts = None
        for m in msgs:
            if m["sender_un"] == owner and (prev_ts is None or m["ts"] - prev_ts > GAP):
                initiations += 1
            prev_ts = m["ts"]
        total = len(msgs)
        n_int = a["types"].get("voice", 0) + a["types"].get("call", 0) + a["transfer_in"] + a["transfer_out"]
        rows.append({
            "username": contact, "total": total, "sent": a["sent"], "recv": a["recv"],
            "first_ts": first_ts, "last_ts": last_ts,
            "known_days": max(0, (now - first_ts) // DAY),
            "active_days": active_days, "initiations": initiations,
            "transfer_in": a["transfer_in"], "transfer_out": a["transfer_out"],
            "shared_groups": shared_groups(contact),
            "types": dict(a["types"]),
            "_n_int": n_int,
        })

    # normalization corpora (P95, floored at 1.0)
    p95_total = max(1.0, percentile([r["total"] for r in rows], 0.95))
    p95_int = max(1.0, percentile([r["_n_int"] for r in rows], 0.95))
    for r in rows:
        s_volume = _clamp01(math.log1p(r["total"]) / math.log1p(p95_total))
        days_since = max(0, (now - r["last_ts"])) / DAY
        s_recency = _clamp01(math.exp(-days_since / TAU_DAYS))
        denom = r["sent"] + r["recv"]
        s_recip = 1.0 - abs(r["sent"] - r["recv"]) / denom if denom else 0.0
        s_intim = _clamp01(math.log1p(r["_n_int"]) / math.log1p(p95_int))
        closeness = (weights["recency"] * s_recency + weights["volume"] * s_volume +
                     weights["intimacy"] * s_intim + weights["reciprocity"] * s_recip)
        r["s_volume"] = s_volume
        r["s_recency"] = s_recency
        r["s_reciprocity"] = s_recip
        r["s_intimacy"] = s_intim
        r["closeness"] = closeness
        del r["_n_int"]
    return rows
