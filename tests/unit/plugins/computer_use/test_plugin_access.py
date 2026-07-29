# -*- coding: utf-8 -*-
"""Tests for plugin-local Computer Use application access decisions."""

from computer_use_tool import access


def _request(
    *,
    session_id: str = "session-1",
    app_id: str = "win32:contoso.editor",
):
    return access.AppApprovalRequest(
        request_id="native-request-1",
        session_id=session_id,
        canonical_app_id=app_id,
        display_name="Contoso Editor",
        identity_evidence={"path": "C:/Editor.exe"},
    )


def test_session_decision_is_scoped_to_session_and_application():
    access_store = access.ComputerUseAccessStore()
    request = _request()

    assert access_store.resolve(request) is None

    access_store.record_session(request, allowed=True)

    assert access_store.resolve(request) == access.AppAccessDecision(
        True,
        "session",
    )
    assert access_store.resolve(_request(session_id="session-2")) is None
    assert access_store.resolve(_request(app_id="win32:other")) is None


def test_persistent_allow_survives_a_new_plugin_store(tmp_path):
    path = tmp_path / "app_access.json"
    request = _request()
    access_store = access.ComputerUseAccessStore(path)

    access_store.record_persistent(
        request.canonical_app_id,
        request.display_name,
    )

    reloaded_store = access.ComputerUseAccessStore(path)
    assert reloaded_store.resolve(
        _request(session_id="session-2"),
    ) == access.AppAccessDecision(True, "persistent")
    assert reloaded_store.list_persistent() == [
        access.PersistentAppAccess(
            canonical_app_id=request.canonical_app_id,
            display_name=request.display_name,
        ),
    ]
    assert reloaded_store.revoke_persistent(request.canonical_app_id)
    assert access.ComputerUseAccessStore(path).resolve(request) is None


def test_process_app_id_spellings_share_one_decision():
    # launch_app reports an extended-length path, while window discovery
    # reports a plain lowercase drive path. Both denote one application and
    # must resolve to a single approval instead of prompting twice.
    access_store = access.ComputerUseAccessStore()
    launched = _request(
        app_id=r"process:\\?\C:\Windows\System32\notepad.exe",
    )
    discovered = _request(
        app_id=r"process:c:\windows\system32\notepad.exe",
    )

    access_store.record_session(launched, allowed=True)

    assert access_store.resolve(discovered) == access.AppAccessDecision(
        True,
        "session",
    )
