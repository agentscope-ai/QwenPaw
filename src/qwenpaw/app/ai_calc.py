# -*- coding: utf-8 -*-
import logging
from functools import lru_cache
from typing import Any, Optional

from qwenpaw.agents.model_factory import create_model_and_formatter

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _main_model():
    """Get the active chat model instance."""
    try:
        model, _ = create_model_and_formatter()
        return model
    except Exception as e:
        logger.warning(f"Failed to get model: {e}")
        return None


def _extract_text_from_response(response) -> str:
    """Extract text from a non-streaming response."""
    if hasattr(response, "text"):
        return response.text
    if isinstance(response, str):
        return response
    return ""


async def match_rule(sys_rule: str, user_msg: str) -> bool:
    """Match a rule using the LLM."""
    try:
        match_sys_rule = f"""{sys_rule}
请根据以上规则判断用户消息是否符合规则。
如果符合，请只回答 "YES"；如果不符合，请只回答 "NO"。
不要输出任何其他内容。"""
        reply = await llm_calc(match_sys_rule, user_msg)
        full_text = reply.get("text", "")
        result = full_text.strip().upper()
        return result in ["YES", "TRUE", "1", "是"]
    except Exception as e:
        logger.exception(f"Rule matching failed: {e}")
        return False


def _fallback_summary(speech_content: str, max_length: int) -> str:
    """Return truncated speech as fallback when summarization fails."""
    return (
        speech_content[:max_length]
        if len(speech_content) > max_length
        else speech_content
    )


async def summarize_speech(speech_content: str, max_length: int = 50) -> str:
    """Summarize speech using LLM, falling back to truncation on failure."""
    if not speech_content or len(speech_content.strip()) == 0:
        return ""
    try:
        sys_rule = f"""你是一个会议纪要精简专家。请将发言内容精简为不超过{max_length}个字符的要点。
要求：
1. 保留核心观点和关键信息
2. 语言简洁明了
3. 直接返回精简后的内容，不要额外解释"""
        content = f"原始发言内容：\n{speech_content}"
        reply = await llm_calc(sys_rule, content)
        summary = reply.get("text", "").strip()
        if summary:
            logger.info(
                f"[ai_calc] summarize_speech: "
                f"{len(speech_content)} -> {len(summary)} chars",
            )
            return summary
        return _fallback_summary(speech_content, max_length)
    except Exception as e:
        logger.exception(f"Summarize speech failed: {e}")
        return _fallback_summary(speech_content, max_length)


async def parse_llm_rsp(response):
    """Parse LLM response into text and reasoning."""
    final_text, final_reason = "", ""
    if hasattr(response, "__aiter__"):
        async for chunk in response:
            if isinstance(chunk.content, list):
                for item in chunk.content:
                    ty = item.get("type", None)
                    text = item.get("text", "")
                    thinking = item.get("thinking", "")
                    if ty == "thinking" and len(thinking) > 0:
                        final_reason = thinking + "\n"
                    elif ty == "text" and len(text) > 0:
                        final_text = text
            elif isinstance(chunk.content, str):
                final_text = f"{chunk.content}"
    else:
        if hasattr(response, "reason"):
            final_reason = f"{response.reason}"
        if hasattr(response, "content"):
            final_text = f"{response.content}"
        elif hasattr(response, "text"):
            final_text = f"{response.text}"
        else:
            final_text = f"{response}"
    return final_text, final_reason


async def llm_calc(sys_rule: str, user_msg: str) -> dict:
    """Calculate the result of a rule using the LLM."""
    try:
        model = _main_model()
        if not model:
            return {"error": "No AI model configured."}
        content = f"{sys_rule},输入:{user_msg}"
        rsp = await model([{"role": "user", "content": content}])
        text, reason = await parse_llm_rsp(rsp)
        logger.info(
            f"[ai_calc] method: llm_calc, content: {content}  "
            f"text: {text}  reason: {reason}",
        )
        return {"text": text, "reason": reason}
    except Exception as e:
        logger.exception(f"AI calculation failed: {e}")
        return {"error": f"Failed to calculate: {str(e)}"}


# ── SACP Response Parsing ───────────────────────────────────────────


def _extract_reasoning_text(content: Any) -> str:
    """Extract text from reasoning content (recursive)."""
    # pylint: disable=too-many-return-statements
    if content is None:
        return ""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts = [
            t for item in content if (t := _extract_reasoning_text(item)) and t
        ]
        return " ".join(texts)

    if isinstance(content, dict):
        if content.get("type") == "text":
            text = content.get("text", "")
            return text if isinstance(text, str) else ""
        parts = [
            t
            for value in content.values()
            if (t := _extract_reasoning_text(value)) and t
        ]
        return " ".join(parts)

    if hasattr(content, "type") and hasattr(content, "text"):
        text = getattr(content, "text", "")
        return text if isinstance(text, str) else ""

    return str(content) if content else ""


