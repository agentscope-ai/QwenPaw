"""Known credential domain aliases must collide despite independent files."""

import pytest

from wechat_w2_authclaims_suite import api, owner, registry, reserve


@pytest.mark.parametrize(
    "left,right",
    [
        ("https://wx.test/api?one=1", "https://wx.test/other?two=2"),
        ("https://wx.test:443/api", "https://wx.test/other"),
        ("http://wx.test:80/api", "http://wx.test/other"),
    ],
)
def test_real_owners_refuse_same_credential_domain_path_query_and_default_port_aliases(
    registry,
    tmp_path,
    left,
    right,
):
    a = owner(registry, tmp_path, "A")
    b = owner(registry, tmp_path, "B")
    ca = {
        "bot_token_file": str(tmp_path / "A" / "token"),
        "bot_token": "fixture-same-known-credential",
        "base_url": left,
    }
    cb = {
        "bot_token_file": str(tmp_path / "B" / "token"),
        "bot_token": "fixture-same-known-credential",
        "base_url": right,
    }
    reserve(registry, a, tmp_path, "A", ca)
    before = registry.runtime_owners.leases()
    with pytest.raises(RuntimeError):
        reserve(registry, b, tmp_path, "B", cb)
    assert registry.runtime_owners.leases() == before
    assert set(api().wechat_auth_scopes(ca, working_dir=tmp_path)) & set(
        api().wechat_auth_scopes(cb, working_dir=tmp_path)
    )
