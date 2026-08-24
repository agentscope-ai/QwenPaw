#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproduce retained ReMe index growth from repeated Markdown updates."""
# pylint: disable=protected-access

from __future__ import annotations

import argparse
import asyncio
import gc
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import psutil
from reme import ReMe
from reme.enumeration import ComponentEnum

from qwenpaw.agents.memory.reme_config import _base_config


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument("--directory-count", type=int, default=980)
    parser.add_argument("--lines-per-update", type=int, default=40)
    parser.add_argument("--compact-every", type=int, default=0)
    return parser.parse_args()


def _application(workspace: Path) -> ReMe:
    config = _base_config()
    config["components"]["file_store"]["default"]["embedding_store"] = ""
    config["components"].pop("embedding_store")
    config["components"].pop("as_embedding")
    config.update(
        workspace_dir=str(workspace),
        metadata_dir=".reme",
        session_dir="sessions",
        mem_session_dir="mem_session",
        resource_dir="resource",
        daily_dir="memory",
        digest_dir="digest",
        language="zh",
        timezone="Asia/Shanghai",
        enable_logo=False,
        log_to_console=False,
    )
    return ReMe(**config)


def _component(app: ReMe, kind: ComponentEnum) -> Any:
    return app.context.components[kind]["default"]


def _index_bytes(index: Any) -> int:
    arrays = [index._doc_lens, index._deleted]
    arrays.extend(index._doc_token_ids)
    arrays.extend(index._posting_doc_idxs.values())
    arrays.extend(index._posting_tfs.values())
    return sum(array.nbytes for array in arrays)


def _report(label: str, index: Any, baseline_rss: int) -> None:
    rss = psutil.Process(os.getpid()).memory_info().rss
    deleted = int(index._deleted.sum())
    print(
        f"{label}: rss_delta_mib={(rss - baseline_rss) / 2**20:.1f} "
        f"live_docs={index.n_docs} allocated_docs={len(index._doc_ids)} "
        f"deleted_docs={deleted} arrays_mib={_index_bytes(index) / 2**20:.1f}",
    )


async def _run(args: argparse.Namespace) -> None:
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="qwenpaw-reme-memory-") as root:
        workspace = Path(root)
        memory_dir = workspace / "memory"
        memory_dir.mkdir()
        note = memory_dir / "2026-08-22.md"
        paths = [
            f"D:/HuaweiFamilyArchive/category-{idx:04d}/document.md"
            for idx in range(args.directory_count)
        ]
        content = ["# 2026-08-22", "", "## Directory inventory", *paths]

        app = _application(workspace)
        tokenizer = _component(app, ComponentEnum.TOKENIZER)
        graph = _component(app, ComponentEnum.FILE_GRAPH)
        keyword = _component(app, ComponentEnum.KEYWORD_INDEX)
        store = _component(app, ComponentEnum.FILE_STORE)
        chunker = app.context.components[ComponentEnum.FILE_CHUNKER][
            "markdown"
        ]
        for component in (tokenizer, graph, keyword, store):
            await component.start()

        process = psutil.Process(os.getpid())
        baseline_rss = process.memory_info().rss
        _report("start", keyword, baseline_rss)
        for iteration in range(1, args.iterations + 1):
            content.append(f"\n## Completed turn {iteration}")
            content.extend(
                f"- archived item {iteration:04d}-{line:04d}"
                for line in range(args.lines_per_update)
            )
            note.write_text("\n".join(content), encoding="utf-8")
            await store.upsert([await chunker.chunk(note)])
            if args.compact_every > 0 and iteration % args.compact_every == 0:
                await store.optimize_index()
            if iteration in {1, args.iterations // 2, args.iterations}:
                gc.collect()
                _report(f"update-{iteration}", keyword, baseline_rss)

        await store.optimize_index()
        gc.collect()
        _report("after-final-compact", keyword, baseline_rss)
        await store.close()


def main() -> None:
    asyncio.run(_run(_arguments()))


if __name__ == "__main__":
    main()
