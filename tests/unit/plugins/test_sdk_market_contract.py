# -*- coding: utf-8 -*-
"""Public market callbacks through the real search/install services."""

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
from qwenpaw.plugins.markets import (
    MarketSpec,
    MarketResult,
    SearchPage,
    SkillBundle,
)
from qwenpaw.plugins.commands import CommandSpec, CommandResult


class Plugin:
    def register(self, ctx):
        async def search(call, query, limit, page):
            assert not hasattr(call, "agent") and not hasattr(
                call, "workspace"
            )
            ctx.storage.write_json(
                "search.json", [call.market_id, query, limit, page]
            )
            return SearchPage(
                (
                    MarketResult(
                        "sample",
                        "Sample",
                        "https://sdk-one.example.test/sample",
                        version="1.2.3",
                    ),
                ),
                True,
                3,
            )

        async def fetch(call, url, requested_version):
            ctx.storage.write_json(
                "fetch.json",
                [call.market_id, url, requested_version],
            )
            return SkillBundle(
                "market-sample",
                {
                    "SKILL.md": (
                        "---\\nname: market-sample\\n"
                        "description: Test market skill\\n"
                        "---\\nSample instructions.\\n"
                    )
                },
                url,
                requested_version or "1.2.3",
            )

        one = ctx.register_market(
            MarketSpec(
                "sdk-market-one",
                "SDK one",
                search,
                fetch,
                lambda url: url.startswith(
                    "https://sdk-one.example.test/"
                ),
            )
        )
        ctx.register_market(
            MarketSpec(
                "sdk-market-two",
                "SDK two",
                search,
                fetch,
                lambda url: url.startswith(
                    "https://sdk-two.example.test/"
                ),
            )
        )

        async def revoke(call, args):
            await one.close()
            return CommandResult()

        ctx.register_command(CommandSpec("revokemarket", revoke))


plugin = Plugin()
"""


async def test_market_search_and_bundle_use_existing_install_service(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["markets", "commands", "storage"]),
        )
        page = await host.search_market(
            "sdk-market-one",
            "needle",
            limit=2,
            page=2,
        )
        assert page.has_more is True and page.total == 3
        assert (
            page.items[0].slug == "sample" and page.items[0].version == "1.2.3"
        )
        assert ctx.storage.read_json("search.json") == [
            "sdk-market-one",
            "needle",
            2,
            2,
        ]
        name = await host.install_market_skill(
            "sdk-market-one",
            "https://sdk-one.example.test/sample",
            version="1.2.3",
            workspace_id="one",
        )
        assert name == "market-sample"
        assert "Sample instructions." in await host.read_skill(
            "market-sample/SKILL.md",
            workspace_id="one",
        )
        assert "market-sample/SKILL.md" not in await host.skill_files(
            workspace_id="two",
        )
        assert ctx.storage.read_json("fetch.json") == [
            "sdk-market-one",
            "https://sdk-one.example.test/sample",
            "1.2.3",
        ]
        assert (await host.reload("extension-contract")).ok
        assert (await host.search_market("sdk-market-one", "again")).items[
            0
        ].slug == "sample"


async def test_market_release_only_revokes_its_own_provider(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, SOURCE, ["markets", "commands", "storage"]),
        )
        await host.call_command("/revokemarket")
        with pytest.raises(SDKError):
            await host.search_market("sdk-market-one", "removed")
        assert (await host.search_market("sdk-market-two", "present")).items[
            0
        ].slug == "sample"
        await host.unload("extension-contract")
        with pytest.raises(SDKError):
            await host.search_market("sdk-market-two", "removed")
