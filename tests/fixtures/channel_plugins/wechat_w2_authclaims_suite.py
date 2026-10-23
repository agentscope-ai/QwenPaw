"""W2 auth custody units: actual filesystem, PluginRegistry and RuntimeOwners.

Unit stop adapters represent non-process owners, with explicit receipt control.
These are not WeChat runtime/Loader/management integration claims.
"""

from importlib import import_module
from pathlib import Path

import pytest

from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
from qwenpaw.plugins.registry import PluginRegistry


def api():
    return import_module("qwenpaw.app.channels.wechat_auth_custody")


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    return PluginRegistry()


def owner(registry, tmp_path, name, calls=None, receipt=None):
    lease = registry.runtime_owners.reserve(
        "wechat",
        RuntimeKey("channel", "wechat", name),
        tmp_path / "source",
        instance_id=name,
    )

    async def stop():
        if calls is not None:
            calls.append(lease)
        return receipt[0] if receipt else RuntimeStopReceipt(True)

    registry.runtime_owners.attach(lease, stop)
    return lease


def reserve(registry, lease, tmp_path, name, config):
    return api().reserve_wechat_auth(
        registry,
        owner=lease,
        workspace_id=name,
        workspace_dir=tmp_path / name,
        config=config,
    )


def test_untouched_default_model_does_not_claim_auth(registry, tmp_path):
    lease = owner(registry, tmp_path, "A")
    assert reserve(registry, lease, tmp_path, "A", {}) == ()
    assert registry.runtime_owners.leases() == (lease,)


def test_explicit_paths_have_hashed_host_claims_and_independent_dirs_coexist(
    registry,
    tmp_path,
):
    a = owner(registry, tmp_path, "A")
    b = owner(registry, tmp_path, "B")
    ca = reserve(
        registry,
        a,
        tmp_path,
        "A",
        {
            "bot_token_file": str(tmp_path / "A" / "token"),
        },
    )
    cb = reserve(
        registry,
        b,
        tmp_path,
        "B",
        {
            "bot_token_file": str(tmp_path / "B" / "token"),
        },
    )
    assert ca and cb and set(ca).isdisjoint(cb)
    for claim in (*ca, *cb):
        assert claim.key.kind == "wechat_auth"
        assert claim.key.scope_id == "host"
        assert str(tmp_path) not in claim.key.name
        assert claim.code_root == a.code_root


@pytest.mark.parametrize(
    "collision", ["same-token", "same-context", "credential"]
)
def test_known_collision_refuses_without_stopping_or_stealing_existing_owner(
    registry,
    tmp_path,
    collision,
):
    calls = []
    a = owner(registry, tmp_path, "A", calls)
    b = owner(registry, tmp_path, "B", calls)
    ca = {"bot_token_file": str(tmp_path / "A" / "token")}
    cb = {"bot_token_file": str(tmp_path / "B" / "token")}
    if collision == "same-token":
        cb["bot_token_file"] = ca["bot_token_file"]
    elif collision == "same-context":
        cb["bot_token_file"] = str(tmp_path / "A" / "another-token")
    else:
        ca.update(bot_token="fixture-credential", base_url="https://wx.test/")
        cb.update(bot_token="fixture-credential", base_url="https://wx.test")
    claims = reserve(registry, a, tmp_path, "A", ca)
    before = registry.runtime_owners.leases()
    with pytest.raises((RuntimeError, ValueError)):
        reserve(registry, b, tmp_path, "B", cb)
    assert registry.runtime_owners.leases() == before
    assert all(c in registry.runtime_owners.leases() for c in claims)
    assert calls == []


@pytest.mark.parametrize(
    "receipt",
    [
        RuntimeStopReceipt(False),
        RuntimeStopReceipt(True, exited=False),
        RuntimeStopReceipt(True, residual=("fixture-child",)),
    ],
)
def test_incomplete_stop_receipt_cannot_release_auth_claims(
    registry,
    tmp_path,
    receipt,
):
    lease = owner(registry, tmp_path, "A")
    claims = reserve(
        registry,
        lease,
        tmp_path,
        "A",
        {
            "bot_token_file": str(tmp_path / "A" / "token"),
        },
    )
    api().release_wechat_auth(registry, claims, receipt)
    assert set(claims).issubset(registry.runtime_owners.leases())
    api().release_wechat_auth(registry, claims, RuntimeStopReceipt(True))
    assert set(claims).isdisjoint(registry.runtime_owners.leases())
    assert lease in registry.runtime_owners.leases()


@pytest.mark.asyncio
async def test_claim_stop_adapter_targets_exact_owner_and_retains_failed_proof(
    registry,
    tmp_path,
):
    calls = []
    receipt = [RuntimeStopReceipt(False, exited=False)]
    a = owner(registry, tmp_path, "A", calls, receipt)
    b = owner(registry, tmp_path, "B", calls)
    claims = reserve(
        registry,
        a,
        tmp_path,
        "A",
        {
            "bot_token_file": str(tmp_path / "A" / "token"),
        },
    )
    result = await registry.runtime_owners.stop(claims[0])
    assert not result.stopped and calls == [a]
    assert a in registry.runtime_owners.leases()
    assert b in registry.runtime_owners.leases()
    assert set(claims).issubset(registry.runtime_owners.leases())
    receipt[0] = RuntimeStopReceipt(True)
    result = await registry.runtime_owners.stop(claims[0])
    assert result.stopped and calls == [a, a]
    api().release_wechat_auth(registry, claims, result)
    assert set(claims).isdisjoint(registry.runtime_owners.leases())
    assert a not in registry.runtime_owners.leases()
    assert b in registry.runtime_owners.leases()


def test_symlink_claim_resolution_does_not_read_or_mutate_auth_files(
    registry,
    tmp_path,
    monkeypatch,
):
    physical = tmp_path / "physical"
    physical.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    token = physical / "token"
    context = physical / "wechat_context_tokens.json"
    token.write_bytes(b"old-token-must-stay")
    context.write_bytes(b'{"actor":"old-context-must-stay"}')
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (token, context)
    }
    a = owner(registry, tmp_path, "A")
    original = Path.read_text

    def guard(path, *args, **kwargs):
        if path.resolve() in before:
            raise AssertionError("auth content read during HTTP custody")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", guard)
        scopes = api().wechat_auth_scopes(
            {"bot_token_file": str(alias / "token")},
            working_dir=tmp_path,
        )
        assert scopes == api().wechat_auth_scopes(
            {"bot_token_file": str(token)},
            working_dir=tmp_path,
        )
        reserve(
            registry,
            a,
            tmp_path,
            "A",
            {
                "bot_token_file": str(alias / "token"),
            },
        )
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before
    }
