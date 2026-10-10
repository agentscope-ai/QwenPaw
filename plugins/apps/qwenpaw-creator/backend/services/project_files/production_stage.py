# -*- coding: utf-8 -*-
"""User-owned script/media boundary, independent of automation settings."""

from domain.errors import ValidationError
from .prompt_sync import digest


SCRIPT_ONLY_MESSAGE = "请先确认当前剧本并允许生成图片／视频；当前项目仅进行剧本创作。"
PRODUCTION_STAGE_POINTER = "/settings/production_stage"
SCRIPT_APPROVAL_POINTER = "/settings/script_approval_fingerprint"


def _document(document):
    if hasattr(document, "model_dump"):
        return document.model_dump(mode="json")
    return document


def _live_timelines(document):
    timelines = document.get("timelines", {})
    for timeline_id in timelines.get("order", []):
        timeline = timelines.get("items", {}).get(timeline_id)
        if timeline and not timeline_id.startswith("snapshot:"):
            yield timeline_id, timeline


def script_inputs(document):
    """Timeline-level script only.

    Shot breakdown and per-shot direction (elements, intent, continuity) are
    media-stage planning that follows script confirmation; including them
    would re-pause production on the first storyboard plan.
    """
    document = _document(document)
    scripts = {}
    for slot in (
        document.get("assets", {}).get("artifact_slots_by_id", {}).values()
    ):
        if slot.get("kind") == "timeline_script":
            scripts[slot.get("owner_ref")] = slot.get("selected_version_id")
    return [
        {
            "id": timeline_id,
            "title": timeline.get("title"),
            "synopsis": timeline.get("synopsis"),
            "description": timeline.get("description"),
            "script": scripts.get(f"timeline:{timeline_id}"),
        }
        for timeline_id, timeline in _live_timelines(document)
    ]


def script_fingerprint(document):
    return digest(script_inputs(document))


def _has_script_content(document):
    """Confirmation needs a script somewhere, including element-only ones."""
    document = _document(document)
    for row in script_inputs(document):
        if row["script"] or str(row["description"] or "").strip():
            return True
    for _, timeline in _live_timelines(document):
        for element_id, element in timeline.get("elements_by_id", {}).items():
            creation = element.get("creation") or {}
            if (
                not element_id.startswith("snapshot:")
                and str(
                    creation.get("narrative") or creation.get("intent") or "",
                ).strip()
            ):
                return True
    return False


def derive_production_stage(before, after):
    """Derive approval under the commit lock from current script content."""
    old = before.get("settings", {})
    settings = after["settings"]
    stage = settings.get("production_stage", "media")
    old_stage = old.get("production_stage", "media")
    approved = old.get("script_approval_fingerprint")
    if stage != old_stage:
        if stage == "media":
            if not _has_script_content(after):
                raise ValidationError("请先发布剧本内容，再确认生成图片／视频。")
            approved = script_fingerprint(after)
        else:
            approved = None
    elif approved and approved != script_fingerprint(after):
        settings["production_stage"] = "script"
        approved = None
    settings["script_approval_fingerprint"] = approved


def assert_media_production_allowed(project):
    if project.settings.production_stage == "script":
        raise ValidationError(SCRIPT_ONLY_MESSAGE)
