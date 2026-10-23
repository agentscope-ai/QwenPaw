"""Static installable iMessage payload contracts; import no host or platform code."""

import json
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/imessage"


def test_imessage_installable_payload_is_complete():
    required = (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
        "qwenpaw_channel_imessage/__init__.py",
        "qwenpaw_channel_imessage/driver.py",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing installable iMessage payload: {missing}"
    manifest = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "imessage"
    assert manifest["type"] == "channel"
    assert manifest["entry"]["descriptor"] == "channel.json"


def test_imessage_descriptor_declares_shared_runner_contract():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing installable iMessage channel descriptor"
    descriptor = json.loads(path.read_text("utf-8"))
    assert descriptor["schema_version"] == 2
    assert descriptor["channel_key"] == "imessage"
    assert descriptor["process_mode"] == "runner_process"
    assert descriptor["dependency_mode"] == "shared"
    entry = descriptor["entrypoint"]
    assert entry["scope"] == "runner"
    assert entry["module"].startswith("qwenpaw_channel_imessage.")
    assert (SOURCE / (entry["module"].replace(".", "/") + ".py")).is_file()
    assert entry["qualname"]
    assert descriptor["requirements_file"] == "requirements.txt"
    assert "channel.generic.v1" in descriptor["capabilities"]
    properties = descriptor["config_schema"]["properties"]
    assert set(descriptor["config_fields"]) == set(properties)
    assert properties["db_path"]["default"] == "~/Library/Messages/chat.db"
    assert properties["poll_sec"]["default"] == 1.0
    assert properties["media_dir"]["default"] is None
    assert properties["max_decoded_size"]["default"] == 10485760
