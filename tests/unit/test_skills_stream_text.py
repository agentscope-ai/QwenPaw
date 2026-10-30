"""Skill optimization must consume the current AgentScope response blocks."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentscope.message import TextBlock, ThinkingBlock
from agentscope.model import ChatResponse
from qwenpaw.app.routers import skills_stream


class SkillStreamTextTests(unittest.IsolatedAsyncioTestCase):
    def test_candidate_and_typed_text_blocks(self):
        expected = (
            Path(__file__).resolve().parents[2]
            / "src/qwenpaw/app/routers/skills_stream.py"
        )
        self.assertEqual(Path(skills_stream.__file__).resolve(), expected)
        response = ChatResponse(
            content=[
                ThinkingBlock(thinking="private reasoning"),
                TextBlock(text="first "),
                TextBlock(text="second"),
            ],
            is_last=True,
        )
        self.assertEqual(
            skills_stream._extract_text_from_chunk(response), "first second"
        )
        self.assertEqual(
            skills_stream._extract_text_from_response(response), "first second"
        )

    def test_legacy_text_and_nontext_content(self):
        self.assertEqual(
            skills_stream._extract_text_from_chunk(
                SimpleNamespace(
                    content=[
                        {"type": "thinking", "text": "hidden"},
                        {"type": "text", "text": "visible"},
                    ]
                )
            ),
            "visible",
        )
        self.assertEqual(
            skills_stream._extract_text_from_response("legacy"), "legacy"
        )
        self.assertEqual(
            skills_stream._extract_text_from_response(
                SimpleNamespace(text="legacy")
            ),
            "legacy",
        )

    async def test_no_text_is_an_error_instead_of_empty_success(self):
        async def model(_messages):
            return ChatResponse(content=[], is_last=True)

        async def get_model():
            return model

        with patch.object(skills_stream, "get_model", get_model):
            response = await skills_stream.ai_optimize_skill_stream(
                skills_stream.AIOptimizeSkillRequest(content="synthetic draft")
            )
            events = [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]
        self.assertTrue(any("error" in event for event in events))
        self.assertFalse(any(event.get("done") for event in events))

    async def test_delta_chunks_are_appended_and_final_snapshot_is_not_duplicated(
        self,
    ):
        async def chunks():
            for text, last in [("ab", False), ("cde", False), ("abcde", True)]:
                yield ChatResponse(
                    content=[TextBlock(text=text)], is_last=last
                )

        async def model(_messages):
            return chunks()

        async def get_model():
            return model

        with patch.object(skills_stream, "get_model", get_model):
            response = await skills_stream.ai_optimize_skill_stream(
                skills_stream.AIOptimizeSkillRequest(content="synthetic draft")
            )
            events = [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]
        self.assertEqual(
            "".join(event.get("text", "") for event in events), "abcde"
        )
        self.assertEqual(
            [event["text"] for event in events if "text" in event],
            ["ab", "cde"],
        )
        self.assertEqual(events[-1], {"done": True})

    async def test_leading_whitespace_does_not_hide_skill_frontmatter(self):
        raw = "\n  ---\nname: synthetic\ndescription: test\n---\n\n  body"

        async def chunks():
            for text, last in [("\n ", False), (raw[2:], False), (raw, True)]:
                yield ChatResponse(
                    content=[TextBlock(text=text)], is_last=last
                )

        async def model(_messages):
            return chunks()

        async def get_model():
            return model

        with patch.object(skills_stream, "get_model", get_model):
            response = await skills_stream.ai_optimize_skill_stream(
                skills_stream.AIOptimizeSkillRequest(content="synthetic draft")
            )
            events = [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]
        self.assertEqual(
            "".join(event.get("text", "") for event in events), raw.lstrip()
        )
        self.assertEqual(events[-1], {"done": True})


if __name__ == "__main__":
    unittest.main()
