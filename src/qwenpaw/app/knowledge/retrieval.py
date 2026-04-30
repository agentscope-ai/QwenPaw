# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentscope.message import AudioBlock, ImageBlock, TextBlock, VideoBlock

from ...agents.schema import FileBlock
from .assets import asset_kind_for_suffix

from .embedding import cosine_similarity, embed_texts, has_usable_embedding_model
from .soul import load_soul_knowledge_config
from .storage import load_store
from .vector_config import DEFAULT_RETRIEVAL_CONFIG, load_knowledge_vector_config


_KNOWLEDGE_ASSET_PATTERN = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<markdown_url>/api/files/preview/knowledge-assets/[^)\s]+)\)"
    r"|(?P<plain_url>/api/files/preview/knowledge-assets/[^)\s]+)",
)


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) if token}


def _matches_reference_trigger(reference: dict, knowledge: dict, query: str) -> bool:
    if reference["trigger"] == "always":
        return True
    lowered = query.lower()
    if any(keyword.lower() in lowered for keyword in reference.get("keywords") or []):
        return True
    return knowledge["name"].lower() in lowered or knowledge["id"] in lowered


def _render_asset_context(chunk: dict) -> str:
    assets = chunk.get("assets") or []
    if not assets:
        return ""
    lines = []
    for asset in assets:
        kind_title = str(asset.get("kind") or "file").capitalize()
        asset_name = str(asset.get("name") or asset.get("id") or "asset")
        asset_url = str(asset.get("url") or "").strip()
        lines.append(
            f"[{kind_title}] {asset_name}" + (f" ({asset_url})" if asset_url else ""),
        )
    return "\n".join(lines)


def _render_chunk_context(chunk: dict) -> str:
    content = str(chunk.get("content") or "").strip()
    asset_context = _render_asset_context(chunk)
    if content and asset_context and asset_context not in content:
        return f"{content}\n{asset_context}"
    return content or asset_context


def _score_chunk(query_tokens: set[str], knowledge: dict, document: dict, chunk: dict) -> float:
    haystack = " ".join(
        [
            knowledge["name"],
            document["name"],
            chunk["name"],
            _render_chunk_context(chunk),
        ],
    ).lower()
    haystack_tokens = _tokenize(haystack)
    overlap = len(query_tokens & haystack_tokens)
    exact_bonus = 0.5 if any(token in haystack for token in query_tokens) else 0.0
    return overlap + exact_bonus


def _build_asset_block(url: str, alt: str = "") -> dict[str, Any]:
    suffix = Path(url).suffix.lower()
    kind = asset_kind_for_suffix(suffix)
    source = {"type": "url", "url": url}
    if kind == "image":
        return ImageBlock(type="image", source=source)
    if kind == "audio":
        return AudioBlock(type="audio", source=source)
    if kind == "video":
        return VideoBlock(type="video", source=source)
    filename = alt.strip() or Path(url).name or "file"
    return FileBlock(type="file", source=source, filename=filename)


