"""Minimal installable voice payload contracts; no call/DTO design invented."""
import importlib
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[3]


def check_payload(key, driver_class, monkeypatch):
    source = ROOT / 'plugins/channel' / key
    namespace = 'qwenpaw_channel_' + key
    required = ('plugin.json', 'channel.json', 'requirements.txt', 'README.md',
                namespace + '/__init__.py', namespace + '/driver.py')
    missing = [name for name in required if not (source / name).is_file()]
    assert not missing, f'Missing installable {key} payload: {missing}'
    manifest = json.loads((source / 'plugin.json').read_text())
    assert manifest['id'] == key
    assert manifest['type'] == 'channel'
    assert manifest['entry'] == {'descriptor': 'channel.json'}
    assert not manifest.get('dependencies')
    requirements = [Requirement(line.strip()) for line in (source / 'requirements.txt').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
    names = [canonicalize_name(item.name) for item in requirements]
    assert len(names) == len(set(names))
    if key == 'voice':
        assert {'aiohttp', 'twilio'} <= set(names)
    # SIP extras/backend dependency selection is an existing public install
    # contract; do not require loading/installing both backends here.
    assert not {'twilio', 'pyVoIP', 'livekit', 'dashscope', 'asyncio', 'json'} & {
        p.stem for p in source.iterdir() if p.is_dir() or p.suffix == '.py'
    }
    from qwenpaw.channel_protocol.shared_response_driver import SharedResponseDriver
    monkeypatch.syspath_prepend(str(source))
    module = importlib.import_module(namespace + '.driver')
    assert Path(module.__file__).resolve() == source / namespace / 'driver.py'
    assert issubclass(getattr(module, driver_class), SharedResponseDriver)


def check_descriptor(key, driver_class, model_name, expected_defaults):
    path = ROOT / 'plugins/channel' / key / 'channel.json'
    assert path.is_file(), f'Missing shared {key} channel descriptor'
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config import config
    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == key
    assert descriptor.process_mode == 'runner_process'
    assert descriptor.dependency_mode == 'shared'
    assert descriptor.entrypoint.scope == 'runner'
    assert descriptor.entrypoint.module == 'qwenpaw_channel_' + key + '.driver'
    assert descriptor.entrypoint.qualname == driver_class
    assert descriptor.requirements_file == 'requirements.txt'
    assert 'channel.generic.v1' in descriptor.capabilities
    model = getattr(config, model_name)
    schema = model.model_json_schema()
    properties = descriptor.config_schema['properties']
    assert set(properties) == set(schema['properties']) == set(expected_defaults)
    assert set(descriptor.config_fields) == set(properties)
    assert len(descriptor.config_fields) == len(properties)
    for name, field in schema['properties'].items():
        for constraint, expected in field.items():
            assert properties[name][constraint] == expected, (name, constraint)
    assert descriptor.config_schema.get('required', []) == schema.get('required', [])
    assert model().model_dump(mode='json') == expected_defaults
    assert {name: field['default'] for name, field in properties.items()} == expected_defaults
