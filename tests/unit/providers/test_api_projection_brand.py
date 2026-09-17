# -*- coding: utf-8 -*-
from qwenpaw.providers.api_projection import project_provider_info
from qwenpaw.providers.provider import ProviderInfo


def test_embedded_provider_uses_public_product_name_without_mutating_source():
    provider = ProviderInfo(
        id="qwenpaw-local",
        name="QwenPaw Local",
        is_local=True,
    )

    projected = project_provider_info(provider)

    assert projected.name == "WeldonAgent Local"
    assert provider.name == "QwenPaw Local"
