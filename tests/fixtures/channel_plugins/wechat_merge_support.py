"""Real independent generic owner built from the existing executable example.

Only descriptor configuration is extended. The existing Driver, journal,
Loader, proxy and process remain real; this never substitutes a WeChat Driver.
"""

import json

from extension_sample import sample_source
from extension_process_suite import inspect, open_route


def merge_source(directory, key, *, capabilities=None):
    source = sample_source(directory, key, capabilities=capabilities)
    path = source / "channel.json"
    data = json.loads(path.read_text())
    policy = data["config_schema"]["properties"]["route_policies"][
        "additionalProperties"
    ]
    policy["properties"]["text_merge_delay_ms"] = {
        "type": ["integer", "null"],
        "minimum": 0,
        "maximum": 2**63 - 1,
    }
    path.write_text(json.dumps(data))
    return source


def merge_policy(delay):
    return {
        "streaming": False,
        "prepare": False,
        "completion_reaction": False,
        "text_merge_delay_ms": delay,
    }


async def merge_runtime(
    runtime,
    *,
    delay=0,
    opted_in=True,
    extra_capabilities=(),
    source_factory=merge_source,
    **settings,
):
    caps = ["channel.generic.v1", "media", "reaction", "streaming"]
    if opted_in:
        caps.append("channel.text_merge.v1")
    caps.extend(extra_capabilities)
    rt = await runtime(
        "independent_merge_owner",
        source_factory=source_factory,
        capabilities=sorted(caps),
        route_policies={
            room: merge_policy(delay) for room in ("room-A", "room-B")
        },
        **settings,
    )
    return rt


async def route(rt, room="room-A"):
    return rt.channel.to_handle_from_target(
        user_id="member", session_id=room
    ), {"response_handle": await open_route(rt, room)}


async def sends(rt):
    return [
        row
        for row in (await inspect(rt))["effects"]
        if row["operation"] == "message.create"
    ]
