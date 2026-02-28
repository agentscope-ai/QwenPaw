# -*- coding: utf-8 -*-
"""Pre-reasoning hook: run VLM on images inside tool results.

When the primary LLM is text-only and a VLM is configured, tool results
containing images (e.g. browser screenshots, desktop captures) are invisible
to the LLM.  This hook intercepts such results before each reasoning step,
sends the images to the VLM for description, and replaces the raw image
blocks with the textual description so the text-only LLM can reason about
the visual content.
"""
import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any

from agentscope.message import Msg
from agentscope.model._model_response import ChatResponse

from ..image_understanding import _resolve_image_blocks_to_base64
from ..model_capabilities import supports_input_capability

logger = logging.getLogger(__name__)


def _is_text_block(block: Any) -> bool:
    """Check if a block is a text block (dict-like with type='text')."""
    if isinstance(block, dict):
        return block.get("type") == "text"
    return getattr(block, "type", None) == "text"


def _get_block_text(block: Any) -> str:
    """Extract text string from a text block."""
    if isinstance(block, dict):
        return block.get("text", "")
    return getattr(block, "text", "")


def _extract_text_from_content(content: list) -> str:
    """Extract text from ChatResponse content blocks."""
    parts: list[str] = []
    for block in content:
        if _is_text_block(block):
            parts.append(_get_block_text(block))
    return "".join(parts)


_SKIP_VLM_TOOLS: set[str] = {
    "send_file_to_user",
    "send_message_to_user",
}


