"""Known filesystem custody unit; actual helpers plus real RuntimeOwners.

Two token symlinks have different resolved targets and credentials but share
one runtime context file at their logical parent. No platform is constructed
and no authentication file content is opened by this test or custody code.
"""

import builtins
from importlib import import_module
from pathlib import Path

import pytest

from wechat_w2_authclaims_suite import owner, registry, reserve


@pytest.mark.parametrize(
    "projection",
    [
        "direct-helper",
        "qr-auth-config-helper",
        "qr-default-and-explicit-helper",
    ],
)
def test_shared_logical_context_refuses_second_real_owner_despite_distinct_symlink_targets(
    registry,
    tmp_path,
    monkeypatch,
    projection,
):
    qr_api = import_module("qwenpaw.app.channels.qrcode_sessions")
    default_projection = projection == "qr-default-and-explicit-helper"
    shared = (
        Path(qr_api.WORKING_DIR) if default_projection else tmp_path / "shared"
    )
    shared.mkdir(parents=True, exist_ok=True)
    target_a = tmp_path / "targets" / "A" / "token"
    target_b = tmp_path / "targets" / "B" / "token"
    for path, content in ((target_a, b"token-A"), (target_b, b"token-B")):
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    a_path = shared / ("wechat_bot_token" if default_projection else "a")
    b_path = shared / "b"
    a_path.symlink_to(target_a)
    b_path.symlink_to(target_b)
    context = shared / "wechat_context_tokens.json"
    context.write_bytes(b'{"history":"do-not-open"}')
    assert a_path.resolve() != b_path.resolve()
    assert (
        (a_path.parent / context.name).resolve()
        == (b_path.parent / context.name).resolve()
        == context.resolve()
    )
    before = {p: p.stat() for p in (target_a, target_b, context)}
    a = owner(registry, tmp_path, "A")
    b = owner(registry, tmp_path, "B")
    configs = [
        {"bot_token_file": str(a_path), "bot_token": "credential-A"},
        {"bot_token_file": str(b_path), "bot_token": "credential-B"},
    ]
    if default_projection:
        configs[0].pop("bot_token_file")
    original_path_open = Path.open
    original_open = builtins.open

    def path_open(path, *args, **kwargs):
        if path.resolve() in before:
            raise AssertionError("authentication file content opened")
        return original_path_open(path, *args, **kwargs)

    def file_open(file, *args, **kwargs):
        if (
            isinstance(file, (str, bytes, Path))
            and Path(file).resolve() in before
        ):
            raise AssertionError("authentication file content opened")
        return original_open(file, *args, **kwargs)

    with monkeypatch.context() as no_auth_io:
        no_auth_io.setattr(Path, "open", path_open)
        no_auth_io.setattr(builtins, "open", file_open)
        if projection != "direct-helper":
            api = qr_api
            configs = [
                api.ChannelQRCodeSessions._auth_config(
                    api._Session(
                        api.ChannelManagementScope(
                            name,
                            tmp_path / name,
                            "wechat",
                            config,
                        ),
                        lease,
                        "unit-revision-not-used-by-projection",
                        {},
                        api.monotonic() + 300,
                    )
                )
                for name, lease, config in zip(("A", "B"), (a, b), configs)
            ]
        first = reserve(registry, a, tmp_path, "A", configs[0])
        assert first
        held = registry.runtime_owners.leases()
        with pytest.raises(RuntimeError):
            reserve(registry, b, tmp_path, "B", configs[1])
        assert registry.runtime_owners.leases() == held
    assert all(p.stat() == old for p, old in before.items())
