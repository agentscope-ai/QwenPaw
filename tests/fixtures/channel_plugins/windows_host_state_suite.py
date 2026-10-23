"""Exercise the real host-state writer with native and Windows handle rules."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels import isolated_proxy
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.channel_protocol.models import HostStateParams


def proxy(workspace):
    owner = object.__new__(IsolatedChannelProxy)
    owner._workspace_dir = workspace
    owner.channel = "sample_chat"
    owner._launch_spec = SimpleNamespace(instance_id="windows-state")
    owner._state = {}
    return owner


def params(key="responses", value=None):
    return HostStateParams(
        channel_key="sample_chat",
        instance_id="windows-state",
        generation=1,
        key=key,
        schema_version=1,
        value=value,
    )


def assert_disk_matches(owner):
    path = owner._state_path()
    assert json.loads(path.read_bytes()) == owner._state
    assert list(path.parent.iterdir()) == [path]


def exercise_success(workspace):
    owner = proxy(workspace)
    for value in (
        [{"route": "room-A", "text": "初始"}],
        [{"route": "room-A", "text": "updated"}],
    ):
        assert owner._state_operation("put", params(value=value)) == {
            "stored": True,
        }
        assert_disk_matches(owner)
        restored = proxy(workspace)
        assert restored._state_operation("get", params()) == {"value": value}
        assert restored._state == owner._state
    assert owner._state_operation("put", params("other", {"keep": True})) == {
        "stored": True,
    }
    assert owner._state_operation("delete", params()) == {"stored": True}
    assert_disk_matches(owner)
    restored = proxy(workspace)
    assert restored._state_operation("get", params()) == {"value": None}
    assert restored._state_operation("get", params("other")) == {
        "value": {"keep": True},
    }
    assert restored._state_operation("delete", params("other")) == {"stored": True}
    assert_disk_matches(restored)
    assert proxy(workspace)._state_operation("get", params("other")) == {
        "value": None,
    }


def windows_file_rules(monkeypatch, failure=None):
    """Track real temporary handles; emulate Windows refusal while live."""
    handles, events = [], []
    named_temporary_file = isolated_proxy.tempfile.NamedTemporaryFile
    replace = isolated_proxy.os.replace
    unlink = Path.unlink
    fsync = isolated_proxy.os.fsync

    def is_live(path):
        return any(
            Path(handle.name) == Path(path) and not handle.closed for handle in handles
        )

    def temporary_file(*args, **kwargs):
        output = named_temporary_file(*args, **kwargs)
        handles.append(output)
        if failure in {"write", "flush"}:
            original = getattr(output, failure)

            def fail(*args, **kwargs):
                # Leave actual bytes to clean up, including on a partial write.
                if failure == "write":
                    original(args[0][: max(1, len(args[0]) // 2)])
                else:
                    original(*args, **kwargs)
                raise OSError(f"injected {failure} failure")

            setattr(output, failure, fail)
        return output

    def replace_closed(source, destination):
        events.append(("replace", is_live(source)))
        if is_live(source):
            raise PermissionError("Windows refuses replace of a live source")
        assert Path(source).parent == Path(destination).parent
        assert events[-2][0] == "fsync"
        assert Path(source).read_bytes()
        if failure == "replace":
            raise OSError("injected replace failure")
        return replace(source, destination)

    def unlink_closed(path, *args, **kwargs):
        events.append(("unlink", is_live(path)))
        if is_live(path):
            raise PermissionError("Windows refuses unlink of a live source")
        return unlink(path, *args, **kwargs)

    def sync(descriptor):
        events.append(("fsync", None))
        if failure == "fsync":
            raise OSError("injected fsync failure")
        return fsync(descriptor)

    monkeypatch.setattr(
        isolated_proxy.tempfile,
        "NamedTemporaryFile",
        temporary_file,
    )
    monkeypatch.setattr(isolated_proxy.os, "replace", replace_closed)
    monkeypatch.setattr(Path, "unlink", unlink_closed)
    monkeypatch.setattr(isolated_proxy.os, "fsync", sync)
    return handles, events


def test_native_filesystem_put_update_reload_and_delete(tmp_path):
    """Keep an unpatched path runnable on Windows itself, without skips."""
    exercise_success(tmp_path)


def test_windows_rules_require_closed_replace_and_unlink(tmp_path, monkeypatch):
    handles, events = windows_file_rules(monkeypatch)
    exercise_success(tmp_path)
    assert len(handles) == 5
    assert all(output.closed for output in handles)
    assert len([row for row in events if row[0] == "replace"]) == 5
    assert len([row for row in events if row[0] == "unlink"]) == 5
    assert all(
        live is False
        for operation, live in events
        if operation in {"replace", "unlink"}
    )


@pytest.mark.parametrize("operation", ["put", "delete"])
@pytest.mark.parametrize("failure", ["write", "flush", "fsync", "replace"])
def test_failed_disk_mutation_preserves_state_and_cleans_closed_temp(
    tmp_path,
    monkeypatch,
    operation,
    failure,
):
    owner = proxy(tmp_path)
    owner._state_operation("put", params(value={"route": "old"}))
    path = owner._state_path()
    previous_memory = deepcopy(owner._state)
    previous_bytes = path.read_bytes()
    handles, events = windows_file_rules(monkeypatch, failure)

    with pytest.raises(OSError, match=f"injected {failure} failure"):
        owner._state_operation(operation, params(value={"route": "new"}))

    assert owner._state == previous_memory
    assert path.read_bytes() == previous_bytes
    assert list(path.parent.iterdir()) == [path]
    assert len(handles) == 1 and handles[0].closed
    assert events[-1] == ("unlink", False)
    assert sum(operation == "replace" for operation, _ in events) == (
        failure == "replace"
    )
    restored = proxy(tmp_path)
    assert restored._state_operation("get", params()) == {"value": {"route": "old"}}
