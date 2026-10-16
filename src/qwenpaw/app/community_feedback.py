# -*- coding: utf-8 -*-
"""Resolve installer identities to the community's public resource IDs.

The public marketplace uses @owner/name; the question editor uses plugin_id
for plugins/apps and a UUID for skills. Never match by display name or send
unrecognised version/body query parameters to the editor.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode, urlsplit

import httpx

from ..installation_origin import validated_origin

PLATFORM_URL = "https://platform.agentscope.io"
COMMUNITY_URL = f"{PLATFORM_URL}/community"


class FeedbackLinkError(ValueError):
    """A resource cannot safely be associated with a community question."""


def _data(body: object) -> dict:
    if not isinstance(body, dict) or body.get("success") is False:
        raise FeedbackLinkError(
            "The community could not resolve this resource",
        )
    data = body.get("data", body)
    if not isinstance(data, dict):
        raise FeedbackLinkError("Invalid community resource response")
    return data


def _detail_id(url: object, collection: str) -> str:
    if not isinstance(url, str):
        raise FeedbackLinkError("The resource has no community details page")
    parsed = urlsplit(url)
    prefix = f"/{collection}/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "platform.agentscope.io"
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(prefix)
    ):
        raise FeedbackLinkError("Invalid community details address")
    identifier = parsed.path[len(prefix) :]
    if not identifier or any(c in identifier for c in "/%?#\\"):
        raise FeedbackLinkError("Invalid community resource identifier")
    return identifier


async def resolve_feedback_link(
    origin: dict,
    client: httpx.AsyncClient,
) -> str:
    """Resolve an exact platform identity using public first-party APIs."""
    record = validated_origin(origin)
    if record is None:
        raise FeedbackLinkError("A verified platform installation is required")
    resource_type = record["resource_type"]
    resource_id = record["resource_id"]
    collection = "skills" if resource_type == "skill" else "plugins"
    target_id = resource_id
    if resource_id.startswith("@"):
        # Search narrows the response; only an exact stable-ID match is used.
        target_id = ""
        for page in range(1, 11):
            response = await client.get(
                f"{PLATFORM_URL}/openapi/v1/{collection}",
                params={
                    "search": resource_id.rsplit("/", 1)[-1],
                    "page_number": page,
                    "page_size": 100,
                },
            )
            response.raise_for_status()
            data = _data(response.json())
            items = data.get(collection)
            if not isinstance(items, list):
                raise FeedbackLinkError("Invalid marketplace response")
            matches = [
                item
                for item in items
                if isinstance(item, dict) and item.get("id") == resource_id
            ]
            if len(matches) > 1:
                raise FeedbackLinkError(
                    "The marketplace identity is ambiguous",
                )
            if matches:
                target_id = _detail_id(
                    matches[0].get("details_url"),
                    collection,
                )
                break
            total = data.get("total")
            if not items or (isinstance(total, int) and page * 100 >= total):
                break
        if not target_id:
            raise FeedbackLinkError(
                "This installed resource is no longer available",
            )

    response = await client.get(
        f"{PLATFORM_URL}/api/v1/{collection}/{quote(target_id, safe='')}",
    )
    response.raise_for_status()
    detail = _data(response.json())
    is_skill = resource_type == "skill"
    identity_key = "id" if is_skill else "plugin_id"
    if detail.get(identity_key) != target_id:
        raise FeedbackLinkError(
            "The community resource identity does not match",
        )
    if not is_skill:
        tech_type = detail.get("tech_type")
        is_app = isinstance(tech_type, dict) and tech_type.get("code") == "app"
        if (resource_type == "app") != is_app:
            raise FeedbackLinkError(
                "The installed resource type does not match",
            )
    query = {"relatedSkillId" if is_skill else "relatedPluginId": target_id}
    return f"{COMMUNITY_URL}/ask?{urlencode(query)}"
