#!/usr/bin/env python3
"""Test script: run chunking prompt against a real content.txt and print the split result."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

from agentscope.agent import ReActAgent
from agentscope.message import Msg

from qwenpaw.agents.model_factory import create_model_and_formatter


CONTENT_PATH = Path(
    "/wsc/qwen-paw/.qwenpaw/knowledge_base/custom-product-readme"
    "/documents/23c880be569444b0a20af0fa5ddc3b7c/content.txt"
)


def _load_json_safely(raw_text: str) -> dict | None:
    import json, re
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].split("```")[0].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].split("```")[0].strip()
    try:
        return json.loads(cleaned) if isinstance(json.loads(cleaned), dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def main():
    content = CONTENT_PATH.read_text(encoding="utf-8").strip()
    if not content:
        print("ERROR: content.txt is empty")
        return

    # Build units the same way the real pipeline does
    from qwenpaw.app.knowledge.parsing_chunking import (
        normalize_content_for_chunking,
        _build_units,
        _window_units,
        _validate_split_points,
        _split_units_by_points,
    )

    normalized = normalize_content_for_chunking(content, chunk_size=1024)
    print(f"=== Normalized length: {len(normalized)} chars ===\n")
    print(f"=== Units count: {len(units)} ===\n")
    for i, u in enumerate(units):
        print(f"  [{i+1}] ({len(u)} chars) {u[:120]}...")
    print()

    # Get the LLM model
    try:
        model, formatter = create_model_and_formatter("default")
    except Exception as exc:
        print(f"ERROR: cannot create model: {exc}")
        return

    # ── PROMPT TEMPLATE (edit this to experiment) ──────────────────────
    SYSTEM_PROMPT = (
        "You are a text structure analysis assistant. "
        "Divide the article into reasonable paragraphs based on semantics and logic, separating each paragraph with a blank line. "
        "Do not change any words of the original text, only perform paragraph segmentation. "
        "If the article already has paragraphs but they are not reasonable, re-optimize the segmentation. "
        "You must respond with a single valid JSON object and nothing else — no explanations, no markdown fences, no extra text."
    )

    USER_PROMPT_TEMPLATE = (
        "Divide the following numbered text units into reasonable paragraphs based on semantics and logic.\n"
        "Mode: general.\n"
        "Target paragraph size: about 1024 characters.\n"
        "Guidance: Favor semantic completeness and balanced chunk sizes.\n"
        "Rules:\n"
        "1. Keep original order.\n"
        "2. Each paragraph must contain contiguous unit numbers only.\n"
        "3. Cover every unit exactly once.\n"
        "4. Respect existing paragraph boundaries unless merging improves semantic completeness.\n"
        "5. Avoid isolated headings, table rows, or image markdown blocks when a neighboring unit clearly belongs with them.\n"
        "6. Try to keep each paragraph near the target size; only exceed it when a single unit is already larger.\n"
        "7. Respond with ONLY valid JSON in this exact shape: {{\"split_after\": [3, 6, 9]}}.\n"
        "8. The last number must equal the last unit index.\n"
        "9. Do NOT include any text before or after the JSON — no markdown fences, no explanations.\n\n"
        "Units:\n{units}"
    )

    agent = ReActAgent(
        name="chunk_tester",
        model=model,
        sys_prompt=SYSTEM_PROMPT,
        formatter=formatter,
        max_iters=1,
    )

    all_groups: list[list[str]] = []
    for window in _window_units(units):
        rendered = "\n\n".join(
            f"[{i}]\n{u}" for i, u in enumerate(window, start=1)
        )
        prompt = USER_PROMPT_TEMPLATE.format(units=rendered)

        print(f"--- Window of {len(window)} units ---")
        response = await agent.reply(
            Msg(name="User", role="user", content=prompt)
        )
        raw = response.get_text_content() or ""
        print(f"LLM raw response:\n{raw}\n")

        parsed = _load_json_safely(raw)
        split_points = _validate_split_points(
            parsed.get("split_after") if parsed else None, len(window)
        )
        if split_points is None:
            print("WARNING: invalid split points, treating as one chunk")
            all_groups.append(window)
        else:
            all_groups.extend(_split_units_by_points(window, split_points))

    print(f"\n=== RESULT: {len(all_groups)} paragraph(s) ===\n")
    for idx, group in enumerate(all_groups, start=1):
        text = joiner.join(group).strip()
        print(f"--- Paragraph {idx} ({len(text)} chars) ---")
        print(text)
        print()


if __name__ == "__main__":
    asyncio.run(main())
