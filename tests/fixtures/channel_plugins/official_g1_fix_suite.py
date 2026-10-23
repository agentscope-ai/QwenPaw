"""Directed G1 review regressions, using real save and release boundaries."""

# pylint: disable=protected-access,redefined-outer-name,import-outside-toplevel
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=unused-argument,too-many-locals

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
import zipfile

import pytest
import official_g1_suite as core_suite

from official_g1_suite import (
    ROOT,
    bundle_project,
    resource_bundle,
    stage_module,
    staged_resources,
)

registry = core_suite.registry
saved_host = core_suite.saved_host


def configurable_resources(tmp_path, monkeypatch):
    """Add a legitimate metadata-like setting to an authenticated ZIP."""
    resources = resource_bundle(tmp_path, monkeypatch)
    index_path = resources / "index.json"
    index = json.loads(index_path.read_text())
    row = next(
        item
        for item in index["plugins"]
        if item["plugin_id"] == "new-delivery"
    )
    archive = resources / row["filename"]
    with zipfile.ZipFile(archive) as zipped:
        entries = {name: zipped.read(name) for name in zipped.namelist()}
    descriptor = json.loads(entries["new-delivery/channel.json"])
    descriptor["config_schema"]["properties"]["description"] = {
        "type": "string",
        "default": "untitled",
    }
    descriptor["config_fields"].append("description")
    entries["new-delivery/channel.json"] = json.dumps(descriptor).encode()
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, data in entries.items():
            zipped.writestr(name, data)
    row["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    row["descriptor_sha256"] = hashlib.sha256(
        entries["new-delivery/channel.json"]
    ).hexdigest()
    index_path.write_text(json.dumps(index))
    return resources


@pytest.mark.parametrize(
    "invalid",
    [
        {"api_token": 17},
        {"intruder": "must-not-persist"},
        {"description": 17},
    ],
)
def test_missing_code_config_save_rejects_trusted_schema_invalid_values(
    saved_host,
    tmp_path,
    monkeypatch,
    registry,
    invalid,
):
    from fastapi import HTTPException
    from qwenpaw.app.routers.config import _validated_channel_config

    configurable_resources(tmp_path, monkeypatch)
    assert registry.get_channel_catalog_entry("new_delivery") is None
    before = saved_host.read_bytes()
    with pytest.raises(HTTPException) as error:
        _validated_channel_config("new_delivery", invalid)
    assert error.value.status_code == 422
    assert saved_host.read_bytes() == before
    assert registry.get_channel_catalog_entry("new_delivery") is None


def test_missing_code_save_preserves_declared_metadata_field_and_defaults(
    saved_host,
    tmp_path,
    monkeypatch,
    registry,
):
    from qwenpaw.app.routers.config import _validated_channel_config
    from qwenpaw.config.utils import mutate_config, load_config
    from qwenpaw.config.config import BaseChannelConfig

    configurable_resources(tmp_path, monkeypatch)
    values = _validated_channel_config(
        "new_delivery",
        {
            "description": "user-setting",
            "availability": "missing_code",
        },
    )
    assert values == {
        **BaseChannelConfig().model_dump(mode="json"),
        "description": "user-setting",
        "api_token": "",
    }

    def persist(config):
        config.channels.new_delivery = values

    mutate_config(persist)
    assert load_config().channels.new_delivery == values
    assert (
        json.loads(saved_host.read_text())["channels"]["new_delivery"]
        == values
    )
    assert registry.get_channel_catalog_entry("new_delivery") is None
    assert not (saved_host.parent / "plugins").exists()


def test_missing_and_installed_schema_config_save_are_identical(
    saved_host,
    tmp_path,
    monkeypatch,
    registry,
):
    from qwenpaw.app.routers.config import _validated_channel_config
    from qwenpaw.plugins import official_channels
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    configurable_resources(tmp_path, monkeypatch)
    incoming = {"api_token": "test-only", "description": "user-field"}
    missing = _validated_channel_config("new_delivery", incoming)
    with official_channels.bundled_channel_source("new-delivery") as source:
        manifest = PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text())
        )
        registry.register_channel_descriptor(
            "new-delivery", describe_channel(source, manifest)
        )
        installed = _validated_channel_config("new_delivery", incoming)
    assert missing == installed
    assert missing["description"] == "user-field"
    assert missing["api_token"] == "test-only"


