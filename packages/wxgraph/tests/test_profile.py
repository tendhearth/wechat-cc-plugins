import math
from wxgraph.profile import build_profiles, percentile, DEFAULT_WEIGHTS

DAY = 86400

def _m(conv, sender, ts, ltype=1, content=None, is_group=False):
    return {"conversation": conv, "is_group": is_group, "sender_un": sender,
            "ltype": ltype, "ts": ts, "content": content}

def test_percentile_pure_python():
    assert percentile([], 0.95) == 0.0
    assert percentile([10], 0.95) == 10
    assert percentile([1, 2, 3, 4], 0.5) == 2.5      # linear interp midpoint

def test_basic_counts_and_direction():
    me, a = "me", "a"
    now = 1000 * DAY
    msgs = [
        _m(a, me, 100 * DAY), _m(a, a, 101 * DAY), _m(a, me, 900 * DAY),
        _m(a, a, 900 * DAY, ltype=34),                                   # voice
        _m(a, me, 900 * DAY, ltype=49, content="<msg><appmsg><type>2000</type></appmsg></msg>"),  # transfer out
    ]
    [p] = build_profiles(msgs, me, now)
    assert p["username"] == a
    assert p["total"] == 5 and p["sent"] == 3 and p["recv"] == 2
    assert p["first_ts"] == 100 * DAY and p["last_ts"] == 900 * DAY
    assert p["transfer_out"] == 1 and p["transfer_in"] == 0
    assert p["types"]["voice"] == 1 and p["types"]["transfer"] == 1
    assert p["active_days"] == 3            # days 100, 101, 900

def test_initiations_gap_rule():
    me, a = "me", "a"
    now = 1000 * DAY
    msgs = [
        _m(a, me, 100 * DAY),                 # initiation (first)
        _m(a, a, 100 * DAY + 60),             # reply, no gap
        _m(a, me, 100 * DAY + 7 * 3600),      # >6h after prev -> initiation
    ]
    [p] = build_profiles(msgs, me, now)
    assert p["initiations"] == 2

def test_scores_and_closeness_math():
    me, a = "me", "a"
    now = 100 * DAY
    # last msg today -> s_recency = 1.0; single contact -> P95 == its own value -> s_volume=1
    msgs = [_m(a, me, 100 * DAY), _m(a, a, 100 * DAY)]
    [p] = build_profiles(msgs, me, now)
    assert abs(p["s_recency"] - 1.0) < 1e-9
    assert abs(p["s_volume"] - 1.0) < 1e-9
    assert abs(p["s_reciprocity"] - 1.0) < 1e-9    # sent==recv==1
    # intimacy: no voice/call/transfer -> log1p(0)/log1p(max(1,P95)) = 0
    assert p["s_intimacy"] == 0.0
    w = DEFAULT_WEIGHTS
    expected = w["recency"]*1.0 + w["volume"]*1.0 + w["intimacy"]*0.0 + w["reciprocity"]*1.0
    assert abs(p["closeness"] - expected) < 1e-9

def test_shared_groups_counts_only_mutual_speakers():
    me, a, b = "me", "a", "b"
    grp = "g@chatroom"
    now = 100 * DAY
    msgs = [
        _m(a, me, 10 * DAY), _m(a, a, 11 * DAY),          # 1:1 with a
        _m(b, me, 10 * DAY),                              # 1:1 with b (b never replies)
        _m(grp, me, 12 * DAY, is_group=True),             # I spoke in group
        _m(grp, a, 12 * DAY, is_group=True),              # a spoke in group -> shared
        # b never spoke in the group
    ]
    profs = {p["username"]: p for p in build_profiles(msgs, me, now)}
    assert profs["a"]["shared_groups"] == 1
    assert profs["b"]["shared_groups"] == 0

def test_group_only_contact_not_a_profile():
    # a contact I only ever see in groups (no 1:1) is NOT a profiled node
    me = "me"
    msgs = [_m("g@chatroom", "stranger", 10 * 86400, is_group=True),
            _m("g@chatroom", me, 10 * 86400, is_group=True)]
    assert build_profiles(msgs, me, 100 * 86400) == []
