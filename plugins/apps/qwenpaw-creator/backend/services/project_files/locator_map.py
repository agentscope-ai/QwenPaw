# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""Map a committed JSON pointer to a frontend navigation locator.

Every review operation carries a ``ui_locator`` so the AgentDock review panel
can (a) jump the user to the place the change lives and (b) render the right
kind of diff/preview.  Text edits point at a Plan/Element field (matched in
the DOM by ``data-creator-path`` == the JSON pointer); generated media points
at the place it was produced: a storyboard/video Element workbench or a
character asset detail page.

The mapping is intentionally derived from the *committed* Project document so a
locator always reflects real, current entities (slot owners, artifact kinds and
media types) rather than guessing from the pointer string alone.
"""

from __future__ import annotations

from typing import Any, Mapping


def _unescape_token(token: str) -> str:
    # RFC 6901: ``~1`` -> ``/`` and ``~0`` -> ``~`` (order matters).
    return token.replace("~1", "/").replace("~0", "~")


def _split_pointer(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        return []
    return [_unescape_token(token) for token in pointer[1:].split("/")]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _assets(project: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(project.get("assets"))


def _media_kind(artifact_kind: str, media_type: str) -> str:
    if media_type.startswith("video") or "video" in artifact_kind:
        return "video"
    if media_type.startswith("image") or "image" in artifact_kind:
        return "image"
    # Fall back to image: storyboards/character art are the common case and a
    # still preview is always safe to render.
    return "image"


def _owner_locator(owner_ref: str) -> dict[str, str]:
    if owner_ref.startswith("element:"):
        return {"page": "element", "elementId": owner_ref.split(":", 1)[1]}
    if owner_ref.startswith("asset:"):
        return {"page": "assets", "assetId": owner_ref.split(":", 1)[1]}
    return {"page": "plan"}


def _media_locator(
    *,
    owner_ref: str,
    artifact_kind: str,
    version_id: str | None,
    media_type: str,
) -> dict[str, str]:
    locator = _owner_locator(owner_ref)
    locator["mediaType"] = _media_kind(artifact_kind, media_type)
    if artifact_kind:
        locator["artifactKind"] = artifact_kind
    if version_id:
        locator["artifactVersionId"] = version_id
    return locator


def _file_media_type(assets: Mapping[str, Any], file_id: str | None) -> str:
    if not file_id:
        return ""
    file_record = _mapping(_mapping(assets.get("files_by_id")).get(file_id))
    media_type = file_record.get("media_type")
    return media_type if isinstance(media_type, str) else ""


def _version_locator(
    assets: Mapping[str, Any],
    version_id: str,
) -> dict[str, str]:
    version = _mapping(
        _mapping(assets.get("artifact_versions_by_id")).get(version_id),
    )
    if not version:
        return {"mediaType": "image", "artifactVersionId": version_id}
    return _media_locator(
        owner_ref=str(version.get("owner_ref") or ""),
        artifact_kind=str(version.get("kind") or ""),
        version_id=version_id,
        media_type=_file_media_type(assets, version.get("file_id")),
    )


def _slot_locator(
    assets: Mapping[str, Any],
    slot_id: str,
) -> dict[str, str]:
    slot = _mapping(_mapping(assets.get("artifact_slots_by_id")).get(slot_id))
    if not slot:
        return {"mediaType": "image"}
    selected = slot.get("selected_version_id")
    selected_id = selected if isinstance(selected, str) else None
    media_type = ""
    if selected_id is not None:
        version = _mapping(
            _mapping(assets.get("artifact_versions_by_id")).get(selected_id),
        )
        media_type = _file_media_type(assets, version.get("file_id"))
    return _media_locator(
        owner_ref=str(slot.get("owner_ref") or ""),
        artifact_kind=str(slot.get("kind") or ""),
        version_id=selected_id,
        media_type=media_type,
    )


def _file_locator(
    assets: Mapping[str, Any],
    file_id: str,
) -> dict[str, str]:
    versions = _mapping(assets.get("artifact_versions_by_id"))
    for version_id, version in versions.items():
        if _mapping(version).get("file_id") == file_id:
            return _version_locator(assets, version_id)
    media_type = _file_media_type(assets, file_id)
    return {"mediaType": _media_kind("", media_type)}


def derive_ui_locator(
    pointer: str | None,
    project: Mapping[str, Any],
) -> dict[str, str]:
    """Return a frontend locator for one committed JSON pointer.

    ``project`` is the committed Project as a JSON-mode mapping.  An empty dict
    is returned when the pointer cannot be classified; callers treat that as
    "no jump target".
    """

    if not pointer:
        return {}
    tokens = _split_pointer(pointer)
    if not tokens:
        return {}

    if tokens[0] == "assets" and len(tokens) >= 3:
        assets = _assets(project)
        collection, entity_id = tokens[1], tokens[2]
        if collection == "artifact_versions_by_id":
            return _version_locator(assets, entity_id)
        if collection == "artifact_slots_by_id":
            return _slot_locator(assets, entity_id)
        if collection == "files_by_id":
            return _file_locator(assets, entity_id)
        return {}

    if (
        len(tokens) >= 5
        and tokens[0] == "timelines"
        and tokens[1] == "items"
        and tokens[3] == "elements_by_id"
    ):
        return {
            "page": "plan",
            "mediaType": "text",
            "elementId": tokens[4],
            "field": pointer,
        }

    # Top-level Project prose (name/description/strategy/visual/...).  These
    # live on the Plan page and are matched in the DOM by data-creator-path.
    return {"page": "plan", "mediaType": "text", "field": pointer}


__all__ = ["derive_ui_locator"]