def _extract_tool_from_dict(content: dict) -> list[dict[str, Any]]:
    """Extract tool call from a dict with type==tool_use."""
    if content.get("type") == "tool_use":
        return [
            {
                "name": content.get("name", "unknown"),
                "arguments": content.get("arguments", {}),
            },
        ]
    return []


def _extract_tool_from_object(content: Any) -> list[dict[str, Any]]:
    """Extract tool calls from an object with tool_calls attribute."""
    results = []
    if not hasattr(content, "tool_calls"):
        return results
    tcs = getattr(content, "tool_calls", [])
    if not isinstance(tcs, list):
        return results
    for tc in tcs:
        if hasattr(tc, "function"):
            fn = tc.function
            results.append(
                {
                    "name": getattr(fn, "name", "unknown"),
                    "arguments": getattr(fn, "arguments", {}),
                },
            )
        elif isinstance(tc, dict):
            results.append(
                {
                    "name": tc.get(
                        "name",
                        tc.get("function", {}).get("name", "unknown"),
                    ),
                    "arguments": tc.get(
                        "arguments",
                        tc.get("function", {}).get("arguments", {}),
                    ),
                },
            )
    return results


def _extract_tool_calls_from_content(content: Any) -> list[dict[str, Any]]:
    """Extract tool calls from message content."""
    if isinstance(content, list):
        results = []
        for item in content:
            results.extend(_extract_tool_calls_from_content(item))
        return results
    if isinstance(content, dict):
        results = _extract_tool_from_dict(content)
        if results:
            return results
        results = []
        for value in content.values():
            results.extend(_extract_tool_calls_from_content(value))
        return results
    return _extract_tool_from_object(content)


def _process_message_obj(
    msg,
    final_text_ref,
    reasoning_steps,
    tool_calls,
    plugin_calls,
    plugin_outputs,
):
    """Process an object-style message and update accumulators."""
    msg_type = getattr(msg, "type", None)
    seq = getattr(msg, "sequence_number", None) or 0
    if msg_type == "reasoning":
        text = _extract_reasoning_text(getattr(msg, "content", None))
        if text:
            reasoning_steps.append((seq, text))
    elif msg_type == "message":
        content = getattr(msg, "content", None)
        if content:
            text = _extract_final_text(content)
            if text:
                final_text_ref[0] = text
        tool_calls.extend(_extract_tool_calls_from_content(content))
    elif msg_type == "plugin_call":
        name = getattr(msg, "name", "unknown")
        args = str(getattr(msg, "arguments", {}))[:80]
        plugin_calls.append((seq, name, args))
    elif msg_type == "plugin_call_output":
        output_content = getattr(msg, "content", None)
        output_text = _extract_reasoning_text(output_content)[:80]
        plugin_outputs.append((seq, output_text))
    return final_text_ref


def _process_message_dict(
    msg,
    final_text_ref,
    reasoning_steps,
    tool_calls,
    plugin_calls,
    plugin_outputs,
):
    """Process a dict-style message and update accumulators."""
    msg_type = msg.get("type")
    seq = msg.get("sequence_number", 0) or 0
    if msg_type == "reasoning":
        text = _extract_reasoning_text(msg.get("content"))
        if text:
            reasoning_steps.append((seq, text))
    elif msg_type == "message":
        content = msg.get("content")
        if content:
            text = _extract_final_text(content)
            if text:
                final_text_ref[0] = text
        tool_calls.extend(_extract_tool_calls_from_content(content))
    elif msg_type == "plugin_call":
        name = msg.get("name", "unknown")
        args = str(msg.get("arguments", {}))[:80]
        plugin_calls.append((seq, name, args))
    elif msg_type == "plugin_call_output":
        output_text = _extract_reasoning_text(msg.get("content"))[:80]
        plugin_outputs.append((seq, output_text))
    return final_text_ref


def _extract_message_content(output: list) -> tuple:
    """Extract all message data from output list."""
    final_text_ref = [None]  # Mutable container for inner function to modify
    reasoning_steps: list[tuple[int, str]] = []
    tool_calls: list[dict[str, Any]] = []
    plugin_calls: list[tuple[int, str, str]] = []
    plugin_outputs: list[tuple[int, str]] = []
    for msg in output:
        if isinstance(msg, dict):
            _process_message_dict(
                msg,
                final_text_ref,
                reasoning_steps,
                tool_calls,
                plugin_calls,
                plugin_outputs,
            )
        else:
            _process_message_obj(
                msg,
                final_text_ref,
                reasoning_steps,
                tool_calls,
                plugin_calls,
                plugin_outputs,
            )
    return (
        final_text_ref[0],
        reasoning_steps,
        tool_calls,
        plugin_calls,
        plugin_outputs,
    )


