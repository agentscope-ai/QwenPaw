# -*- coding: utf-8 -*-
"""Proposal choice tool for interactive resource selection.

Presents resource proposals to users in table format and waits for
their selection. Supports up to 5 proposals with resource details,
including multi-strategy proposals from iac-code.

Auto-corrects common LLM formatting mistakes:
- Strips header rows (e.g. ["资源类型", "资源用途", ...])
- Splits flat 2D arrays into multiple proposals using "合计" rows
"""

import asyncio
import json
import logging
import re
from typing import Any, List, Optional, Union

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

# pylint: disable=no-name-in-module
from qwenpaw.app.interaction import InteractionManager
from qwenpaw.app.agent_context import get_current_session_id

logger = logging.getLogger(__name__)

_INTERACTION_TIMEOUT = 3600  # 1 hour

# Fixed table headers for resource proposals
_TABLE_HEADERS = [
    "资源类型",
    "资源用途",
    "规格",
    "地域",
    "数量",
    "计费方式",
    "时长",
    "原价",
    "优惠",
    "预估算费用",
]

# Fixed proposal names (extended for multi-strategy support)
_PROPOSAL_NAMES = ["方案一", "方案二", "方案三", "方案四", "方案五"]


def _validate_cell(cell: Any) -> bool:
    """Validate a single cell value.

    Cell can be:
    - A string
    - An object with "text" (required) and optional "url" fields
    """
    if isinstance(cell, str):
        return True
    if isinstance(cell, dict):
        return "text" in cell and isinstance(cell["text"], str)
    return False


def _is_row(item: Any) -> bool:
    """Check if item is a valid row (list of 10 cells)."""
    return isinstance(item, list) and len(item) == 10


_HEADER_KEYWORDS = frozenset(h.lower() for h in _TABLE_HEADERS)


def _is_header_row(row: List[Any]) -> bool:
    """Detect if a row is a table header (e.g. ["资源类型", "资源用途", ...])."""
    if not _is_row(row):
        return False
    first = str(row[0]).strip().lower() if row[0] else ""
    return first in _HEADER_KEYWORDS


def _is_summary_row(row: List[Any]) -> bool:
    """Detect summary/total rows (first cell matches 合计/总计/total)."""
    if not _is_row(row):
        return False
    first = str(row[0]).strip() if row[0] else ""
    return bool(first) and bool(
        re.match(r"^(合计|总计|total)", first, re.IGNORECASE),
    )


def _split_flat_rows_into_proposals(
    rows: List[List[Any]],
) -> List[List[List[Any]]]:
    """Split a flat 2D array into proposals.

    Uses summary rows as delimiters.

    When the LLM puts two proposals' rows into a single 2D array, we can
    recover the intended structure by splitting on "合计" rows: each "合计"
    row marks the end of a proposal.
    """
    proposals: List[List[List[Any]]] = []
    current: List[List[Any]] = []
    for row in rows:
        current.append(row)
        if _is_summary_row(row):
            proposals.append(current)
            current = []
    if current:
        if proposals:
            proposals[-1].extend(current)
        else:
            proposals.append(current)
    return proposals if proposals else [rows]


def _normalize_proposals(  # pylint: disable=too-many-return-statements
    data: Any,
    expected_count: int = 0,
) -> Union[List[List[List[Any]]], str]:
    """Normalize proposals data to 3D array format.

    Accepts multiple formats and auto-corrects common LLM mistakes:
    - 2D array (single proposal): [[row1], [row2], ...].
      Each row has 10 columns.
    - 3D array (multiple proposals): [[[row1], [row2]], [[row3]]]
    - 2D array with mixed proposals: auto-splits on "合计" rows

    Also auto-strips header rows (e.g. ["资源类型", "资源用途", ...]) that the
    LLM sometimes inserts.

    Args:
        data: Parsed JSON data
        expected_count: Expected number of proposals (from strategy_names).
            Length used as a hint to split flat arrays when summary rows
            are missing.
    """
    if not isinstance(data, list) or len(data) == 0:
        return "Error: data must be a non-empty JSON array."

    # Check if it's a 2D array (all items are 10-column rows)
    if all(_is_row(item) for item in data):
        cleaned = [r for r in data if not _is_header_row(r)]
        if not cleaned:
            return (
                "Error: data contains only header rows, "
                "no actual resource data."
            )
        summary_count = sum(1 for r in cleaned if _is_summary_row(r))
        if summary_count >= 2:
            return _split_flat_rows_into_proposals(cleaned)
        if expected_count >= 2 and len(cleaned) >= expected_count * 2:
            import math

            chunk = math.ceil(len(cleaned) / expected_count)
            return [
                cleaned[i : i + chunk] for i in range(0, len(cleaned), chunk)
            ]
        return [cleaned]

    # Check if it's a 3D array (multiple proposals)
    if all(isinstance(item, list) for item in data):
        result = []
        for i, proposal in enumerate(data):
            if not isinstance(proposal, list) or len(proposal) == 0:
                return (
                    f"Error: proposal {i + 1} must be a non-empty array "
                    f"of rows. Each row should have 10 columns: "
                    f"{', '.join(_TABLE_HEADERS)}"
                )
            cleaned = [
                r for r in proposal if _is_row(r) and not _is_header_row(r)
            ]
            if not cleaned:
                return (
                    f"Error: proposal {i + 1} has no valid data rows after "
                    f"filtering headers."
                )
            for j, row in enumerate(cleaned):
                if not _is_row(row):
                    return (
                        f"Error: row {j + 1} in proposal {i + 1} has "
                        f"{len(row)} columns, expected 10. "
                        f"Columns: {', '.join(_TABLE_HEADERS)}"
                    )
            result.append(cleaned)
        return result

    return (
        "Error: data format not recognized. Expected either:\n"
        "- 2D array for single proposal: [[row1], [row2], ...] "
        "where each row has 10 columns\n"
        "- 3D array for multiple proposals: [[[row1], [row2]], [[row3]]] "
        "where each proposal contains rows"
    )


