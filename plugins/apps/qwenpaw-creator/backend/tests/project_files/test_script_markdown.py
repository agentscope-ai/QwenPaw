# -*- coding: utf-8 -*-
"""剧本 markdown 解析/序列化的双向无损契约（方案 2.3 / 6.2）。

覆盖三种体裁样例（场次体 / 口播体 / 剪辑体）与往返快照：
块级 diff 与「Agent 重写不覆盖人工修改」都以
``parse(serialize(parse(x))) == parse(x)`` 为前提。
"""
from __future__ import annotations

import pytest

from services.project_files.script_markdown import (
    ScriptBlock,
    parse_script_markdown,
    serialize_script_blocks,
)

pytestmark = pytest.mark.unit


SCENE_SCRIPT = """\
## 场 1 · 内景 · 旧宅大厅 · 夜

烛光摇曳，林晚推开吱呀作响的木门，灰尘在光柱中翻滚。

**林晚**（低声）：这里……和二十年前一模一样。

**管家**：小姐，老爷临终前只留下这把钥匙。

> 钥匙上刻着的家徽，和母亲遗物上的一模一样。

## 场 2 · 外景 · 后山小径 · 黎明

两人沿小径疾行，远处传来犬吠。
"""

VOICEOVER_SCRIPT = """\
三秒抓住注意力：你知道吗？90% 的人第一步就选错了。

**旁白**：今天这支视频，教你三招选对第一台相机。

第一招，看传感器尺寸，别被像素数字骗了。

> 记住：底大一级压死人。

第二招，镜头群比机身更重要。
"""

EDIT_SCRIPT = """\
## 段 1 · 开场钩子

[访谈A 01:02:13–01:02:21](source-version://sv-interview-a?in=3733&out=3741)
受访者说出全片最有冲击力的一句话，直接切入。

**受访者**（哽咽）：那一天，我永远忘不了。

## 段 2 · 背景铺垫

[空镜·老街](source-version://sv-broll-street?in=120&out=480) 叠加旁白，
交代事件发生的时间与地点。
"""


def test_parse_scene_script_blocks() -> None:
    blocks = parse_script_markdown(SCENE_SCRIPT)
    kinds = [block.kind for block in blocks]
    assert kinds == [
        "scene",
        "action",
        "line",
        "line",
        "hook",
        "scene",
        "action",
    ]
    assert blocks[0].text == "场 1 · 内景 · 旧宅大厅 · 夜"
    assert blocks[2].character == "林晚"
    assert blocks[2].parenthetical == "低声"
    assert blocks[2].text == "这里……和二十年前一模一样。"
    assert blocks[3].character == "管家"
    assert blocks[3].parenthetical == ""
    assert blocks[4].kind == "hook"
    assert "家徽" in blocks[4].text


def test_parse_voiceover_script_blocks() -> None:
    blocks = parse_script_markdown(VOICEOVER_SCRIPT)
    kinds = [block.kind for block in blocks]
    assert kinds == ["action", "line", "action", "hook", "action"]
    assert blocks[1].character == "旁白"
    assert blocks[3].text == "记住：底大一级压死人。"


def test_parse_edit_script_extracts_source_refs() -> None:
    blocks = parse_script_markdown(EDIT_SCRIPT)
    refs = [ref for block in blocks for ref in block.source_refs]
    assert refs == [
        ("sv-interview-a", 3733, 3741),
        ("sv-broll-street", 120, 480),
    ]
    # 链接原文保留在块文本中，序列化不丢失。
    linked = next(block for block in blocks if block.source_refs)
    assert "source-version://sv-interview-a?in=3733&out=3741" in linked.text


@pytest.mark.parametrize(
    "sample",
    [SCENE_SCRIPT, VOICEOVER_SCRIPT, EDIT_SCRIPT],
    ids=["scene", "voiceover", "edit"],
)
def test_round_trip_is_lossless(sample: str) -> None:
    parsed = parse_script_markdown(sample)
    assert parse_script_markdown(serialize_script_blocks(parsed)) == parsed


def test_edge_blocks_normalize_and_round_trip() -> None:
    # 半角冒号输入解析成同一台词块；序列化输出全角冒号后再解析等值。
    parsed = parse_script_markdown("**林晚**: 你来了。\n")
    assert parsed == [
        ScriptBlock(kind="line", text="你来了。", character="林晚"),
    ]
    assert serialize_script_blocks(parsed) == "**林晚**：你来了。\n"
    # 多行 hook 归并为单块且往返无损。
    hooks = parse_script_markdown("> 第一行悬念\n> 第二行悬念\n")
    assert hooks == [
        ScriptBlock(kind="hook", text="第一行悬念\n第二行悬念"),
    ]
    assert parse_script_markdown(serialize_script_blocks(hooks)) == hooks
