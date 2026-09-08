# -*- coding: utf-8 -*-
"""Read story readiness from existing published project content."""

from services.project_files.models import Project, narrative_timeline_ids

STORY_BEFORE_VISUAL_MESSAGE = "请先在剧集蓝图发布剧情梗概或剧本，再生成角色与场景。"


def has_published_story(project: Project, timeline_id: str) -> bool:
    timeline = project.timelines.items[timeline_id]
    if timeline.synopsis.strip() or timeline.description.strip():
        return True
    for slot in project.assets.artifact_slots_by_id.values():
        if (
            slot.kind != "timeline_script"
            or slot.owner_ref != f"timeline:{timeline_id}"
        ):
            continue
        version = project.assets.artifact_versions_by_id.get(
            slot.selected_version_id,
        )
        if version is not None and not version.stale:
            return True
    # Older projects already express their story through authored elements.
    # A bare title, prompt, user brief or snapshot is not story publication.
    return any(
        element.enabled
        and (
            str(getattr(element.creation, "narrative", "") or "").strip()
            or str(getattr(element.creation, "intent", "") or "").strip()
        )
        for element in timeline.elements_by_id.values()
    )


def visual_story_missing(project: Project, entity_id: str) -> bool:
    """Shared assets need story context; scoped assets use their own episodes.

    An unrelated unwritten episode must not stop an already authored episode
    from progressing. Unbound shared visual development can start once a
    live episode has published its story. Asset-only/editing projects keep
    their existing workflow.
    """
    if project.scenario != "short_drama":
        return False
    live_ids = narrative_timeline_ids(project)
    referenced_ids = []
    for timeline_id in live_ids:
        for element in project.timelines.items[
            timeline_id
        ].elements_by_id.values():
            if not element.enabled:
                continue
            creation = element.creation
            refs = [
                *getattr(creation, "character_refs", ()),
                *getattr(creation, "prop_refs", ()),
                getattr(creation, "scene_ref", None),
                getattr(creation, "character_ref", None),
            ]
            if entity_id in refs:
                referenced_ids.append(timeline_id)
                break
    if referenced_ids:
        return any(
            not has_published_story(project, tid) for tid in referenced_ids
        )
    return not any(has_published_story(project, tid) for tid in live_ids)
