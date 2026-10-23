"""OneBot's legacy order oracle at a real generic Proxy/worker boundary."""
import os
import json

import pytest

from semantic_event_host_suite import semantic_source

pytest_plugins = ['extension_process_suite']


def ordered_source(directory, key, *, capabilities=None):
    """Expose the public policy through normal sample config, not a mock."""
    source = semantic_source(directory, key, capabilities=capabilities)
    path = source / 'channel.json'
    descriptor = json.loads(path.read_text())
    route = descriptor['config_schema']['properties']['route_policies']['additionalProperties']
    route['properties']['send_format'] = {
        'type': 'object',
        'properties': {name: {'type': 'boolean'} for name in (
            'direct_prefix', 'parts_configured_prefix', 'parts_metadata_prefix',
            'stream_prefix', 'parts_strip_text', 'parts_preserve_order')},
        'required': ['direct_prefix', 'parts_configured_prefix'],
        'additionalProperties': False,
    }
    path.write_text(json.dumps(descriptor))
    return source


def ordered_policy(**overrides):
    return {'streaming': False, 'prepare': False, 'completion_reaction': False,
            'send_format': {'direct_prefix': True, 'parts_configured_prefix': True,
                            'parts_preserve_order': True, **overrides}}


@pytest.mark.asyncio
async def test_explicit_text_file_text_preserves_order_through_actual_proxy_worker(runtime):
    # Ordinary third-party sample owner: no OneBot builtin owner bypass and
    # no Agent execution. The worker records its real send effect parameters.
    rt = await runtime(source_factory=ordered_source, route_policies={'room-A': ordered_policy()})
    target = rt.channel.to_handle_from_target(user_id='member', session_id='room-A')
    parts = [
        {'type': 'text', 'text': 'before'},
        {'type': 'file', 'file_url': 'https://files.test/a.txt', 'filename': 'a.txt'},
        {'type': 'text', 'text': 'after'},
    ]
    await rt.channel.send_content_parts(target, parts, {})
    state = await rt.process.call('fixture.inspect', {})
    effects = [row for row in state['effects'] if row['operation'] == 'message.create']
    assert len(effects) == 1
    assert effects[0]['pid'] == rt.process.health_snapshot()['pid'] != os.getpid()
    assert effects[0]['content_source'] == 'content_parts'
    assert effects[0]['content_parts'] == parts
