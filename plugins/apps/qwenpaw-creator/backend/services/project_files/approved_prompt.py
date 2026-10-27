# -*- coding: utf-8 -*-
"""Resolve the stored prompt a legacy specialist approval actually displays."""

from domain.errors import ConflictError
from .json_pointer import escape_pointer_token


def saved_authorization_prompt(project, authorization):
    if len(authorization.target_scope) != 1:
        raise ConflictError("此授权没有唯一的提示词目标")
    target = authorization.target_scope[0]
    operation = authorization.operation
    parameters = (authorization.scope or {}).get("parameters") or {}
    pointer = None
    prompt = None
    if target.startswith("element:"):
        element_id = target.removeprefix("element:")
        field = {
            "image_generation": "storyboard_prompt",
            "r2v_generation": "video_prompt",
        }.get(operation)
        for timeline_id, timeline in project.timelines.items.items():
            if field and element_id in timeline.elements_by_id:
                element = timeline.elements_by_id[element_id]
                prompt = getattr(element.creation, field, None)
                pointer = (
                    f"/timelines/items/{escape_pointer_token(timeline_id)}"
                    f"/elements_by_id/{escape_pointer_token(element_id)}"
                    f"/creation/{field}"
                )
                break
    elif target.startswith("asset:") and operation == "image_generation":
        entity_id = target.removeprefix("asset:")
        entity = project.visual.entities.items.get(entity_id)
        variant_id = parameters.get("variantId")
        if entity and not variant_id and len(entity.variants.order) == 1:
            variant_id = entity.variants.order[0]
        if entity and variant_id in entity.variants.items:
            prompt = entity.variants.items[variant_id].prompt
            pointer = (
                f"/visual/entities/items/{escape_pointer_token(entity_id)}"
                f"/variants/items/{escape_pointer_token(variant_id)}/prompt"
            )
    if not pointer or not isinstance(prompt, str) or not prompt.strip():
        raise ConflictError("请先保存此生成目标的提示词，再重新确认。")
    return {"pointer": pointer, "prompt": prompt}


def saved_prompt_is_current(snapshot, authorization) -> bool:
    """The approval still describes the stored prompt.

    The saved ETag is only a fast path: unrelated writes (task results,
    auto-saved drafts elsewhere) must not void an approval whose prompt text
    is byte-identical, while any change to the prompt itself does.
    """
    saved = (authorization.decision or {}).get("savedPrompt")
    if not saved:
        return True
    if snapshot.etag == saved.get("etag"):
        return True
    try:
        current = saved_authorization_prompt(snapshot.project, authorization)
    except ConflictError:
        return False
    return current == {key: saved.get(key) for key in ("pointer", "prompt")}


def approved_specialist_arguments(snapshot, authorization, arguments):
    saved = (authorization.decision or {}).get("savedPrompt")
    if not saved:
        return arguments
    if not saved_prompt_is_current(snapshot, authorization):
        raise ConflictError("批准后的提示词已改变，请按最新内容重新请求授权。")
    return {
        **arguments,
        "arguments": {
            **(arguments.get("arguments") or {}),
            "prompt": saved["prompt"],
        },
    }