def _truncate_display(text: str, limit: int) -> str:
    """Truncate text and escape for mermaid."""
    display = text[:limit] + "..." if len(text) > limit else text
    return display.replace('"', "'").replace("\n", " ")


def _build_reasoning_section(reasoning_steps: list, parts: list):
    """Build thinking chain subgraph."""
    if not reasoning_steps:
        return
    parts.append("    subgraph 思维链")
    for sseq, stext in reasoning_steps:
        parts.append(f'    S{sseq}["{_truncate_display(stext, 120)}"]')
    parts.append("    end")
    for i in range(len(reasoning_steps) - 1):
        s_curr = reasoning_steps[i][0]
        s_next = reasoning_steps[i + 1][0]
        parts.append(f"    S{s_curr} --> S{s_next}")


def _build_tool_calls_section(tool_calls: list, parts: list):
    """Build tool calls subgraph."""
    if not tool_calls:
        return
    parts.append("    subgraph 工具调用(message)")
    for tc in tool_calls:
        name = tc.get("name", "unknown")
        args = str(tc.get("arguments", ""))[:80]
        tc_id = f"T{name}_{id(tc) % 1000}"
        parts.append(f'    {tc_id}["{name}({args})"]')
    parts.append("    end")


def _build_plugin_calls_section(plugin_calls: list, parts: list) -> dict:
    """Build plugin calls subgraph, return seq->id map."""
    pc_id_map = {}
    if not plugin_calls:
        return pc_id_map
    parts.append("    subgraph 插件调用")
    for pc_seq, pc_name, pc_args in plugin_calls:
        pc_id = f"P{pc_seq}"
        pc_id_map[pc_seq] = pc_id
        display = pc_args[:80] if pc_args else ""
        parts.append(f'    {pc_id}["{pc_name}({display})"]')
    parts.append("    end")
    return pc_id_map


def _build_plugin_outputs_section(
    plugin_outputs: list,
    parts: list,
    pc_id_map: dict,
):
    """Build plugin outputs subgraph and connect to calls."""
    if not plugin_outputs:
        return
    parts.append("    subgraph 插件输出")
    po_id_map = {}
    for po_seq, po_text in plugin_outputs:
        po_id = f"O{po_seq}"
        po_id_map[po_seq] = po_id
        parts.append(f'    {po_id}["{_truncate_display(po_text, 80)}"]')
    parts.append("    end")
    for pc_seq, pc_id in pc_id_map.items():
        for po_seq, po_id in po_id_map.items():
            if pc_seq < po_seq:
                parts.append(f"    {pc_id} -.-> {po_id}")


def _build_reasoning_mermaid(
    reasoning_steps,
    tool_calls,
    plugin_calls,
    plugin_outputs,
) -> str:
    """Build the full reasoning mermaid flowchart."""
    parts = ["flowchart LR"]
    _build_reasoning_section(reasoning_steps, parts)
    _build_tool_calls_section(tool_calls, parts)
    pc_id_map = _build_plugin_calls_section(plugin_calls, parts)
    _build_plugin_outputs_section(plugin_outputs, parts, pc_id_map)
    return "\n".join(parts)


def extract_response_parts(
    output: list[Any] | str,
) -> tuple[Optional[str], str]:
    """Split SACP response output into final text and reasoning chain."""
    if isinstance(output, str):
        return output.strip() if output.strip() else None, ""
    if not output:
        return None, ""
    (
        final_text,
        reasoning_steps,
        tool_calls,
        plugin_calls,
        plugin_outputs,
    ) = _extract_message_content(output)
    reasoning_mermaid = (
        _build_reasoning_mermaid(
            reasoning_steps,
            tool_calls,
            plugin_calls,
            plugin_outputs,
        )
        if (reasoning_steps or tool_calls or plugin_calls or plugin_outputs)
        else ""
    )
    return final_text, reasoning_mermaid


def _extract_final_text(content: Any) -> Optional[str]:
    """Extract final response text from message content (recursive)."""
    # pylint: disable=too-many-return-statements
    if isinstance(content, str):
        return content.strip() if content.strip() else None

    if isinstance(content, list):
        for item in content:
            text = _extract_final_text(item)
            if text:
                return text
        return None

    if isinstance(content, dict):
        if content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            return None
        for value in content.values():
            text = _extract_final_text(value)
            if text:
                return text
        return None

    if hasattr(content, "type") and getattr(content, "type", None) == "text":
        text = getattr(content, "text", None)
        return text.strip() if isinstance(text, str) and text.strip() else None

    try:
        s = str(content)
        return s if s and s != "None" and len(s) > 1 else None
    except Exception:
        return None
