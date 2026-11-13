# -*- coding: utf-8 -*-
"""Real Chromium journey through the public Browser tool."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from agentscope.message import ToolResultState

from qwenpaw.agents.tools.browser import browser
from qwenpaw.browser.execution import kernel
from qwenpaw.browser.execution.kernel import get_default_kernel_manager
from qwenpaw.browser import tool_entrypoint


@pytest_asyncio.fixture(autouse=True)
async def reset_kernel() -> AsyncGenerator[None, None]:
    yield
    manager = get_default_kernel_manager()
    await manager.reset_session(
        tool_entrypoint.derive_workspace_id(
            tool_entrypoint.get_current_workspace_dir(),
        ),
        "default",
    )
    await manager.discard_all_workers()
    kernel._MANAGER = None  # pylint: disable=protected-access


@pytest.mark.p1
async def test_browser_tool_drives_a_real_page(fixture_url: str) -> None:
    code = (
        "browser = await Browser.connect(identity='guest')\n"
        f"page = await browser.open({fixture_url!r})\n"
        "button = page.get_by_role('button', name='登录')\n"
        "await button.click()\n"
        "result = (await page.snapshot()).text\n"
        "await browser.close()\n"
        "result"
    )

    result = await browser(code)

    assert result.state is ToolResultState.SUCCESS, result.content[0].text
    assert "Logged in" in result.content[0].text
