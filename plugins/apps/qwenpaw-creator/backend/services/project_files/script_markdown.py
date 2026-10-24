# -*- coding: utf-8 -*-
"""剧本 markdown 的成文规范：块级解析与序列化（双向无损）。

`timeline_script` artifact 的内容是**约定格式 markdown**（方案 2.3）：
场次体 / 口播体 / 剪辑体三种体裁共用同一套块类型，体裁由内容形态
自然体现，不入库为枚举。块类型：

- ``scene``：场次头，``## 场 N · 内景 · 旧宅大厅 · 夜``；
- ``line``：台词，``**林晚**（低声）：台词正文``（括注可省略）；
- ``hook``：钩子/悬念，markdown 引用块 ``> ...``；
- ``action``：普通段落 = 动作描述 / 口播 segment / 剪辑段落。

素材时间码引用（剪辑体裁）内联在块文本中，链接约定
``[访谈A 01:02:13–01:02:21](source-version://<id>?in=3733&out=3741)``；
解析时同时抽取为 ``source_refs``，序列化时保留原始链接文本，
因此 ``parse(serialize(parse(x))) == parse(x)`` 恒成立——这是
「人工 contentEditable 编辑 → 块级 diff → Agent 重写不覆盖人工修改」
的前提（方案第 6.2 条）。前端 ``lib/scriptMarkdown.ts`` 与本模块
同构，规则变更必须双端同步。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ScriptBlockKind = Literal["scene", "action", "line", "hook"]

# 台词行：**角色**（括注）：台词。括注可省略；冒号接受全角/半角。
_LINE_PATTERN = re.compile(
    r"^\*\*(?P<character>[^*\n]+)\*\*"
    r"(?:（(?P<parenthetical>[^）\n]*)）)?"
    r"\s*[：:]\s?(?P<text>.*)$",
)

# 素材时间码链接：[label](source-version://<id>?in=<tick>&out=<tick>)。
_SOURCE_REF_PATTERN = re.compile(
    r"\[[^\]\n]*\]\("
    r"source-version://(?P<version_id>[^)?\s]+)"
    r"\?in=(?P<in_tick>\d+)&out=(?P<out_tick>\d+)"
    r"\)",
)


@dataclass(frozen=True, slots=True)
class ScriptBlock:
    """一个剧本块：解析与序列化的最小单位。"""

    kind: ScriptBlockKind
    text: str
    character: str = ""
    parenthetical: str = ""
    # (source version id, in tick, out tick) —— 从块文本中的
    # source-version:// 链接抽取，文本本身保留链接原文。
    source_refs: list[tuple[str, int, int]] = field(default_factory=list)


def _extract_source_refs(text: str) -> list[tuple[str, int, int]]:
    return [
        (
            match.group("version_id"),
            int(match.group("in_tick")),
            int(match.group("out_tick")),
        )
        for match in _SOURCE_REF_PATTERN.finditer(text)
    ]


def _block(
    kind: ScriptBlockKind,
    text: str,
    *,
    character: str = "",
    parenthetical: str = "",
) -> ScriptBlock:
    return ScriptBlock(
        kind=kind,
        text=text,
        character=character,
        parenthetical=parenthetical,
        source_refs=_extract_source_refs(text),
    )


def parse_script_markdown(text: str) -> list[ScriptBlock]:
    """把约定格式 markdown 解析为块列表。

    规则（与 serialize_script_blocks 互逆）：
    - ``## `` 开头的行是场次头，独立成块（存储时去掉 ``## `` 前缀）；
    - 连续 ``>`` 引用行合并为一个 hook 块（去掉引用前缀，行间以换行连接）；
    - 匹配台词格式的行独立成 line 块；
    - 其余连续非空行合并为一个 action 段落；空行是块边界。
    """

    blocks: list[ScriptBlock] = []
    action_lines: list[str] = []
    hook_lines: list[str] = []

    def flush_action() -> None:
        if action_lines:
            blocks.append(_block("action", "\n".join(action_lines)))
            action_lines.clear()

    def flush_hook() -> None:
        if hook_lines:
            blocks.append(_block("hook", "\n".join(hook_lines)))
            hook_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_action()
            flush_hook()
            continue
        if stripped.startswith("## "):
            flush_action()
            flush_hook()
            blocks.append(_block("scene", stripped[3:].strip()))
            continue
        if stripped.startswith(">"):
            flush_action()
            hook_lines.append(stripped[1:].lstrip())
            continue
        flush_hook()
        matched = _LINE_PATTERN.match(stripped)
        if matched is not None:
            flush_action()
            blocks.append(
                _block(
                    "line",
                    matched.group("text").strip(),
                    character=matched.group("character").strip(),
                    parenthetical=(
                        matched.group("parenthetical") or ""
                    ).strip(),
                ),
            )
            continue
        action_lines.append(stripped)
    flush_action()
    flush_hook()
    return blocks


def serialize_script_blocks(blocks: list[ScriptBlock]) -> str:
    """把块列表序列化回约定格式 markdown（parse 的逆操作）。"""

    chunks: list[str] = []
    for block in blocks:
        if block.kind == "scene":
            chunks.append(f"## {block.text}")
        elif block.kind == "hook":
            chunks.append(
                "\n".join(
                    f"> {line}" if line else ">"
                    for line in block.text.split("\n")
                ),
            )
        elif block.kind == "line":
            parenthetical = (
                f"（{block.parenthetical}）" if block.parenthetical else ""
            )
            chunks.append(
                f"**{block.character}**{parenthetical}：{block.text}",
            )
        else:
            chunks.append(block.text)
    return "\n\n".join(chunks) + ("\n" if chunks else "")


__all__ = [
    "ScriptBlock",
    "ScriptBlockKind",
    "parse_script_markdown",
    "serialize_script_blocks",
]
