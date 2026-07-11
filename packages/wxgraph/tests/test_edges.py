from wxgraph.edges import build_mention_edges

def _g(sender, content):
    return {"conversation": "room@chatroom", "is_group": True, "sender_un": sender,
            "ltype": 49, "ts": 1, "content": content}

def test_atuserlist_wxids_resolve_directly():
    msgs = [
        {"conversation": "room@chatroom", "is_group": True, "sender_un": "a",
         "ltype": 1, "ts": 1, "content": "<msgsource><atuserlist>wxid_b,wxid_c</atuserlist></msgsource>"},
    ]
    edges = build_mention_edges(msgs, owner="me")
    assert sorted(edges) == [("a", "wxid_b", 1), ("a", "wxid_c", 1)]

def test_refermsg_chatusr_preferred():
    msgs = [_g("a", "<msg><appmsg><refermsg><chatusr>wxid_b</chatusr>"
                    "<displayname>Bob</displayname></refermsg></appmsg></msg>")]
    assert build_mention_edges(msgs, owner="me") == [("a", "wxid_b", 1)]

def test_refermsg_displayname_mapped_when_no_chatusr():
    msgs = [_g("a", "<msg><appmsg><refermsg><displayname>Bob</displayname></refermsg></appmsg></msg>")]
    edges = build_mention_edges(msgs, owner="me", display_to_un={"Bob": "wxid_b"})
    assert edges == [("a", "wxid_b", 1)]

def test_drops_owner_self_and_unresolved():
    msgs = [
        _g("a", "<msgsource><atuserlist>me</atuserlist></msgsource>"),           # -> owner, drop
        _g("a", "<msgsource><atuserlist>a</atuserlist></msgsource>"),            # -> self, drop
        _g("a", "<msg><appmsg><refermsg><displayname>Ghost</displayname></refermsg></appmsg></msg>"),  # unmapped, drop
    ]
    assert build_mention_edges(msgs, owner="me", display_to_un={}) == []

def test_weight_accumulates_directed():
    msgs = [_g("a", "<msgsource><atuserlist>wxid_b</atuserlist></msgsource>"),
            _g("a", "<msgsource><atuserlist>wxid_b</atuserlist></msgsource>"),
            _g("wxid_b", "<msgsource><atuserlist>a</atuserlist></msgsource>")]
    edges = dict(((a, b), w) for a, b, w in build_mention_edges(msgs, owner="me"))
    assert edges[("a", "wxid_b")] == 2
    assert edges[("wxid_b", "a")] == 1
