"""Exact old issuer semantics using real RSA and controlled trusted JWKS."""
import importlib
from pathlib import Path
import sys
import time
import types

import aiohttp
import jwt
import pytest

from azure_bot_auth_support import APP, connector, rsa_material

__all__ = ["connector", "rsa_material"]
ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = (
    ROOT
    / "tests/fixtures/channel_plugins/legacy_azure_bot"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issuer",
    [
        "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/",
        "https://login.microsoftonline.com/d6d49420-f39b-4df7-a1dc-d59a935871db/v2.0",
    ],
)
async def test_exact_legacy_aad_issuer_signed_by_trusted_key_remains_usable(
    connector,
    monkeypatch,
    issuer,
):
    name = "azure_auth_snapshot_fixture"
    package = types.ModuleType(name)
    package.__path__ = [str(SNAPSHOT)]
    monkeypatch.setitem(sys.modules, name, package)
    old_module = importlib.import_module(name + ".auth")
    old = old_module.AzureBotTokenValidator(APP)
    old._jwks_client = jwt.PyJWKClient("https://login.botframework.com/keys")
    # Only the old synchronous external JWKS fetch is controlled. Real PyJWT
    # key selection, RSA verification, claims and untouched old allowlist run.
    monkeypatch.setattr(
        old._jwks_client, "fetch_data", lambda: {"keys": connector.keys}
    )
    old._jwks_fetched_at = time.time()
    header = "Bearer " + connector.token(overrides={"iss": issuer})
    assert await old.validate_auth_header(header) is True
    from qwenpaw_channel_azure_bot.auth import AzureBotTokenValidator

    async with aiohttp.ClientSession() as session:
        current = AzureBotTokenValidator(APP, session)
        assert await current.authenticate(header) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "issuer-suffix",
        "tenant-substring",
        "foreign-tenant",
        "signature",
        "audience",
        "expired",
        "future-nbf",
        "missing-issuer",
    ],
)
async def test_legacy_issuer_expansion_retains_exact_signature_and_claim_checks(
    connector,
    failure,
):
    from qwenpaw_channel_azure_bot.auth import AzureBotTokenValidator

    issuer = "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/"
    changes = {
        "issuer-suffix": {"iss": issuer + "attacker"},
        "tenant-substring": {
            "iss": "https://attacker.test/d6d49420-f39b-4df7-a1dc-d59a935871db/"
        },
        "foreign-tenant": {"iss": "https://sts.windows.net/another-tenant/"},
        "signature": {},
        "audience": {"aud": "another-app"},
        "expired": {"exp": int(time.time()) - 3600},
        "future-nbf": {"nbf": int(time.time()) + 3600},
        "missing-issuer": {"iss": None},
    }
    token = connector.token(
        overrides={"iss": issuer, **changes[failure]},
        signer=connector.other if failure == "signature" else None,
    )
    async with aiohttp.ClientSession() as session:
        validator = AzureBotTokenValidator(APP, session)
        assert await validator.authenticate("Bearer " + token) is None