class ToolResultVLMPrepassHook:
    """Run VLM prepass on images embedded in tool-result memory entries."""

    def __init__(self) -> None:
        self._processed: set[tuple[str, int]] = set()
        self._running = False

    async def __call__(
        self,
        agent: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self._running:
            return None

        if not self._needs_processing(agent):
            return None

        items = self._collect_unprocessed(agent)
        if not items:
            return None

        self._running = True
        try:
            await self._process_items(agent, items)
        finally:
            self._running = False
        return None

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _needs_processing(agent: Any) -> bool:
        """Return True when primary LLM is text-only and a VLM is available."""
        llm_cfg = getattr(agent, "_active_llm_cfg", None)
        if llm_cfg is not None and supports_input_capability(llm_cfg, "image"):
            return False
        return getattr(agent, "_vlm_model", None) is not None

    # ------------------------------------------------------------------
    # Memory scanning
    # ------------------------------------------------------------------

    def _collect_unprocessed(
        self,
        agent: Any,
    ) -> list[tuple[Msg, dict, list[dict], int]]:
        """Find tool_result blocks in memory that contain image outputs."""
        entries = getattr(agent.memory, "content", None)
        if not entries:
            return []

        items: list[tuple[Msg, dict, list[dict], int]] = []
        for entry in entries:
            msg = entry[0] if isinstance(entry, tuple) else entry
            if not isinstance(msg, Msg):
                continue
            if not isinstance(msg.content, list):
                continue
            for idx, block in enumerate(msg.content):
                if (msg.id, idx) in self._processed:
                    continue
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                output = block.get("output", [])
                if not isinstance(output, list):
                    continue
                img_blocks = [
                    b
                    for b in output
                    if isinstance(b, dict) and b.get("type") == "image"
                ]
                if img_blocks:
                    items.append((msg, block, img_blocks, idx))
        return items

    # ------------------------------------------------------------------
    # VLM processing
    # ------------------------------------------------------------------

    async def _process_items(
        self,
        agent: Any,
        items: list[tuple[Msg, dict, list[dict], int]],
    ) -> None:
        for msg, tool_result_block, image_blocks, block_idx in items:
            tool_name = tool_result_block.get("name", "unknown_tool")
            if tool_name in _SKIP_VLM_TOOLS:
                self._strip_image_blocks(tool_result_block)
                self._processed.add((msg.id, block_idx))
                continue
            description: str | None = None
            try:
                description = await self._describe_images(
                    agent,
                    image_blocks,
                    tool_name,
                )
            except Exception as exc:
                logger.warning(
                    "VLM prepass on tool-result images from '%s' failed: %s",
                    tool_name,
                    exc,
                )

            self._replace_image_blocks(tool_result_block, description)
            self._processed.add((msg.id, block_idx))

    async def _describe_images(
        self,
        agent: Any,
        image_blocks: list[dict],
        tool_name: str,
    ) -> str:
        resolved = _resolve_image_blocks_to_base64(image_blocks)

        if tool_name == "browser_use":
            resolved, labeled = await self._try_labeled_screenshot(resolved)
            base_prompt = (
                "You are a vision preprocessor for a browser screenshot.\n"
                "The structural information (text, links, buttons) is "
                "ALREADY available from the accessibility tree. "
                "Do NOT repeat it.\n"
                "Focus ONLY on visual details:\n"
                "- Image/thumbnail/video cover content (what is depicted)\n"
                "- Colors, icons, visual indicators\n"
                "- Spatial layout and relative positioning of elements\n"
                "- Any visual-only UI state (hover effects, highlights)\n"
                "Be concise. Skip elements where text labels already "
                "describe the content."
            )
            if labeled:
                prompt_text = (
                    base_prompt + "\n"
                    "The screenshot has orange ref labels (e.g. e57) overlaid "
                    "on elements. Use these refs when describing visual "
                    "content so it can be matched to the accessibility tree."
                )
            else:
                prompt_text = base_prompt
        else:
            prompt_text = (
                "You are a vision preprocessor. "
                f"The tool '{tool_name}' returned the following "
                "screenshot/image. "
                "Describe it concisely and accurately.\n"
                "Include: visible text (OCR), UI elements, layout, "
                "key objects/entities, and any notable details.\n"
                "Do NOT claim you cannot view the image.\n"
                "Do NOT request external tools."
            )
        vlm_msg = Msg(
            name="user",
            role="user",
            content=[{"type": "text", "text": prompt_text}, *resolved],
        )

        prompt = await agent.formatter.format(
            [
                Msg(
                    "system",
                    "You are a helpful vision assistant.",
                    "system",
                ),
                vlm_msg,
            ],
        )

        vision_settings = getattr(agent, "_vision_settings", None)
        image_settings = getattr(vision_settings, "image", None)
        timeout_seconds = getattr(image_settings, "timeout_seconds", 120)
        max_output_chars = getattr(image_settings, "max_output_chars", 2000)

        vlm_model = agent._vlm_model
        response = await asyncio.wait_for(
            vlm_model(prompt),
            timeout=max(1, timeout_seconds),
        )

        text = ""
        if vlm_model.stream:
            last_content: list = []
            async for chunk in response:
                if isinstance(chunk, ChatResponse):
                    last_content = list(chunk.content)
            text = _extract_text_from_content(last_content)
        else:
            if isinstance(response, ChatResponse):
                text = _extract_text_from_content(list(response.content))
            elif isinstance(response, Msg):
                text = response.get_text_content() or ""

        text = text.strip()
        if not text:
            raise RuntimeError("VLM returned empty description")

        if 0 < max_output_chars < len(text):
            text = text[: max_output_chars - 3] + "..."

        logger.info(
            "VLM described tool-result image from '%s' (%d chars)",
            tool_name,
            len(text),
        )
        return text

    # ------------------------------------------------------------------
    # Browser label overlay
    # ------------------------------------------------------------------

    @staticmethod
    async def _try_labeled_screenshot(
        resolved: list[dict],
    ) -> tuple[list[dict], bool]:
        """Replace browser screenshot with a labeled version if possible.

        Returns (image_blocks, was_labeled).
        """
        try:
            from ..tools.browser_control import get_labeled_screenshot

            img_bytes = await get_labeled_screenshot()
            if img_bytes is None:
                return resolved, False

            debug_dir = Path("downloads") / "vlm_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / f"vlm_labeled_{int(time.time())}.png"
            debug_path.write_bytes(img_bytes)
            logger.info("VLM labeled screenshot saved: %s", debug_path)

            b64 = base64.b64encode(img_bytes).decode("ascii")
            labeled_block = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            }
            return [labeled_block], True
        except Exception as exc:
            logger.debug("Labeled screenshot unavailable: %s", exc)
            return resolved, False

    # ------------------------------------------------------------------
    # Memory mutation
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_image_blocks(tool_result_block: dict) -> None:
        """Remove image blocks from tool result (no VLM description needed)."""
        output = tool_result_block.get("output", [])
        if isinstance(output, list):
            tool_result_block["output"] = [
                b for b in output
                if not (isinstance(b, dict) and b.get("type") == "image")
            ]

    @staticmethod
    def _replace_image_blocks(
        tool_result_block: dict,
        description: str | None,
    ) -> None:
        """Replace image blocks inside the tool_result output with text."""
        output = tool_result_block.get("output", [])
        if not isinstance(output, list):
            return

        new_output: list[dict] = []
        for block in output:
            if isinstance(block, dict) and block.get("type") == "image":
                continue
            new_output.append(block)

        if description:
            caveat = (
                "Note: This is a summary. For questions about specific "
                "visual details or spatial positions (e.g. what is above/"
                "below a particular element), take a targeted screenshot "
                "of that area using action=screenshot with ref=<element>."
            )
            new_output.append(
                {
                    "type": "text",
                    "text": (
                        "\n[Image Description (from vision model)]\n"
                        f"{description}\n"
                        f"{caveat}\n"
                        "[/Image Description]"
                    ),
                },
            )
        else:
            new_output.append(
                {
                    "type": "text",
                    "text": "[Image: vision analysis unavailable]",
                },
            )

        tool_result_block["output"] = new_output
