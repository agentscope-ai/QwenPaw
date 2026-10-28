# -*- coding: utf-8 -*-
"""Read file-level tag relationships from the running ReMe index."""

from typing import Any

# Unicode casefold expands a source character to at most three characters.
# ReMe limits source tags to 64 characters, before applying casefold.
MAX_MEMORY_TAG_QUERY_LENGTH = 64 * 3


def _file_location(reme: Any, path: str) -> dict[str, str]:
    """Reuse the existing daily/digest editor identities for indexed files."""
    roots = sorted(
        (
            ("daily", reme.config.daily_dir),
            ("digest", reme.config.digest_dir),
        ),
        key=lambda item: len(item[1].strip("/")),
        reverse=True,
    )
    for source, directory in roots:
        root = directory.replace("\\", "/").strip("/")
        prefix = root + "/" if root else ""
        if path.startswith(prefix):
            return {"source": source, "relative_path": path[len(prefix) :]}
    return {"source": "workspace", "relative_path": path}


async def list_tag_files(
    reme: Any,
    *,
    tag: str,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Return complete files rather than ranked search chunks.

    The caller holds the manager's ReMe lifecycle lease throughout this read.
    File metadata comes from the existing catalog, without reading file bodies.
    """
    store = reme.context.components["file_store"]["default"]
    index = store.require_tag_index()
    if not index.is_healthy:
        raise RuntimeError("Memory tag index is unavailable")
    raw = "_".join(tag.split())
    canonical = raw.casefold()
    if (
        not raw
        or len(raw) > MAX_MEMORY_TAG_QUERY_LENGTH
        or not any(char.isalnum() for char in raw)
    ):
        raise ValueError("Tag must contain a valid memory tag")
    if len(raw) <= index.max_tag_length:
        # Pass the source spelling: ReMe normalizes queries itself, and a
        # second normalization would reject an expanded canonical tag.
        paths = await index.paths_for_tags([raw])
        nodes = await store.get_nodes(paths) if paths else []
    else:
        # ReMe 0.4.2.0 can list canonical keys that its query length check
        # rejects. Match those rare expanded keys against catalog metadata;
        # this reads no file bodies and does not modify the running index.
        nodes = [
            node
            for node in await store.get_nodes()
            if canonical
            in index.normalize_tags(
                (node.front_matter.model_extra or {}).get(index.tag_key),
            )
        ]
    if not index.is_healthy:
        raise RuntimeError("Memory tag index is unavailable")
    nodes.sort(key=lambda node: (-node.st_mtime, node.path))
    start = (page - 1) * page_size
    return {
        "tag": canonical,
        "total_files": len(nodes),
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "path": node.path,
                **_file_location(reme, node.path),
                "name": node.front_matter.name,
                "description": node.front_matter.description,
                "modified_at": node.st_mtime,
                "memory_tags": index.normalize_tags(
                    (node.front_matter.model_extra or {}).get(index.tag_key),
                ),
            }
            for node in nodes[start : start + page_size]
        ],
    }
