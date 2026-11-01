# -*- coding: utf-8 -*-
"""Exercise the tag pipeline and real indexes without provider calls."""

import asyncio

import pytest

from qwenpaw.agents.memory.reme_config import get_reme_app_config
from qwenpaw.agents.memory.reme_light_memory_manager import (
    _load_validated_reme_app,
)
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.agents.memory.reme_tags import list_tag_files

pytestmark = [pytest.mark.integration, pytest.mark.p1]


@pytest.mark.asyncio
async def test_tagged_memory_is_discoverable_and_filterable(
    tmp_path,
    monkeypatch,
):
    from reme.steps.evolve.auto_memory import AutoMemoryStep
    from reme.steps.evolve.auto_tag import AutoTagStep

    cfg = get_reme_app_config(
        working_dir=str(tmp_path),
        agent_config=AgentProfileConfig(id="tag-test", name="Tag test"),
    )
    cfg["components"]["as_llm"]["default"]["credential"] = {
        "api_key": "offline-test-key",
    }
    cfg.update(log_to_console=False, log_to_file=False, enable_logo=False)
    cfg["jobs"]["index_update_loop"]["steps"][1].update(
        force_polling=True,
        poll_delay_ms=20,
        step=10,
        debounce=50,
    )
    note_path = f"{cfg['daily_dir']}/2026-10-23/orion.md"

    async def write_memory(step):
        path = tmp_path / note_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nname: Orion\ndescription: Orion project owner\n---\n"
            "赵六 owns the Orion project.\n",
            encoding="utf-8",
        )
        step.context["changes"] = [{"path": note_path, "change": "added"}]
        step.context.response.metadata["modified"] = True
        return step.context.response

    async def generate_tags(step, target):
        # Replace the LLM interaction; retain real frontmatter and index jobs.
        response = await step.run_job(
            "frontmatter_update",
            path=target.path,
            metadata={"memory_tags": ["赵六", "Orion"]},
        )
        assert response.success, response.answer
        return "Tagged Orion owner"

    monkeypatch.setattr(AutoMemoryStep, "execute", write_memory)
    monkeypatch.setattr(AutoTagStep, "_process_target", generate_tags)
    app = _load_validated_reme_app()(**cfg)
    try:
        await app.start()
        plain = await app.run_job("auto_memory", messages=[])
        assert plain.success, plain.answer
        assert "auto_tag" not in plain.metadata
        assert "memory_tags" not in (tmp_path / note_path).read_text(
            encoding="utf-8",
        )

        tagged = await app.run_job("auto_memory_with_tags", messages=[])
        assert tagged.success, tagged.answer
        assert tagged.metadata["auto_tag"]["succeeded"] == 1
        async with asyncio.timeout(10):
            while True:
                listed = await app.run_job("list_tags")
                if listed.answer["items"]:
                    break
                await asyncio.sleep(0.05)
        assert listed.success, listed.answer
        assert ("赵六", 1) in listed.answer["items"]
        browsed = await list_tag_files(app, tag="赵六")
        assert browsed["total_files"] == 1
        assert browsed["items"][0]["path"] == note_path
        assert browsed["items"][0]["memory_tags"] == ["赵六", "orion"]

        found = await app.run_job("search", query="Orion", tags=["赵六"])
        assert found.success, found.answer
        assert "orion.md" in found.answer
        all_memories = await app.run_job("search", query="Orion")
        assert "orion.md" in all_memories.answer
        excluded = await app.run_job("search", query="Orion", tags=["missing"])
        assert "orion.md" not in str(excluded.answer)
    finally:
        await app.close()