def real_wheel(path, name, version, payload, *, requires=()):
    """Construct real offline metadata without executable imports."""
    info = name.replace("-", "_") + "-" + version + ".dist-info/"
    metadata = (
        "Metadata-Version: 2.1\nName: " + name + "\nVersion: " + version + "\n"
    )
    metadata += "".join("Requires-Dist: " + value + "\n" for value in requires)
    entries = {
        **payload,
        info + "METADATA": metadata.encode(),
        info
        + "WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: independent-test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    entries[info + "RECORD"] = "".join(
        entry + ",," + str(len(content)) + "\n"
        for entry, content in entries.items()
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zipped:
        for entry, content in entries.items():
            zipped.writestr(entry, content)
    return path


@pytest.fixture
def clean_stage_inputs(tmp_path):
    """Copied target Python has stdlib and no third-party providers."""
    root = tmp_path / "resources"
    root.mkdir()
    runtime = root / "target-python"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(runtime)
    python = runtime / "bin/python"
    assert python.resolve().is_relative_to(root)
    site = staged_resources(tmp_path)
    marker = tmp_path / "staged-imported"
    sentinel = (
        "from pathlib import Path\n"
        + "Path("
        + repr(str(marker))
        + ").write_text('staged code executed')\n"
        + "raise AssertionError('staged packaging must never execute')\n"
    ).encode()
    wheelhouse = tmp_path / "wheelhouse"
    packaging = real_wheel(
        wheelhouse / "packaging-99.0-py3-none-any.whl",
        "packaging",
        "99.0",
        {"packaging/__init__.py": sentinel},
    )
    host_payload = {
        path.relative_to(site).as_posix(): path.read_bytes()
        for path in site.rglob("*")
        if path.is_file()
    }
    host_payload["qwenpaw/__init__.py"] = (
        b"raise AssertionError('staged host import forbidden')\n"
    )
    host_wheel = real_wheel(
        tmp_path / "qwenpaw-2.2.2b4-py3-none-any.whl",
        "qwenpaw",
        "2.2.2b4",
        host_payload,
        requires=("packaging>=20",),
    )
    return {
        "python": python,
        "site": site,
        "root": root,
        "marker": marker,
        "wheelhouse": wheelhouse,
        "packaging": packaging,
        "host_wheel": host_wheel,
    }


def assert_target_tags(snapshot):
    from packaging.tags import sys_tags

    assert snapshot["python"]["version"] == list(sys.version_info[:2])
    assert snapshot["python"]["cache_tag"] == sys.implementation.cache_tag
    assert snapshot["python"]["supported_tags"] == [
        str(tag) for tag in sys_tags()
    ]
    assert snapshot["environment"]["python_version"] == ".".join(
        map(str, sys.version_info[:2])
    )


def test_snapshot_reads_staged_metadata_without_importing_staged_packaging(
    clean_stage_inputs,
):
    case = clean_stage_inputs
    stage = stage_module()
    stage._extract_wheel(case["packaging"], case["site"])
    try:
        snapshot = stage._snapshot(case["python"], case["site"])
    finally:
        assert not case[
            "marker"
        ].exists(), "snapshot executed staged packaging"
    assert_target_tags(snapshot)
    row = next(
        item
        for item in snapshot["distributions"]
        if item["name"] == "packaging"
    )
    assert row["version"] == "99.0"
    assert Path(row["path"]).is_relative_to(case["site"])
    assert "Tag: py3-none-any" in row["wheel"]


def test_full_stage_validates_and_publishes_without_executing_staged_packages(
    clean_stage_inputs,
):
    case = clean_stage_inputs
    try:
        manifest = stage_module().stage_channel_runtime(
            python=case["python"],
            wheel=case["host_wheel"],
            resource_dir=case["root"],
            wheelhouse=case["wheelhouse"],
        )
    finally:
        assert not case[
            "marker"
        ].exists(), "full stage executed staged packaging"
    saved = json.loads(manifest.read_text())
    assert saved["host_version"] == "2.2.2b4"
    assert (
        saved["python_executable"]
        == case["python"].relative_to(case["root"]).as_posix()
    )
    assert saved["python"]["supported_tags"]
    assert (
        saved["python"]["supported_tags"]
        == stage_module()._snapshot(case["python"])["python"]["supported_tags"]
    )
    published = case["root"] / saved["support_root"]
    assert (published / "packaging/__init__.py").is_file()
    assert (published / "qwenpaw/official_channels/index.json").is_file()
    assert not list(published.rglob("__pycache__"))


def test_full_stage_rejects_incompatible_target_tag_without_staged_import(
    clean_stage_inputs,
):
    case = clean_stage_inputs
    archive = case["packaging"]
    with zipfile.ZipFile(archive) as zipped:
        entries = {name: zipped.read(name) for name in zipped.namelist()}
    wheel_info = next(
        name for name in entries if name.endswith(".dist-info/WHEEL")
    )
    entries[wheel_info] = entries[wheel_info].replace(
        b"Tag: py3-none-any", b"Tag: py2-none-any"
    )
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, content in entries.items():
            zipped.writestr(name, content)
    with pytest.raises(
        ValueError, match="Incompatible/missing wheel tags: packaging"
    ):
        stage_module().stage_channel_runtime(
            python=case["python"],
            wheel=case["host_wheel"],
            resource_dir=case["root"],
            wheelhouse=case["wheelhouse"],
        )
    assert not case["marker"].exists()
    assert not (
        case["root"] / "binaries/channel-runtime/runtime.json"
    ).exists()


def model_contract_project(tmp_path):
    project, _ = bundle_project(tmp_path)
    inventory = (
        project / "src/qwenpaw/plugins/official_channel_catalog.py"
    ).read_bytes()
    shutil.copytree(
        ROOT / "src/qwenpaw", project / "src/qwenpaw", dirs_exist_ok=True
    )
    (project / "src/qwenpaw/plugins/official_channel_catalog.py").write_bytes(
        inventory
    )
    destination = project / "scripts/pack"
    destination.mkdir(parents=True)
    for name in (
        "generate_plugin_metadata.py",
        "validate_channel_contracts.py",
    ):
        source = ROOT / "scripts/pack" / name
        if source.is_file():
            shutil.copyfile(source, destination / name)
    return project


def guarded_release_cli(project, name, arguments):
    """Run real release CLI; any platform import writes durable evidence."""
    marker = project / "platform-imported"
    script = project / "scripts/pack" / name
    launcher = r"""
import importlib.abc, pathlib, runpy, sys
marker = pathlib.Path(sys.argv[1])
script = sys.argv[2]
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        platforms = ('lark_oapi', 'dingtalk_stream', 'alibabacloud_', 'Tea',
                     'telegram', 'discord', 'slack_sdk', 'qqbot')
        implementations = ('qwenpaw_channel_', 'qwenpaw.app.channels.feishu',
                           'qwenpaw.app.channels.dingtalk')
        if fullname.startswith(platforms + implementations):
            marker.write_text(fullname)
            raise AssertionError('gate imported platform: ' + fullname)
sys.meta_path.insert(0, Guard())
sys.argv = [script, *sys.argv[3:]]
runpy.run_path(script, run_name='__main__')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            launcher,
            str(marker),
            str(script),
            *arguments,
        ],
        cwd=project,
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(project / "host"),
            "QWENPAW_SECRET_DIR": str(project / "secrets"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        not marker.exists()
    ), "release gate attempted platform implementation import"
    return result


@pytest.mark.parametrize(
    "change",
    [
        "default",
        "factory_default",
        "missing_field",
        "constraint",
        "custom_validator",
        "config_fields",
    ],
)
def test_real_release_generator_rejects_retained_model_descriptor_drift(
    tmp_path, change
):
    project = model_contract_project(tmp_path)
    descriptor_path = project / "plugins/channel/feishu/channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    properties = descriptor["config_schema"]["properties"]
    if change == "default":
        properties["app_id"]["default"] = "incompatible-default"
    elif change == "factory_default":
        properties["allow_from"]["default"] = ["incompatible-factory-default"]
    elif change == "missing_field":
        del properties["app_id"]
        descriptor["config_fields"].remove("app_id")
    elif change == "constraint":
        del properties["tool_result_max_length"]["minimum"]
    elif change == "custom_validator":
        del properties["domain"]["pattern"]
    else:
        descriptor["config_fields"].remove("app_id")
    descriptor_path.write_text(json.dumps(descriptor))
    destination = project / "dist/plugins"
    result = guarded_release_cli(
        project,
        "generate_plugin_metadata.py",
        [
            "--plugins-root",
            str(project / "plugins"),
            "--dist",
            str(destination),
        ],
    )
    assert result.returncode != 0, (
        "release accepted model/descriptor drift: " + result.stdout
    )
    assert "feishu" in result.stdout + result.stderr
    assert not list(
        destination.rglob("*.zip")
    ), "contract rejection occurred after creating artifacts"


def test_contract_preflight_accepts_defaults_validators_and_no_model_channel(
    tmp_path,
):
    project = model_contract_project(tmp_path)
    result = guarded_release_cli(
        project,
        "validate_channel_contracts.py",
        [
            "--project-root",
            str(project),
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Azure fixture has no retained host model, while FD exercise default
    # factories and domain's existing custom validator contract.
    result = guarded_release_cli(
        project,
        "generate_plugin_metadata.py",
        [
            "--plugins-root",
            str(project / "plugins"),
            "--dist",
            str(project / "dist/plugins"),
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        project / "dist/plugins/channel/new-delivery/new-delivery-1.0.0.zip"
    ).is_file()


@pytest.mark.parametrize(
    "change", ["channel_key", "module", "qualname", "label"]
)
def test_descriptor_update_preserves_key_but_allows_source_evolution(
    tmp_path, change
):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import (
        ChannelBackend,
        ChannelRuntimeSettings,
    )
    from types import SimpleNamespace

    old_source, old_manifest = core_suite.channel_source(
        tmp_path / "old",
        plugin_id="stable-owner",
        key="old_chat",
        source_dir="old-code",
    )
    key = "new_chat" if change == "channel_key" else "old_chat"
    source, _ = core_suite.channel_source(
        tmp_path / "candidate",
        plugin_id="stable-owner",
        key=key,
        source_dir="new-code",
    )
    data = json.loads((source / "plugin.json").read_text())
    data["version"] = "1.0.1"
    (source / "plugin.json").write_text(json.dumps(data))
    descriptor = json.loads((source / "channel.json").read_text())
    if change == "module":
        descriptor["entrypoint"][
            "module"
        ] = "qwenpaw_channel_old_chat.replacement"
        (source / "qwenpaw_channel_old_chat/replacement.py").write_text(
            "raise AssertionError('update validation imported driver')\n",
        )
    elif change == "qualname":
        descriptor["entrypoint"]["qualname"] = "NewDriver"
    elif change == "label":
        descriptor["label"] = {"en": "Updated channel", "zh": "新展示名"}
    (source / "channel.json").write_text(json.dumps(descriptor))
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=None,
    )
    backend = ChannelBackend(SimpleNamespace(runtime_settings=lambda: runtime))
    old = backend.describe(old_source, old_manifest)
    candidate = backend.describe(source, PluginManifest.from_dict(data))
    assert old.manifest.id == candidate.manifest.id == "stable-owner"
    if change == "channel_key":
        with pytest.raises(
            (ValueError, RuntimeError), match="(?i)(channel|key|route)"
        ):
            backend.validate_update(old, candidate, in_place=False)
    else:
        backend.validate_update(old, candidate, in_place=False)


def test_legacy_backend_to_descriptor_is_not_mistaken_for_key_rename(tmp_path):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import (
        ChannelBackend,
        ChannelRuntimeSettings,
    )
    from qwenpaw.plugins.execution_backend import PluginDescription
    from types import SimpleNamespace

    # Azure is now an actual v2 source. Model the previous backend contract
    # with a real separate manifest, without labelling that new source legacy.
    legacy_source = tmp_path / "legacy-code"
    legacy_source.mkdir()
    data = {
        "id": "new-delivery",
        "name": "Previous backend",
        "version": "0.9.0",
        "type": "channel",
        "entry": {"backend": "plugin.py"},
    }
    (legacy_source / "plugin.json").write_text(json.dumps(data))
    (legacy_source / "plugin.py").write_text(
        "raise AssertionError('update validation imported legacy backend')\n",
    )
    legacy_manifest = PluginManifest.from_dict(data)
    assert legacy_manifest.entry.descriptor is None
    old = PluginDescription(legacy_manifest, legacy_source, None, None)
    source, manifest = core_suite.channel_source(tmp_path)
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=frozenset({"new_delivery"}),
    )
    backend = ChannelBackend(SimpleNamespace(runtime_settings=lambda: runtime))
    candidate = backend.describe(source, manifest)
    backend.validate_update(old, candidate, in_place=False)


def literal_contract_project(tmp_path, monkeypatch, model=None):
    """Install a real retained-model field and corresponding v2 source."""
    from copy import deepcopy
    from pydantic import Field
    from pydantic.fields import FieldInfo
    from qwenpaw.config.config import BaseChannelConfig, ChannelConfig

    class LiteralSettings(BaseChannelConfig):
        description: str = "business-description"
        payload: dict = Field(
            default_factory=lambda: {
                "title": "business-title",
                "description": "nested-description",
                "examples": ["business-example"],
                "$comment": "business-comment",
            }
        )
        constant: dict = Field(
            default={
                "title": "constant-title",
                "description": "constant-description",
            },
            json_schema_extra={
                "const": {
                    "title": "constant-title",
                    "description": "constant-description",
                }
            },
        )
        choice: dict = Field(
            default={"title": "first"},
            json_schema_extra={
                "enum": [{"title": "first"}, {"description": "second"}]
            },
        )

    model = LiteralSettings if model is None else model
    monkeypatch.setitem(
        ChannelConfig.model_fields,
        "contract_chat",
        FieldInfo.from_annotation(model),
    )
    root = tmp_path / "contract-project"
    source, _ = core_suite.channel_source(
        root / "plugins/channel",
        plugin_id="contract-owner",
        key="contract_chat",
        source_dir="independent-source",
    )
    schema = deepcopy(model.model_json_schema())
    for name, value in model().model_dump(mode="json").items():
        schema["properties"][name]["default"] = value
    descriptor_path = source / "channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["config_schema"] = schema
    descriptor["config_fields"] = list(schema["properties"])
    descriptor_path.write_text(json.dumps(descriptor))
    inventory = root / "src/qwenpaw/plugins/official_channel_catalog.py"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(
        "OFFICIAL_CHANNELS = "
        + repr(
            (
                {
                    "channel_key": "contract_chat",
                    "plugin_id": "contract-owner",
                    "source_dir": "independent-source",
                    "icon": "",
                    "doc_url": "",
                },
            )
        )
        + "\n"
    )
    spec = importlib.util.spec_from_file_location(
        "g1_literal_contract_gate",
        ROOT / "scripts/pack/validate_channel_contracts.py",
    )
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return root, descriptor_path, gate


@pytest.mark.parametrize(
    "change",
    [
        "description_field",
        "default_title",
        "default_description",
        "default_examples",
        "default_comment",
        "const_literal",
        "enum_literal",
    ],
)
def test_contract_gate_preserves_business_names_and_literals(
    tmp_path, monkeypatch, change
):
    root, path, gate = literal_contract_project(tmp_path, monkeypatch)
    gate.validate_official_channel_contracts(root)
    descriptor = json.loads(path.read_text())
    fields = descriptor["config_schema"]["properties"]
    if change == "description_field":
        fields["description"]["default"] = "incompatible-description-default"
    elif change.startswith("default_"):
        name = {
            "default_title": "title",
            "default_description": "description",
            "default_examples": "examples",
            "default_comment": "$comment",
        }[change]
        fields["payload"]["default"][name] = "incompatible-business-literal"
    elif change == "const_literal":
        fields["constant"]["const"]["description"] = "incompatible-constant"
    else:
        fields["choice"]["enum"][1][
            "description"
        ] = "incompatible-second-choice"
    path.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError, match="contract_chat"):
        gate.validate_official_channel_contracts(root)


def test_contract_gate_ignores_only_schema_presentation_annotations(
    tmp_path, monkeypatch
):
    root, path, gate = literal_contract_project(tmp_path, monkeypatch)
    descriptor = json.loads(path.read_text())
    schema = descriptor["config_schema"]
    for node in [schema, *schema["properties"].values()]:
        node.update(
            title="New display title",
            description="Schema documentation",
            examples=["schema-only example"],
            **{"$comment": "schema comment"},
        )
    path.write_text(json.dumps(descriptor))
    gate.validate_official_channel_contracts(root)


def dependency_contract_project(tmp_path, monkeypatch, keyword, trigger):
    """Generate real model schemas with standard field-name dependency maps."""
    from pydantic import ConfigDict, create_model
    from qwenpaw.config.config import BaseChannelConfig

    dependency = (
        {trigger: ["permission"]}
        if keyword == "dependentRequired"
        else {
            trigger: {"properties": {"permission": {"const": "authorized"}}},
        }
    )
    model = create_model(
        "DependentSettings",
        __base__=BaseChannelConfig,
        __config__=ConfigDict(json_schema_extra={keyword: dependency}),
        **{trigger: (str, ""), "permission": (str, "authorized")},
    )
    return literal_contract_project(tmp_path, monkeypatch, model)


@pytest.mark.parametrize("keyword", ["dependentRequired", "dependentSchemas"])
@pytest.mark.parametrize(
    "trigger", ["description", "title", "examples", "$comment"]
)
def test_gate_rejects_dependency_map_constraint_deletion(
    tmp_path, monkeypatch, keyword, trigger
):
    from copy import deepcopy
    from jsonschema import Draft202012Validator

    root, path, gate = dependency_contract_project(
        tmp_path, monkeypatch, keyword, trigger
    )
    gate.validate_official_channel_contracts(root)
    descriptor = json.loads(path.read_text())
    original = deepcopy(descriptor["config_schema"])
    assert trigger in original["properties"]
    changed = descriptor["config_schema"]
    del changed[keyword][trigger]
    probe = (
        {trigger: "user-setting"}
        if keyword == "dependentRequired"
        else {trigger: "user-setting", "permission": "denied"}
    )
    # Defaults satisfy both schemas. The probe proves actual accepted-input
    # behavior differs, independently of the gate's normalization/equality.
    defaults = {
        name: field["default"]
        for name, field in original["properties"].items()
    }
    assert Draft202012Validator(original).is_valid(defaults)
    assert Draft202012Validator(changed).is_valid(defaults)
    assert not Draft202012Validator(original).is_valid(probe)
    assert Draft202012Validator(changed).is_valid(probe)
    path.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError, match="contract_chat"):
        gate.validate_official_channel_contracts(root)


def test_dependency_subschema_presentation_changes_are_allowed(
    tmp_path, monkeypatch
):
    root, path, gate = dependency_contract_project(
        tmp_path,
        monkeypatch,
        "dependentSchemas",
        "description",
    )
    descriptor = json.loads(path.read_text())
    subschema = descriptor["config_schema"]["dependentSchemas"]["description"]
    for node in [subschema, subschema["properties"]["permission"]]:
        node.update(
            title="Display title",
            description="Schema explanation",
            examples=["documentation-only example"],
            **{"$comment": "documentation-only comment"},
        )
    path.write_text(json.dumps(descriptor))
    gate.validate_official_channel_contracts(root)
