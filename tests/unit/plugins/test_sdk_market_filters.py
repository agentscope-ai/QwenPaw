# -*- coding: utf-8 -*-
"""Language/category isolation through the actual host market service."""

import asyncio

import pytest

from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin

SOURCE = """
from qwenpaw.plugins.markets import MarketSpec, MarketResult, SearchPage, SkillBundle
class Plugin:
    def register(self, ctx):
        async def search(call, query, limit, page):
            await call.resources.run_sync(lambda: None)
            return SearchPage((MarketResult(
                f"{call.lang}:{call.category}:{query}:{limit}:{page}",
                "Filtered", "https://example.test/skill",
            ),), page < 3, 30)
        def fetch(call, url, version):
            return SkillBundle("filtered", {"SKILL.md": "instructions"}, url)
        ctx.register_market(MarketSpec("filter-probe", "Filters", search, fetch, lambda url: False))
plugin = Plugin()
"""


async def test_market_filters_do_not_cross_concurrent_calls(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, SOURCE, ["markets", "resources"]),
        )
        chinese, english = await asyncio.gather(
            host.search_market(
                "filter-probe",
                "",
                lang="zh",
                category="engineering-development",
                page=2,
                limit=5,
            ),
            host.search_market(
                "filter-probe",
                "needle",
                lang="en",
                category="custom-category",
                page=3,
                limit=10,
            ),
        )
        assert chinese.items[0].slug == "zh:engineering-development::5:2"
        assert english.items[0].slug == "en:custom-category:needle:10:3"
        assert chinese.has_more and not english.has_more
        assert chinese.total == english.total == 30
        assert (await host.reload("extension-contract")).ok
        default = await host.search_market("filter-probe", "default")
        assert default.items[0].slug == "en:None:default:10:1"
        assert (await host.unload("extension-contract")).clean
        host.assert_quiescent("extension-contract")


async def test_native_install_cancel_waits_for_fetch_cleanup(
    tmp_path,
    sdk_component,
):
    from qwenpaw.agents.skill_system.hub import install_skill_from_hub
    from qwenpaw.exceptions import SkillImportCancelled
    from qwenpaw.plugins.markets import MarketSpec, SearchPage

    started, cancel, cleaning, release = (asyncio.Event() for _ in range(4))

    async def search(call, query, limit, page):
        return SearchPage(())

    async def fetch(call, url, version):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    def declare(ctx):
        ctx.register_market(
            MarketSpec(
                "cancel-contract",
                "Cancel",
                search,
                fetch,
                lambda url: True,
            ),
        )

    async with sdk_component(declare, capabilities=("markets",)) as (
        host,
        ctx,
    ):
        workspace = tmp_path / "workspace"
        task = asyncio.create_task(
            install_skill_from_hub(
                workspace_dir=workspace,
                provider_key="cancel-contract",
                bundle_url="https://example.test/skill",
                cancel_checker=cancel.is_set,
            ),
        )
        try:
            await asyncio.wait_for(started.wait(), 3)
            cancel.set()
            await asyncio.wait_for(cleaning.wait(), 3)
            assert not task.done()
            release.set()
            with pytest.raises(SkillImportCancelled):
                await asyncio.wait_for(task, 3)
            assert not ctx.resources.snapshot()["resources"]
            assert not workspace.exists()
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
