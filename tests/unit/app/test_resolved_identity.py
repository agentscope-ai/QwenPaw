from qwenpaw.app.auth import ResolvedIdentity


def test_resolved_identity_defaults_roles_to_empty_list():
    ident = ResolvedIdentity(sender_id="u@x.io")
    assert ident.sender_id == "u@x.io"
    assert ident.roles == []


def test_resolved_identity_carries_roles():
    ident = ResolvedIdentity(sender_id="u@x.io", roles=["admin"])
    assert ident.roles == ["admin"]


def test_resolved_identity_mutable_default_is_independent():
    first = ResolvedIdentity(sender_id="a")
    second = ResolvedIdentity(sender_id="b")
    first.roles.append("admin")
    assert second.roles == []
