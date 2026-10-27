# -*- coding: utf-8 -*-
"""Author-facing SDK module tables must be accepted by the SDK checker."""

import re
from pathlib import Path

import pytest

from .sdk_author_fixture import make_plugin

pytestmark = pytest.mark.p2


@pytest.mark.parametrize(
    "language, heading",
    [("zh", "能力与公开模块"), ("en", "Public capabilities")],
)
def test_documented_sdk_entries_pass_author_check(tmp_path, language, heading):
    from qwenpaw.plugins.compliance import PUBLIC_API, check_plugin

    page = Path(__file__).resolve().parents[3] / "website/public/docs"
    text = (page / f"plugins.{language}.md").read_text(encoding="utf-8")
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    entries = [
        entry
        for line in section.splitlines()
        if line.startswith("|")
        for entry in re.findall(r"`([^`]+)`", line.split("|")[-2])
    ]
    assert entries
    imports = []
    for entry in entries:
        if entry in PUBLIC_API["qwenpaw.plugins"]:
            imports.append(f"from qwenpaw.plugins import {entry}")
        else:
            module = (
                entry
                if entry.startswith("qwenpaw.")
                else (f"qwenpaw.plugins.{entry}")
            )
            imports.append(f"import {module}")
    source = (
        "\n".join(imports) + "\nclass Plugin:\n    pass\nplugin = Plugin()\n"
    )
    report = check_plugin(make_plugin(tmp_path, source, []))
    assert report.ok, report.findings


async def test_documented_counter_preserves_concurrent_updates(tmp_path):
    import asyncio
    from qwenpaw.plugins.testing import PluginTestHost

    page = (
        Path(__file__).resolve().parents[3]
        / "website/public/docs/plugins.zh.md"
    )
    section = page.read_text(encoding="utf-8").split("### 最小工具\n", 1)[1]
    source = section.split("```python\n", 1)[1].split("```", 1)[0]
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["tools", "storage"]))
        results = await asyncio.gather(
            *(
                host.call_tool("hello_sdk", {"name": "author"})
                for _ in range(20)
            ),
        )
        texts = [
            "".join(block.text for block in result.content)
            for result in results
        ]
        assert set(texts) == {
            f"Hello author ({count})" for count in range(1, 21)
        }
        assert (await host.reload("extension-contract")).ok
        retained = await host.call_tool("hello_sdk", {"name": "retained"})
        assert "".join(block.text for block in retained.content) == (
            "Hello retained (21)"
        )
