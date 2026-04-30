# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg

from ...agents.model_factory import create_model_and_formatter


logger = logging.getLogger(__name__)


class KnowledgeChunkModelError(RuntimeError):
    """Raised when AI chunking is required but cannot complete."""


MARKDOWN_BLOCK_PREFIXES = ("#", ">", "- ", "* ", "+ ", "1. ", "|")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?\.])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _split_sentences_safe(text: str) -> list[str]:
    """Split text into sentences, protecting markdown image syntax from being split."""
    # Replace markdown images with placeholders
    image_pattern = re.compile(r"!\[.*?\]\(.*?\)")
    placeholders: dict[str, str] = {}
    counter = 0

    def _replace_image(m: re.Match) -> str:
        nonlocal counter
        key = f"\x00IMG{counter}\x00"
        placeholders[key] = m.group(0)
        counter += 1
        return key

    protected = image_pattern.sub(_replace_image, text)
    parts = re.split(r"(?<=[。！？!?\.])\s+", protected)
    result = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        # Restore placeholders
        for key, val in placeholders.items():
            stripped = stripped.replace(key, val)
        result.append(stripped)
    return result


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_content_for_chunking(content: str, chunk_size: int = 1024) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    in_code_block = False

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        joined = _normalize_whitespace(" ".join(line.strip() for line in paragraph_lines if line.strip()))
        if joined:
            blocks.append(joined)
        paragraph_lines.clear()

    for raw_line in normalized.split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            blocks.append(stripped)
            in_code_block = not in_code_block
            continue
        if in_code_block:
            blocks.append(raw_line.rstrip())
            continue
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith(MARKDOWN_BLOCK_PREFIXES):
            flush_paragraph()
            blocks.append(stripped)
            continue
        paragraph_lines.append(stripped)

    flush_paragraph()

    # Split oversized blocks by sentence boundaries so the LLM gets finer-grained units.
    # Use chunk_size * 2 as threshold; protect markdown image syntax from being split.
    max_block_chars = max(200, chunk_size * 2)
    refined: list[str] = []
    for block in blocks:
        if len(block) <= max_block_chars:
            refined.append(block)
        else:
            refined.extend(_split_sentences_safe(block))
    return "\n\n".join(refined).strip()


def _decode_separator(separator: str | None) -> str:
    raw = str(separator or "")
    return raw.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")


def _split_by_separator(text: str, separator: str | None) -> list[str]:
    decoded = _decode_separator(separator)
    if not decoded:
        return [text.strip()] if text.strip() else []
    return [part.strip() for part in text.split(decoded) if part.strip()]


def _build_units(
    content: str,
    granularity: str,
    separator: str | None,
    normalize_whitespace: bool = False,
) -> tuple[list[str], str]:
    decoded_separator = _decode_separator(separator)
    if decoded_separator:
        units = _split_by_separator(content, separator)
        joiner = " " if normalize_whitespace and not decoded_separator.strip() else decoded_separator
        return ([_normalize_whitespace(unit) for unit in units] if normalize_whitespace else units), joiner
    if granularity == "paragraph":
        units = [segment.strip() for segment in re.split(r"\n\s*\n", content) if segment.strip()]
        return ([_normalize_whitespace(unit) for unit in units] if normalize_whitespace else units), (" " if normalize_whitespace else "\n\n")
    if granularity == "sentence":
        units = _split_sentences(content)
        return ([_normalize_whitespace(unit) for unit in units] if normalize_whitespace else units), " "
    paragraph_units = [segment.strip() for segment in re.split(r"\n\s*\n", content) if segment.strip()]
    if len(paragraph_units) > 1:
        return ([_normalize_whitespace(unit) for unit in paragraph_units] if normalize_whitespace else paragraph_units), (" " if normalize_whitespace else "\n\n")
    sentence_units = _split_sentences(content)
    return ([_normalize_whitespace(unit) for unit in sentence_units] if normalize_whitespace else sentence_units), " "


def _safe_split_position(text: str, position: int) -> int:
    """Adjust split position to avoid breaking markdown image syntax like ![xxx](url)."""
    pattern = re.compile(r"!\[.*?\]\(.*?\)")
    for match in pattern.finditer(text):
        if match.start() < position < match.end():
            return match.end()
    return position


