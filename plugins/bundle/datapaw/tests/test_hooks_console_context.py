# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access
# Test stubs override signatures for monkeypatch targets (unused-argument);
# the hooks install patches reaching host internals (protected-access).
"""Tests for hooks console ``request_context`` pass-through."""
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# _read_request_context
# ---------------------------------------------------------------------------


def test_read_request_context_from_dict():
    from plugin_datapaw.hooks import _read_request_context

    out = _read_request_context({"request_context": {"datasource_id": "x"}})
    assert out == {"datasource_id": "x"}


def test_read_request_context_from_object_attr():
    from plugin_datapaw.hooks import _read_request_context

    req = SimpleNamespace(request_context={"datasource_id": "y"})
    assert _read_request_context(req) == {"datasource_id": "y"}


def test_read_request_context_returns_none_when_absent():
    from plugin_datapaw.hooks import _read_request_context

    assert _read_request_context({}) is None
    assert _read_request_context({"request_context": {}}) == {}
    assert _read_request_context({"request_context": "nope"}) is None
    assert _read_request_context(SimpleNamespace()) is None


# ---------------------------------------------------------------------------
# _wrap_extract_session_and_payload
# ---------------------------------------------------------------------------


def test_extract_wrapper_preserves_request_context():
    from plugin_datapaw.hooks import _wrap_extract_session_and_payload

    def orig(request_data):
        return {"channel_id": "console", "meta": {}}

    wrapped = _wrap_extract_session_and_payload(orig)
    out = wrapped({"request_context": {"datasource_id": "mysql-abc123"}})

    assert out["request_context"] == {"datasource_id": "mysql-abc123"}
    assert getattr(wrapped, "_datapaw_patched", False) is True


def test_extract_wrapper_no_request_context_unchanged():
    from plugin_datapaw.hooks import _wrap_extract_session_and_payload

    def orig(request_data):
        return {"channel_id": "console", "meta": {}}

    wrapped = _wrap_extract_session_and_payload(orig)
    out = wrapped({"input": []})

    assert "request_context" not in out


# ---------------------------------------------------------------------------
# _wrap_build_agent_request_from_native
# ---------------------------------------------------------------------------


def test_build_wrapper_attaches_request_context():
    from plugin_datapaw.hooks import _wrap_build_agent_request_from_native

    def orig(self, native_payload):
        return SimpleNamespace(channel_meta={})

    wrapped = _wrap_build_agent_request_from_native(orig)
    request = wrapped(
        object(),
        {"request_context": {"datasource_id": "mysql-abc123"}},
    )

    assert request.request_context == {"datasource_id": "mysql-abc123"}
    assert getattr(wrapped, "_datapaw_patched", False) is True


def test_build_wrapper_no_request_context_leaves_request_untouched():
    from plugin_datapaw.hooks import _wrap_build_agent_request_from_native

    def orig(self, native_payload):
        return SimpleNamespace(channel_meta={})

    wrapped = _wrap_build_agent_request_from_native(orig)
    request = wrapped(object(), {"meta": {}})

    assert not hasattr(request, "request_context")


def test_build_wrapper_attaches_empty_request_context():
    from plugin_datapaw.hooks import _wrap_build_agent_request_from_native

    def orig(self, native_payload):
        return SimpleNamespace(channel_meta={})

    wrapped = _wrap_build_agent_request_from_native(orig)
    request = wrapped(object(), {"request_context": {}})

    assert request.request_context == {}


# ---------------------------------------------------------------------------
# setup_console_request_context_hook installer
# ---------------------------------------------------------------------------


def test_setup_console_request_context_hook_patches_both_and_idempotent():
    from plugin_datapaw.hooks import setup_console_request_context_hook

    def orig_extract(request_data):
        return {"meta": {}}

    def orig_build(self, native_payload):
        return SimpleNamespace()

    fake_console_module = SimpleNamespace(
        _extract_session_and_payload=orig_extract,
    )

    class FakeChannel:
        build_agent_request_from_native = orig_build

    setup_console_request_context_hook(
        _console_module=fake_console_module,
        _channel_cls=FakeChannel,
    )

    assert fake_console_module._extract_session_and_payload is not orig_extract
    assert FakeChannel.build_agent_request_from_native is not orig_build
    patched_extract = fake_console_module._extract_session_and_payload
    patched_build = FakeChannel.build_agent_request_from_native

    setup_console_request_context_hook(
        _console_module=fake_console_module,
        _channel_cls=FakeChannel,
    )

    assert fake_console_module._extract_session_and_payload is patched_extract
    assert FakeChannel.build_agent_request_from_native is patched_build
