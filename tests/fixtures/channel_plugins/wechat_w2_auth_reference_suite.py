"""Known config references use real files/readers, before any other launch."""

import pytest

from qwenpaw.config.config import load_agent_config, save_agent_config
from qwenpaw.plugins.ownership import RuntimeKey
from wechat_w2_authclaims_suite import owner, registry, reserve
from wechat_w2_config_support import write_profiles


@pytest.mark.parametrize(
    "reference", ["explicit-path", "enabled", "reserved-runtime"]
)
def test_configured_or_reserved_peer_claims_default_or_explicit_auth_before_launch(
    registry,
    tmp_path,
    monkeypatch,
    reference,
):
    _, paths = write_profiles(tmp_path, monkeypatch, "wechat", {})
    a = owner(registry, tmp_path, "A")
    candidate = {"enabled": True}
    peer = load_agent_config("B")
    if reference == "explicit-path":
        path = str(tmp_path / "shared" / "token")
        peer.channels.wechat.bot_token_file = path
        candidate = {"bot_token_file": path}
    elif reference == "enabled":
        peer.channels.wechat.enabled = True
    else:
        registry.runtime_owners.reserve(
            "wechat",
            RuntimeKey("channel", "wechat", str(paths["B"].resolve())),
            tmp_path / "source",
            instance_id="B-constructor-not-started",
        )
    save_agent_config("B", peer)
    before = registry.runtime_owners.leases()
    with pytest.raises(RuntimeError):
        reserve(registry, a, tmp_path, "A", candidate)
    assert registry.runtime_owners.leases() == before