def build_retrieval_context(workspace_dir: Path, query: str, agent_id: str = "default") -> str | None:
    if not query.strip():
        return None

    references = load_soul_knowledge_config(workspace_dir)["items"]
    if not references:
        return None

    store = load_store(workspace_dir)
    query_tokens = _tokenize(query)
    try:
        runtime_config = load_knowledge_vector_config(agent_id, include_secret=True)
    except Exception:
        runtime_config = {
            "embedding_model_config": {},
            "retrieval_config": DEFAULT_RETRIEVAL_CONFIG,
        }

    retrieval_config = runtime_config.get("retrieval_config") or DEFAULT_RETRIEVAL_CONFIG
    embedding_config = runtime_config.get("embedding_model_config") or {}
    search_method = retrieval_config.get("search_method") or "hybrid"
    score_threshold_enabled = bool(retrieval_config.get("score_threshold_enabled", False))
    score_threshold = float(retrieval_config.get("score_threshold") or 0.0)
    weights = retrieval_config.get("weights") or {}
    vector_weight = float(weights.get("vector_weight") or 0.7)
    keyword_weight = float(weights.get("keyword_weight") or 0.3)
    query_embedding: list[float] | None = None
    if (
        retrieval_config.get("indexing_technique") == "high_quality"
        and search_method in {"semantic", "hybrid"}
        and has_usable_embedding_model(embedding_config)
    ):
        try:
            embeddings = embed_texts(embedding_config, [query])
            query_embedding = embeddings[0] if embeddings else None
        except Exception:
            query_embedding = None
    sections: list[str] = []

    for reference in references:
        knowledge = next(
            (
                item
                for item in store["knowledge_bases"]
                if item["id"] == reference["id"] and item["enabled"]
            ),
            None,
        )
        if knowledge is None:
            continue
        if not _matches_reference_trigger(reference, knowledge, query):
            continue

        scored_chunks: list[tuple[float, dict, dict]] = []
        for document in knowledge["documents"]:
            if document.get("status") != "enabled" or not document.get("enabled", False):
                continue
            for chunk in document["chunks"]:
                if not chunk.get("enabled", False):
                    continue
                keyword_score = _score_chunk(query_tokens, knowledge, document, chunk)
                vector_score = cosine_similarity(query_embedding, chunk.get("embedding"))
                if search_method == "semantic":
                    score = vector_score
                elif search_method == "full_text" or search_method == "keyword":
                    score = keyword_score
                else:
                    score = (vector_score * vector_weight) + (keyword_score * keyword_weight)
                if score_threshold_enabled and score < score_threshold:
                    continue
                scored_chunks.append((score, document, chunk))

        scored_chunks.sort(key=lambda item: (item[0], item[2].get("updated_at") or ""), reverse=True)
        top_k = max(1, int(reference.get("retrieval_top_k") or retrieval_config.get("top_k") or 3))
        selected = [item for item in scored_chunks if item[0] > 0][:top_k]
        if not selected and reference["trigger"] == "always":
            selected = scored_chunks[:top_k]
        if not selected:
            continue

        lines = [
            f"Knowledge Base: {knowledge['name']} ({knowledge['id']})",
            f"Usage Rule: {reference['usage_rule']}",
        ]
        for _, document, chunk in selected:
            chunk_context = _render_chunk_context(chunk)
            # 优先保证 markdown image 块不被截断
            max_len = 1200
            if len(chunk_context) > max_len:
                # 查找所有 markdown image 的区间
                img_spans = [m.span() for m in re.finditer(r'!\[[^\]]*\]\([^\)\s]+\)', chunk_context)]
                # 找到第一个超出 max_len 的 image 块
                cut = max_len
                for start, end in img_spans:
                    if start < max_len < end:
                        cut = end
                        break
                    if start >= max_len:
                        cut = start
                        break
                chunk_context = chunk_context[:cut]
            lines.append(f"- {document['name']} / {chunk['name']}: {chunk_context}")
        sections.append("\n".join(lines))

    if not sections:
        return None

    return (
        "Use the following retrieved knowledge-base context when answering. "
        "If it conflicts with the user's current request, explain the conflict clearly. "
        "If the context contains images (such as markdown image links), you must preserve and reference these images in your answer. "
        "Do not omit or ignore any image references from the context.\n\n"
        + "\n\n".join(sections)
    )


def build_retrieval_message_content(
    workspace_dir: Path,
    query: str,
    agent_id: str = "default",
) -> list[dict[str, Any]] | None:
    context = build_retrieval_context(workspace_dir, query, agent_id)
    if not context:
        return None

    blocks: list[dict[str, Any]] = []
    cursor = 0

    for match in _KNOWLEDGE_ASSET_PATTERN.finditer(context):
        start, end = match.span()
        if start > cursor:
            text = context[cursor:start]
            if text:
                blocks.append(TextBlock(type="text", text=text))

        url = match.group("markdown_url") or match.group("plain_url") or ""
        alt = match.group("alt") or ""
        if url:
            blocks.append(_build_asset_block(url, alt))
        cursor = end

    if cursor < len(context):
        tail = context[cursor:]
        if tail:
            blocks.append(TextBlock(type="text", text=tail))

    if not blocks and context:
        blocks.append(TextBlock(type="text", text=context))

    return blocks