def _assemble_chunks(units: list[str], joiner: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    buffer = ""
    for unit in units:
        candidate = unit if not buffer else f"{buffer}{joiner}{unit}"
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
        if len(unit) <= chunk_size:
            buffer = unit
            continue
        start = 0
        step = max(1, chunk_size - chunk_overlap)
        while start < len(unit):
            end = _safe_split_position(unit, start + chunk_size)
            piece = unit[start:end].strip()
            if piece:
                chunks.append(piece)
            start = end
        buffer = ""

    if buffer:
        chunks.append(buffer)
    return chunks


def _load_json_safely(raw_text: str) -> dict[str, Any] | None:
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].split("```")[0].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].split("```")[0].strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _window_units(units: list[str], *, max_units: int = 24, max_chars: int = 6000) -> list[list[str]]:
    windows: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for unit in units:
        unit_chars = len(unit)
        if current and (len(current) >= max_units or current_chars + unit_chars > max_chars):
            windows.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars += unit_chars
    if current:
        windows.append(current)
    return windows


def _validate_split_points(raw_points: Any, unit_count: int) -> list[int] | None:
    if not isinstance(raw_points, list) or not raw_points:
        return None
    split_points: list[int] = []
    for value in raw_points:
        if not isinstance(value, int) or value < 1 or value > unit_count:
            return None
        split_points.append(value)
    if split_points != sorted(set(split_points)):
        return None
    if split_points[-1] != unit_count:
        return None
    return split_points


def _split_units_by_points(units: list[str], split_points: list[int]) -> list[list[str]]:
    groups: list[list[str]] = []
    start = 0
    for point in split_points:
        groups.append(units[start:point])
        start = point
    return groups


async def _semantic_group_units(
    units: list[str],
    *,
    target_size: int,
    agent_id: str | None,
    mode: str,
    fallback_to_heuristic: bool,
    embedding_guided: bool,
) -> list[list[str]] | None:
    if len(units) <= 1:
        return [units]

    try:
        model, formatter = create_model_and_formatter(agent_id)
    except Exception as exc:
        if not fallback_to_heuristic:
            raise KnowledgeChunkModelError(f"Knowledge chunk model unavailable: {exc}") from exc
        logger.warning("Knowledge chunk model unavailable, fallback to heuristic chunking: %s", exc)
        return None

    agent = ReActAgent(
        name="knowledge_chunker",
        model=model,
        sys_prompt=(
            "You are a text structure analysis assistant. "
            "Divide the article into reasonable paragraphs based on semantics and logic, separating each paragraph with a blank line. "
            "Do not change any words of the original text, only perform paragraph segmentation. "
            "If the article already has paragraphs but they are not reasonable, re-optimize the segmentation. "
            "You must respond with a single valid JSON object and nothing else — no explanations, no markdown fences, no extra text."
        ),
        formatter=formatter,
        max_iters=1,
    )

    grouped_units: list[list[str]] = []
    for window in _window_units(units):
        rendered_units = "\n\n".join(f"[{index}]\n{unit}" for index, unit in enumerate(window, start=1))
        prompt = (
            "Divide the following numbered text units into reasonable paragraphs based on semantics and logic.\n"
            f"Mode: {mode}.\n"
            f"Target paragraph size: about {target_size} characters.\n"
            "Guidance: Favor semantic completeness and balanced chunk sizes.\n"
            "Rules:\n"
            "1. Keep original order.\n"
            "2. Each paragraph must contain contiguous unit numbers only.\n"
            "3. Cover every unit exactly once.\n"
            "4. Respect existing paragraph boundaries unless merging improves semantic completeness.\n"
            "5. Avoid isolated headings, table rows, or image markdown blocks when a neighboring unit clearly belongs with them.\n"
            "6. Try to keep each paragraph near the target size; only exceed it when a single unit is already larger.\n"
            "7. Respond with ONLY valid JSON in this exact shape: {\"split_after\": [3, 6, 9]}.\n"
            "8. The last number must equal the last unit index.\n"
            "9. Do NOT include any text before or after the JSON — no markdown fences, no explanations.\n"
            "10. Try not to merge paragraphs that are very different in length, unless it significantly improves semantic completeness.\n\n"
            "Units:\n"
            f"{rendered_units}"
        )

        try:
            response = await agent.reply(Msg(name="User", role="user", content=prompt))
        except Exception as exc:
            if not fallback_to_heuristic:
                raise KnowledgeChunkModelError(f"Knowledge chunk model call failed: {exc}") from exc
            logger.warning("Knowledge chunk model call failed, fallback to heuristic chunking: %s", exc)
            return None

        parsed = _load_json_safely(response.get_text_content() or "")
        split_points = _validate_split_points(parsed.get("split_after") if parsed else None, len(window))
        if split_points is None:
            if not fallback_to_heuristic:
                raise KnowledgeChunkModelError("Knowledge chunk model returned invalid split points.")
            logger.warning("Knowledge chunk model returned invalid split points, fallback to heuristic chunking.")
            return None

        grouped_units.extend(_split_units_by_points(window, split_points))

    return grouped_units