def _validate_proposals(proposals: List[List[List[Any]]]) -> Union[str, None]:
    """Validate normalized proposals data structure."""
    if len(proposals) < 1 or len(proposals) > 5:
        return (
            f"Error: must have 1 to 5 proposals (found {len(proposals)}). "
            f"Each proposal can contain multiple resource rows."
        )

    for i, proposal in enumerate(proposals):
        for j, row in enumerate(proposal):
            for k, cell in enumerate(row):
                if not _validate_cell(cell):
                    return (
                        f"Error: cell at proposal {i + 1}, row {j + 1}, "
                        f"column '{_TABLE_HEADERS[k]}' is invalid. "
                        f"Cell must be a string or an object with "
                        f"'text' field."
                    )

    return None


async def proposal_choice(
    data: str,
    strategy_names: Optional[str] = None,
) -> ToolResponse:
    """Display a resource proposal to user and wait for confirmation.

    Presents a resource proposal in table format with fixed headers and
    waits for user to confirm deployment or request adjustments.

    Args:
        data (`str`):
            A JSON-encoded 2D array of resource rows (single proposal) or
            3D array (multiple proposals). Each row must have exactly 10
            columns matching the fixed headers:
            资源类型, 资源用途, 规格, 地域, 数量, 计费方式, 时长, 原价, 优惠, 预估算费用

            Example (single proposal):
            ```json
            [
              ["ECS", "Web服务器", "2核4G", "华东1", "1", "包年包月", "1年",
               "¥1200", "8折", "¥960"],
              ["OSS", "存储", "标准", "华东1", "1", "按量付费", "-",
               "¥100", "-", "¥100"],
              ["合计", "", "", "", "", "", "", "", "", "≈¥1060/月"]
            ]
            ```

            The last row of each proposal should be a summary row with
            "合计" as the first column and the total cost in the last
            column. The frontend
            renders this row separately and does NOT compute totals itself.

            Cell value format:
            - String: "value"
            - Object with URL: {"text": "value", "url": "https://..."}

        strategy_names (`str`, optional):
            JSON-encoded list of strategy display names for each proposal.
            If provided, these names replace the default proposal names
            ("方案一/方案二/方案三").
            Example: '["最低价方案", "中等配置", "高性能方案"]'

    Returns:
        `ToolResponse`:
            When user confirms deployment: "用户确认部署"
            When user requests adjustment: "用户要求调整资源：{user input text}"
            When timeout (1 hour): "用户确认部署"
    """
    # Parse JSON data
    try:
        raw_data: Any = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: 'data' parameter must be a valid JSON "
                        "string. Expected a 2D array (single proposal) "
                        "or 3D array (multiple proposals). Each row "
                        "must have 10 columns."
                    ),
                ),
            ],
        )

    # Parse strategy names if provided
    custom_names: list[str] | None = None
    if strategy_names:
        try:
            parsed_names = json.loads(strategy_names)
            if isinstance(parsed_names, list) and all(
                isinstance(n, str) for n in parsed_names
            ):
                custom_names = parsed_names
        except (json.JSONDecodeError, TypeError):
            pass

    # Normalize to 3D array format
    expected_count = len(custom_names) if custom_names else 0
    normalized = _normalize_proposals(raw_data, expected_count=expected_count)
    if isinstance(normalized, str):
        return ToolResponse(
            content=[TextBlock(type="text", text=normalized)],
        )
    proposals: List[List[List[Any]]] = normalized

    # Validate proposals structure
    error = _validate_proposals(proposals)
    if error:
        return ToolResponse(
            content=[
                TextBlock(type="text", text=error),
            ],
        )

    # Determine proposal names
    proposal_names: list[str]
    if custom_names and len(custom_names) >= len(proposals):
        proposal_names = custom_names[: len(proposals)]
    elif len(proposals) == 1:
        proposal_names = ["方案"]
    else:
        proposal_names = _PROPOSAL_NAMES[: len(proposals)]

    # Get session context
    session_id = get_current_session_id()
    logger.info("[proposal_choice] session_id from context: %s", session_id)
    if session_id is None:
        payload = json.dumps(
            {
                "headers": _TABLE_HEADERS,
                "proposals": proposals,
                "proposal_names": proposal_names,
            },
            ensure_ascii=False,
        )
        return ToolResponse(
            content=[TextBlock(type="text", text=payload)],
        )

    logger.info(
        "[proposal_choice] Creating interaction for session: %s",
        session_id,
    )
    interaction = InteractionManager.create(session_id)
    try:
        await asyncio.wait_for(
            interaction.event.wait(),
            timeout=_INTERACTION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="用户确认部署",
                ),
            ],
        )
    finally:
        InteractionManager.cleanup(session_id)

    result = interaction.result or "用户未做出选择"
    return ToolResponse(
        content=[TextBlock(type="text", text=result)],
    )
