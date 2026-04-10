# -*- coding: utf-8 -*-
"""Two-stage background skill reviewer: generate draft -> validate -> save.

The reviewer is spawned as a fire-and-forget ``asyncio.Task`` after
the main agent completes a conversation turn whose weighted signal
score exceeds the configured threshold.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING

from .review_prompts import build_generator_prompt, build_validator_prompt
from .signal_accumulator import LearningSignals
from .skill_usage import SkillUsageTracker

if TYPE_CHECKING:
    from ...config.config import SkillLearningConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillDraft:
    """Immutable draft produced by the generator stage."""

    name: str
    description: str
    content: str
    action: Literal["create", "patch"]
    patch_target: Optional[str] = None
    old_string: Optional[str] = None
    new_string: Optional[str] = None


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str


class SkillReviewer:
    """Orchestrates the generate -> validate -> save pipeline."""

    def __init__(
        self,
        *,
        config: "SkillLearningConfig",
        skill_service: Any,
        workspace_dir: Path,
        agent_id: str,
        channel_manager: Optional[Any] = None,
        runner: Optional[Any] = None,
        usage_tracker: Optional[SkillUsageTracker] = None,
    ) -> None:
        self._config = config
        self._skill_service = skill_service
        self._workspace_dir = workspace_dir
        self._agent_id = agent_id
        self._channel_manager = channel_manager
        self._runner = runner
        self._usage_tracker = usage_tracker or SkillUsageTracker(
            workspace_dir / "skills",
        )
        self._semaphore = asyncio.Semaphore(1)

    async def maybe_review(
        self,
        *,
        messages_snapshot: list[dict],
        signals: LearningSignals,
    ) -> None:
        """Check threshold and spawn background review if met."""
        if not self._config.enabled:
            return

        score = signals.weighted_score(self._config.signal_weights)
        threshold = self._config.threshold

        if score < threshold:
            logger.debug(
                "skill_learning: skipped review"
                " (score=%d < threshold=%d)",
                score,
                threshold,
            )
            return

        if self._semaphore.locked():
            logger.debug(
                "skill_learning: review already running, skipping",
            )
            return

        logger.info(
            "skill_learning: review triggered"
            " (score=%d, threshold=%d, signals=%s)",
            score,
            threshold,
            signals,
        )

        task = asyncio.create_task(
            self._run_pipeline(messages_snapshot),
        )
        task.add_done_callback(self._on_review_done)

    def _on_review_done(self, task: asyncio.Task) -> None:
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.warning("skill_learning: review failed: %s", exc)

    async def _run_pipeline(
        self,
        messages_snapshot: list[dict],
    ) -> None:
        """Full pipeline with semaphore guard and timeout."""
        async with self._semaphore:
            try:
                await asyncio.wait_for(
                    self._generate_and_validate(messages_snapshot),
                    timeout=self._config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "skill_learning: review timed out"
                    " after %ds",
                    self._config.timeout_seconds,
                )

    async def _generate_and_validate(
        self,
        messages_snapshot: list[dict],
    ) -> None:
        """Stage 1: generate draft.  Stage 2: validate.  Stage 3: save."""
        draft = await self._generate_draft(messages_snapshot)
        if draft is None:
            return

        # Stage 2: validate (skip if no validator model configured)
        validated = True
        if self._config.validator_model is not None:
            result = await self._validate_draft(
                draft,
                messages_snapshot,
            )
            logger.debug(
                "skill_learning: validator result: %s",
                result,
            )
            if not result.passed:
                logger.warning(
                    "skill_learning: draft rejected"
                    " by validator: %s",
                    result.reason,
                )
                return
            validated = True

        # Stage 3: save
        await self._save_and_notify(draft, validated=validated)

    async def _generate_draft(
        self,
        messages_snapshot: list[dict],
    ) -> Optional[SkillDraft]:
        """Run the generator agent to produce a skill draft.

        This is a simplified implementation that constructs the draft
        by analysing the conversation.  A full implementation would
        instantiate a lightweight CoPawAgent with the generator model.
        """
        # Gather underperforming skills
        underperforming = self._usage_tracker.list_underperforming()

        # Build the generator prompt
        prompt = build_generator_prompt(underperforming or None)

        # For now, delegate to the runner if available
        if self._runner is None:
            logger.warning(
                "skill_learning: no runner available, skipping",
            )
            return None

        # Build a simple request
        conversation_summary = self._summarize_conversation(
            messages_snapshot,
        )
        req = {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Conversation context:\n"
                                + conversation_summary
                                + "\n\n"
                                + prompt
                            ),
                        },
                    ],
                },
            ],
            "session_id": "_skill_review",
            "user_id": "_system",
        }

        # Collect the response
        response_text = ""
        try:
            async for event in self._runner.stream_query(req):
                if isinstance(event, dict):
                    content = event.get("content", "")
                    if isinstance(content, str):
                        response_text += content
                elif isinstance(event, str):
                    response_text += event
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "skill_learning: generator failed: %s",
                exc,
            )
            return None

        if "nothing to save" in response_text.lower():
            logger.debug("skill_learning: nothing to save")
            return None

        # Try to extract a skill draft from the response
        return self._parse_draft(response_text)

    async def _validate_draft(
        self,
        draft: SkillDraft,
        messages_snapshot: list[dict],
    ) -> ValidationResult:
        """Run the validator model to check draft quality."""
        # List existing skills
        try:
            existing = self._skill_service.list_all_skills()
            skill_list = "\n".join(
                f"- {s.name}: {s.description}"
                for s in existing
            )
        except Exception:
            skill_list = "(unable to list)"

        conversation_tail = self._summarize_conversation(
            messages_snapshot,
            max_messages=20,
        )

        prompt = build_validator_prompt(
            skill_list=skill_list,
            draft_content=draft.content,
            conversation_tail=conversation_tail,
        )

        if self._runner is None:
            return ValidationResult(passed=True, reason="no validator")

        req = {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                },
            ],
            "session_id": "_skill_validate",
            "user_id": "_system",
        }

        response_text = ""
        try:
            async for event in self._runner.stream_query(req):
                if isinstance(event, dict):
                    content = event.get("content", "")
                    if isinstance(content, str):
                        response_text += content
                elif isinstance(event, str):
                    response_text += event
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "skill_learning: validator failed: %s",
                exc,
            )
            return ValidationResult(passed=True, reason=f"error: {exc}")

        response_lower = response_text.strip().lower()
        if response_lower.startswith("pass"):
            reason = response_text.strip().split(":", 1)[-1].strip()
            return ValidationResult(passed=True, reason=reason)
        if response_lower.startswith("fail"):
            reason = response_text.strip().split(":", 1)[-1].strip()
            return ValidationResult(passed=False, reason=reason)

        return ValidationResult(
            passed=True,
            reason="ambiguous response, allowing",
        )

    async def _save_and_notify(
        self,
        draft: SkillDraft,
        *,
        validated: bool = False,
    ) -> None:
        """Save skill via SkillService and send notification."""
        try:
            if draft.action == "create":
                self._skill_service.create_skill(
                    name=draft.name,
                    content=draft.content,
                    enable=True,
                )
                self._usage_tracker.init_meta(draft.name)
                logger.info(
                    "skill_learning: created skill '%s'"
                    " (validated=%s)",
                    draft.name,
                    validated,
                )
            elif draft.action == "patch" and draft.patch_target:
                self._skill_service.save_skill(
                    skill_name=draft.patch_target,
                    content=draft.content,
                )
                self._usage_tracker.record_revision(
                    draft.patch_target,
                    reason="auto-patched by skill reviewer",
                )
                logger.info(
                    "skill_learning: patched skill '%s'",
                    draft.patch_target,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "skill_learning: save failed: %s",
                exc,
            )
            return

        # Notification
        notify_text = (
            f"💾 Learned new skill: **{draft.name}**"
            f"\n_{draft.description}_"
        )
        await self._dispatch_notification(notify_text)

    async def _dispatch_notification(self, text: str) -> None:
        """Send notification based on config.notify setting."""
        notify = self._config.notify
        if notify == "main" or self._channel_manager is None:
            return  # console-only, already logged

        try:
            if notify == "last":
                from ...config.config import load_agent_config

                agent_config = load_agent_config(self._agent_id)
                ld = agent_config.last_dispatch
                if ld and ld.channel and (ld.user_id or ld.session_id):
                    await self._channel_manager.send_text(
                        channel=ld.channel,
                        user_id=ld.user_id,
                        session_id=ld.session_id,
                        text=text,
                    )
            else:
                # Treat as channel ID
                await self._channel_manager.send_text(
                    channel=notify,
                    user_id="",
                    session_id="main",
                    text=text,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "skill_learning: notification failed: %s",
                exc,
            )

    # -- helpers --

    @staticmethod
    def _summarize_conversation(
        messages: list[dict],
        max_messages: int = 30,
    ) -> str:
        """Build a text summary of the last N messages."""
        recent = messages[-max_messages:]
        lines: list[str] = []
        for msg in recent:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                content = " ".join(text_parts)
            if isinstance(content, str):
                content = content[:500]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_draft(response: str) -> Optional[SkillDraft]:
        """Try to extract a SkillDraft from generator response text."""
        # Look for YAML frontmatter block
        import re

        fm_match = re.search(
            r"---\s*\n(.*?)\n---",
            response,
            re.DOTALL,
        )
        if not fm_match:
            # Try to extract name and description from text
            name_match = re.search(
                r"(?:name|skill):\s*[\"']?(\S+)[\"']?",
                response,
                re.IGNORECASE,
            )
            if not name_match:
                return None
            name = name_match.group(1).strip().lower()
            name = re.sub(r"[^a-z0-9-]", "-", name)[:64]
            return SkillDraft(
                name=name,
                description=response[:200],
                content=response,
                action="create",
            )

        # Has frontmatter
        import yaml  # pylint: disable=import-outside-toplevel

        try:
            fm = yaml.safe_load(fm_match.group(1))
        except Exception:
            return None

        if not isinstance(fm, dict):
            return None

        name = str(fm.get("name", "unnamed")).strip().lower()
        name = re.sub(r"[^a-z0-9-]", "-", name)[:64]
        description = str(fm.get("description", ""))[:200]

        return SkillDraft(
            name=name,
            description=description,
            content=response.strip(),
            action="create",
        )