def _assign_assets_to_chunks(chunks: list[dict[str, Any]], assets: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not assets:
        return chunks
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        chunk["assets"] = [asset for asset in assets if str(asset.get("url") or "") and str(asset.get("url")) in content]
    return chunks


def _enforce_chunk_size(chunks: list[dict[str, Any]], chunk_size: int, joiner: str) -> list[dict[str, Any]]:
    """Split any chunk that exceeds chunk_size using character-level slicing."""
    result: list[dict[str, Any]] = []
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        if len(content) <= chunk_size:
            result.append(chunk)
            continue
        pieces = _assemble_chunks([content], joiner, chunk_size, 0)
        for i, piece in enumerate(pieces):
            result.append({
                "name": f"{chunk['name']}-{i + 1}" if i else chunk["name"],
                "content": piece,
                "assets": list(chunk.get("assets") or []),
            })
    return result


def _merge_by_embedding_similarity(
    groups: list[list[str]],
    joiner: str,
    embedding_model_config: dict[str, Any] | None,
    similarity_threshold: float = 0.85,
) -> list[list[str]]:
    """Merge adjacent groups whose embeddings are similar."""
    if not embedding_model_config or len(groups) <= 1:
        return groups

    from .embedding import embed_texts

    texts = [joiner.join(g).strip() for g in groups]
    try:
        embeddings = embed_texts(embedding_model_config, texts)
    except Exception:
        return groups

    if not embeddings or len(embeddings) != len(groups):
        return groups

    merged: list[list[str]] = [list(groups[0])]
    for i in range(1, len(groups)):
        sim = _cosine_similarity(embeddings[i - 1], embeddings[i])
        if sim >= similarity_threshold:
            merged[-1].extend(groups[i])
        else:
            merged.append(list(groups[i]))
    return merged


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _finalize_chunks(chunks: list[dict[str, Any]], assets: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    chunks = _assign_assets_to_chunks(chunks, assets)
    return [
        {
            "id": uuid.uuid4().hex,
            "name": item["name"],
            "content": item["content"],
            "char_count": len(item["content"]),
            "enabled": True,
            "assets": item.get("assets") or [],
        }
        for item in chunks
    ]


async def chunk_text_with_model(
    content: str,
    chunk_config: dict[str, Any],
    *,
    agent_id: str | None,
    assets: list[dict[str, Any]] | None = None,
    fallback_to_heuristic: bool = True,
    embedding_guided: bool = False,
    embedding_model_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    mode = str(chunk_config.get("mode") or "general")
    chunk_size = max(100, int(chunk_config.get("chunk_size") or 1024))
    granularity = str(chunk_config.get("granularity") or "balanced")
    separator = chunk_config.get("separator")

    # When llm_grouping is disabled, skip LLM-based semantic grouping entirely
    if not bool(chunk_config.get("llm_grouping", False)):
        return chunk_text(content, chunk_config, assets=assets)

    normalized = normalize_content_for_chunking(content, chunk_size)
    if not normalized and not assets:
        return []

    if mode == "parent_child":
        parent_units, parent_joiner = _build_units(
            normalized,
            "paragraph",
            chunk_config.get("parent_separator"),
            bool(chunk_config.get("parent_normalize_whitespace", False)),
        )
        parent_groups = await _semantic_group_units(
            parent_units,
            target_size=max(100, int(chunk_config.get("parent_chunk_size") or 1600)),
            agent_id=agent_id,
            mode=mode,
            fallback_to_heuristic=fallback_to_heuristic,
            embedding_guided=embedding_guided,
        )
        if parent_groups is None:
            return chunk_text(content, chunk_config, assets=assets)

        if embedding_guided and embedding_model_config:
            parent_groups = _merge_by_embedding_similarity(parent_groups, parent_joiner, embedding_model_config)

        chunks: list[dict[str, Any]] = []
        for parent_index, parent_group in enumerate(parent_groups, start=1):
            parent_chunk = parent_joiner.join(parent_group).strip()
            if not parent_chunk:
                continue
            child_units, child_joiner = _build_units(
                parent_chunk,
                "sentence",
                chunk_config.get("child_separator"),
                bool(chunk_config.get("child_normalize_whitespace", False)),
            )
            child_groups = await _semantic_group_units(
                child_units or [parent_chunk],
                target_size=max(100, int(chunk_config.get("child_chunk_size") or 400)),
                agent_id=agent_id,
                mode="parent_child_child",
                fallback_to_heuristic=fallback_to_heuristic,
                embedding_guided=embedding_guided,
            )
            if child_groups is None:
                return chunk_text(content, chunk_config, assets=assets)
            for child_index, child_group in enumerate(child_groups, start=1):
                child_chunk = child_joiner.join(child_group).strip()
                if child_chunk:
                    chunks.append({"name": f"P{parent_index}-C{child_index}", "content": child_chunk, "assets": []})
    else:
        units, joiner = _build_units(
            normalized,
            granularity,
            separator,
            bool(chunk_config.get("normalize_whitespace", False)),
        )
        groups = await _semantic_group_units(
            units,
            target_size=chunk_size,
            agent_id=agent_id,
            mode=mode,
            fallback_to_heuristic=fallback_to_heuristic,
            embedding_guided=embedding_guided,
        )
        if groups is None:
            return chunk_text(content, chunk_config, assets=assets)

        if embedding_guided and embedding_model_config:
            groups = _merge_by_embedding_similarity(groups, joiner, embedding_model_config)

        chunks = [
            {"name": f"Chunk {index + 1}", "content": joiner.join(group).strip(), "assets": []}
            for index, group in enumerate(groups)
            if group and joiner.join(group).strip()
        ]

    chunks = _enforce_chunk_size(chunks, chunk_size, joiner if not mode == "parent_child" else "\n\n")
    return _finalize_chunks(chunks, assets)


def chunk_text(content: str, chunk_config: dict[str, Any], assets: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    mode = str(chunk_config.get("mode") or "general")
    chunk_size = max(100, int(chunk_config.get("chunk_size") or 800))
    chunk_overlap = max(0, int(chunk_config.get("chunk_overlap") or 0))
    granularity = str(chunk_config.get("granularity") or "balanced")
    separator = chunk_config.get("separator")

    normalized = normalize_content_for_chunking(content, chunk_size)
    if not normalized and not assets:
        return []

    if mode == "parent_child":
        parent_units, parent_joiner = _build_units(
            normalized,
            "paragraph",
            chunk_config.get("parent_separator"),
            bool(chunk_config.get("parent_normalize_whitespace", False)),
        )
        parent_chunks = _assemble_chunks(
            parent_units,
            parent_joiner,
            max(100, int(chunk_config.get("parent_chunk_size") or 1600)),
            max(0, int(chunk_config.get("parent_chunk_overlap") or 0)),
        )
        chunks: list[dict[str, Any]] = []
        for parent_index, parent_chunk in enumerate(parent_chunks, start=1):
            child_units, child_joiner = _build_units(
                parent_chunk,
                "sentence",
                chunk_config.get("child_separator"),
                bool(chunk_config.get("child_normalize_whitespace", False)),
            )
            child_chunks = _assemble_chunks(
                child_units or [parent_chunk],
                child_joiner,
                max(100, int(chunk_config.get("child_chunk_size") or 400)),
                max(0, int(chunk_config.get("child_chunk_overlap") or 0)),
            )
            for child_index, child_chunk in enumerate(child_chunks, start=1):
                chunks.append({"name": f"P{parent_index}-C{child_index}", "content": child_chunk, "assets": []})
    else:
        units, joiner = _build_units(
            normalized,
            granularity,
            separator,
            bool(chunk_config.get("normalize_whitespace", False)),
        )
        chunk_bodies = _assemble_chunks(units, joiner, chunk_size, chunk_overlap)
        chunks = [{"name": f"Chunk {index + 1}", "content": chunk_body, "assets": []} for index, chunk_body in enumerate(chunk_bodies)]

    return _finalize_chunks(chunks, assets)