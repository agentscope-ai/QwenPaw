"""Repacked official artifact: exact legacy AAD issuer through full Agent chain."""
from azure_bot_formal_agent_suite import (
    test_official_azure_zip_authenticated_activity_real_agent_and_cleanup as _roundtrip,
)
from azure_bot_formal_support import (
    azure_host_guard,
    azure_sdk_runtime,
    formal_connector,
    rsa_material,
)
from extension_process_suite import runtime
import pytest

__all__ = [
    "azure_host_guard",
    "azure_sdk_runtime",
    "formal_connector",
    "rsa_material",
    "runtime",
]


@pytest.mark.asyncio
async def test_repacked_official_azure_accepts_exact_aad_issuer_end_to_end(
    runtime,
    azure_sdk_runtime,
    formal_connector,
    monkeypatch,
    tmp_path,
):
    original_token = formal_connector.token
    monkeypatch.setattr(
        formal_connector,
        "token",
        lambda: original_token(
            overrides={
                "iss": "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db/"
            },
        ),
    )
    await _roundtrip(
        runtime, azure_sdk_runtime, formal_connector, monkeypatch, tmp_path
    )
