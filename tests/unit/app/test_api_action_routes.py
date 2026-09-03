# -*- coding: utf-8 -*-
"""Unit tests for :mod:`qwenpaw.app._api_action_routes`.

Covers the ``@api_action`` auto-publishing layer: HTTP path parameter
extraction, the four endpoint closure shapes, route registration on a
real FastAPI app, and the slash-command spec collection including its
argument parsing branches.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from qwenpaw.api_action import ApiActionSpec, ManagerBase, ManagerRegistry
from qwenpaw.api_action import api_action
from qwenpaw.app._api_action_routes import (
    _extract_path_params,
    _make_endpoint,
    collect_slash_specs_from_api_actions,
    register_http_routes,
)
from qwenpaw.runtime.slash_command_registry import CommandSpec


class _Body(BaseModel):
    """Request model used to exercise the body-carrying endpoints."""

    label: str = "default"


class _Recorder:
    """Stand-in manager recording every dispatched call."""

    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self.result = result

    async def no_args(self):
        self.calls.append(("no_args", (), {}))
        return self.result if self.result is not None else "ok"

    async def with_kwargs(self, **kwargs):
        self.calls.append(("with_kwargs", (), kwargs))
        return self.result if self.result is not None else "kwargs-ok"

    async def with_body(self, body):
        self.calls.append(("with_body", (body,), {}))
        return self.result if self.result is not None else "body-ok"

    async def with_body_and_kwargs(self, body, **kwargs):
        self.calls.append(("with_body_and_kwargs", (body,), kwargs))
        return self.result if self.result is not None else "full-ok"


def _spec(**overrides) -> ApiActionSpec:
    data = {
        "name": "no_args",
        "methods": frozenset({"http"}),
    }
    data.update(overrides)
    return ApiActionSpec(**data)


# ---------------------------------------------------------------------------
# _extract_path_params
# ---------------------------------------------------------------------------


class TestExtractPathParams:
    @pytest.mark.parametrize("path", [None, ""])
    def test_empty_paths_yield_no_params(self, path):
        assert _extract_path_params(path) == []

    def test_path_without_placeholders(self):
        assert _extract_path_params("/crons/list") == []

    def test_single_placeholder(self):
        assert _extract_path_params("/crons/{job_id}") == ["job_id"]

    def test_multiple_placeholders_keep_order(self):
        assert _extract_path_params("/a/{first}/b/{second}") == [
            "first",
            "second",
        ]

    def test_repeated_placeholder_appears_twice(self):
        assert _extract_path_params("/{x}/and/{x}") == ["x", "x"]

    def test_non_word_placeholder_is_ignored(self):
        assert _extract_path_params("/crons/{job-id}") == []


# ---------------------------------------------------------------------------
# _make_endpoint
# ---------------------------------------------------------------------------


class TestMakeEndpoint:
    async def test_no_model_no_params_calls_method(self):
        recorder = _Recorder()
        app = FastAPI()
        endpoint = _make_endpoint(_spec(), lambda _app: recorder, app)

        assert await endpoint() == "ok"
        assert recorder.calls == [("no_args", (), {})]
        # Closure vars stay hidden from FastAPI's signature inspection.
        assert list(inspect.signature(endpoint).parameters) == []

    async def test_path_params_forwarded_as_kwargs(self):
        recorder = _Recorder()
        app = FastAPI()
        spec = _spec(
            name="with_kwargs",
            http_path="/crons/{job_id}/run/{attempt}",
        )
        endpoint = _make_endpoint(spec, lambda _app: recorder, app)

        assert await endpoint(job_id="j1", attempt="2") == "kwargs-ok"
        assert recorder.calls == [
            ("with_kwargs", (), {"job_id": "j1", "attempt": "2"}),
        ]
        params = list(inspect.signature(endpoint).parameters.values())
        assert [p.name for p in params] == ["job_id", "attempt"]
        assert all(p.annotation is str for p in params)

    async def test_request_model_without_path_params(self):
        recorder = _Recorder()
        app = FastAPI()
        spec = _spec(name="with_body", request_model=_Body)
        endpoint = _make_endpoint(spec, lambda _app: recorder, app)

        body = _Body(label="hello")
        assert await endpoint(body) == "body-ok"
        assert recorder.calls == [("with_body", (body,), {})]
        params = list(inspect.signature(endpoint).parameters.values())
        assert [p.name for p in params] == ["body"]
        assert params[0].annotation is _Body

    async def test_request_model_with_path_params(self):
        recorder = _Recorder()
        app = FastAPI()
        spec = _spec(
            name="with_body_and_kwargs",
            request_model=_Body,
            http_path="/things/{thing_id}",
        )
        endpoint = _make_endpoint(spec, lambda _app: recorder, app)

        body = _Body(label="x")
        assert await endpoint(body, thing_id="t9") == "full-ok"
        assert recorder.calls == [
            ("with_body_and_kwargs", (body,), {"thing_id": "t9"}),
        ]
        params = list(inspect.signature(endpoint).parameters.values())
        assert [p.name for p in params] == ["body", "thing_id"]
        assert params[0].annotation is _Body
        assert params[1].annotation is str

    async def test_instance_getter_receives_the_app(self):
        seen = {}

        def getter(app):
            seen["app"] = app
            return _Recorder()

        application = FastAPI()
        endpoint = _make_endpoint(_spec(), getter, application)

        await endpoint()

        assert seen["app"] is application

    async def test_getter_is_called_per_request(self):
        """No manager caching: every request re-resolves the instance."""
        instances = []

        def getter(_app):
            recorder = _Recorder()
            instances.append(recorder)
            return recorder

        endpoint = _make_endpoint(_spec(), getter, FastAPI())

        await endpoint()
        await endpoint()

        assert len(instances) == 2
        assert instances[0] is not instances[1]


# ---------------------------------------------------------------------------
# register_http_routes
# ---------------------------------------------------------------------------


class _HttpManager(ManagerBase):
    endpoint_prefix = "crons"

    @api_action(methods={"http"})
    async def list_jobs(self):
        return "listed"

    @api_action(methods={"http"}, http_method="GET", http_path="/custom/ping")
    async def ping(self):
        return "pong"

    @api_action(methods={"cli"})
    async def cli_only(self):
        return "cli"


def _registry_for(cls, instance) -> ManagerRegistry:
    registry = ManagerRegistry()
    registry.register(cls, lambda _app: instance)
    return registry


class TestRegisterHttpRoutes:
    def test_registers_http_actions_with_prefix_path(self):
        app = FastAPI()
        count = register_http_routes(app, _registry_for(_HttpManager, None))

        assert count == 2
        paths = {route.path for route in app.routes}
        assert "/crons/list_jobs" in paths
        assert "/custom/ping" in paths

    def test_non_http_actions_are_skipped(self):
        app = FastAPI()
        register_http_routes(app, _registry_for(_HttpManager, None))

        assert not any(
            "cli_only" in route.path for route in app.routes
        )

    def test_route_metadata_matches_spec(self):
        app = FastAPI()
        register_http_routes(app, _registry_for(_HttpManager, None))

        by_path = {route.path: route for route in app.routes}
        assert by_path["/custom/ping"].methods == {"GET"}
        assert by_path["/crons/list_jobs"].methods == {"POST"}
        assert (
            by_path["/crons/list_jobs"].name
            == "auto__HttpManager_list_jobs"
        )

    def test_empty_prefix_yields_double_slash_path(self):
        """Documented behaviour: the prefix is not normalised away."""

        class _NoPrefix(ManagerBase):
            endpoint_prefix = ""

            @api_action(methods={"http"})
            async def bare(self):
                return "bare"

        app = FastAPI()
        count = register_http_routes(app, _registry_for(_NoPrefix, None))

        assert count == 1
        assert "//bare" in {route.path for route in app.routes}

    def test_empty_registry_registers_nothing(self):
        app = FastAPI()

        assert register_http_routes(app, ManagerRegistry()) == 0

    def test_registration_failure_is_swallowed(self):
        app = FastAPI()
        registry = _registry_for(_HttpManager, None)

        with patch.object(
            FastAPI,
            "add_api_route",
            side_effect=RuntimeError("boom"),
        ):
            count = register_http_routes(app, registry)

        assert count == 0

    def test_multiple_managers_are_all_scanned(self):
        class _First(ManagerBase):
            endpoint_prefix = "one"

            @api_action(methods={"http"})
            async def act(self):
                return 1

        class _Second(ManagerBase):
            endpoint_prefix = "two"

            @api_action(methods={"http"})
            async def act(self):
                return 2

        registry = ManagerRegistry()
        registry.register(_First, lambda _app: None)
        registry.register(_Second, lambda _app: None)
        app = FastAPI()

        assert register_http_routes(app, registry) == 2
        paths = {route.path for route in app.routes}
        assert "/one/act" in paths
        assert "/two/act" in paths

    async def test_registered_endpoint_dispatches_to_manager(self):
        recorder = _Recorder()

        class _Live(ManagerBase):
            endpoint_prefix = "live"

            @api_action(methods={"http"})
            async def no_args(self):
                return await recorder.no_args()

        app = FastAPI()
        register_http_routes(app, _registry_for(_Live, recorder))

        route = next(
            r for r in app.routes if r.path == "/live/no_args"
        )
        assert await route.endpoint() == "ok"
        assert recorder.calls == [("no_args", (), {})]


# ---------------------------------------------------------------------------
# collect_slash_specs_from_api_actions
# ---------------------------------------------------------------------------


class _SlashManager(ManagerBase):
    """Both the spec holder and the dispatched instance.

    The slash adapter resolves ``getattr(manager, spec.name)`` at call
    time, so the registered instance must expose the same method names
    that carry the ``@api_action`` decorators.
    """

    endpoint_prefix = "slash"

    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self.result = result

    def _value(self, default):
        return self.result if self.result is not None else default

    @api_action(methods={"slash"})
    async def status(self, *args):
        self.calls.append(("status", args))
        return self._value("status-result")

    @api_action(methods={"slash"}, slash_command="renamed")
    async def aliased(self, *args):
        self.calls.append(("aliased", args))
        return self._value("aliased-result")

    @api_action(methods={"slash", "http"})
    async def dual(self, *args):
        self.calls.append(("dual", args))
        return self._value("dual-result")

    @api_action(methods={"http"})
    async def http_only(self):
        self.calls.append(("http_only", ()))
        return "http"


def _slash_registry(manager) -> ManagerRegistry:
    registry = ManagerRegistry()
    registry.register(_SlashManager, lambda _app: manager)
    return registry


class _Ctx:
    """Minimal slash-command dispatch context."""

    def __init__(self, app_services=None):
        self.app_services = app_services


class TestCollectSlashSpecs:
    def test_collects_only_slash_actions(self):
        specs = collect_slash_specs_from_api_actions(
            _slash_registry(_SlashManager()),
        )

        names = [spec.name for spec in specs]
        assert names == ["status", "renamed", "dual"]
        assert all(isinstance(spec, CommandSpec) for spec in specs)

    def test_spec_metadata(self):
        specs = collect_slash_specs_from_api_actions(
            _slash_registry(_SlashManager()),
        )

        first = specs[0]
        assert first.category == "auto"
        assert "_SlashManager.status" in first.help_text

    def test_empty_registry_yields_no_specs(self):
        assert collect_slash_specs_from_api_actions(ManagerRegistry()) == []

    async def test_no_args_dispatch(self):
        manager = _SlashManager(result="done")
        specs = collect_slash_specs_from_api_actions(
            _slash_registry(manager),
        )
        status = next(s for s in specs if s.name == "status")

        msg = await status.handler(_Ctx(), "   ")

        assert manager.calls == [("status", ())]
        assert msg.role == "assistant"
        assert msg.get_text_content() == "done"

    async def test_plain_string_args_passed_through(self):
        manager = _SlashManager(result="echoed")
        specs = collect_slash_specs_from_api_actions(
            _slash_registry(manager),
        )
        status = next(s for s in specs if s.name == "status")

        await status.handler(_Ctx(), "raw text")

        # No request model: the stripped string is forwarded as-is.
        assert manager.calls == [("status", ("raw text",))]

    async def test_json_args_build_request_model(self):
        captured = {}

        class _JsonManager(ManagerBase):
            endpoint_prefix = "json"

            @api_action(
                methods={"slash"},
                request_model=_Body,
            )
            async def configure(self, body):
                captured["body"] = body
                return "configured"

        manager = _JsonManager()
        registry = ManagerRegistry()
        registry.register(_JsonManager, lambda _app: manager)
        specs = collect_slash_specs_from_api_actions(registry)

        msg = await specs[0].handler(_Ctx(), '{"label": "value"}')

        assert isinstance(captured["body"], _Body)
        assert captured["body"].label == "value"
        assert msg.get_text_content() == "configured"

    async def test_invalid_json_reports_error_message(self):
        class _JsonManager(ManagerBase):
            endpoint_prefix = "json"

            @api_action(
                methods={"slash"},
                slash_command="cfg",
                request_model=_Body,
            )
            async def configure(self, body):
                raise AssertionError("must not be called")

        registry = ManagerRegistry()
        registry.register(_JsonManager, lambda _app: _JsonManager())
        specs = collect_slash_specs_from_api_actions(registry)

        msg = await specs[0].handler(_Ctx(), "not json")

        assert msg.role == "assistant"
        assert "Error: expected JSON for /cfg" in msg.get_text_content()

    async def test_msg_result_is_returned_unchanged(self):
        from agentscope.message import Msg
        from agentscope.message._block import TextBlock

        original = Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text="already a msg")],
        )

        class _MsgManager(ManagerBase):
            endpoint_prefix = "msg"

            @api_action(methods={"slash"})
            async def report(self):
                return original

        registry = ManagerRegistry()
        registry.register(_MsgManager, lambda _app: _MsgManager())
        specs = collect_slash_specs_from_api_actions(registry)

        assert await specs[0].handler(_Ctx(), "") is original

    async def test_non_string_result_is_stringified(self):
        class _NumberManager(ManagerBase):
            endpoint_prefix = "num"

            @api_action(methods={"slash"})
            async def count(self):
                return 42

        registry = ManagerRegistry()
        registry.register(_NumberManager, lambda _app: _NumberManager())
        specs = collect_slash_specs_from_api_actions(registry)

        msg = await specs[0].handler(_Ctx(), "")

        assert msg.get_text_content() == "42"

    async def test_context_app_services_reaches_getter(self):
        seen = {}
        app_state = object()
        manager = _SlashManager(result="resolved")

        def getter(state):
            seen["state"] = state
            return manager

        registry = ManagerRegistry()
        registry.register(_SlashManager, getter)
        specs = collect_slash_specs_from_api_actions(registry)
        status = next(s for s in specs if s.name == "status")

        await status.handler(_Ctx(app_services=app_state), "")

        assert seen["state"] is app_state
        assert manager.calls == [("status", ())]

    async def test_context_without_app_services_passes_none(self):
        seen = {}
        manager = _SlashManager(result="resolved")

        def getter(state):
            seen["state"] = state
            return manager

        registry = ManagerRegistry()
        registry.register(_SlashManager, getter)
        specs = collect_slash_specs_from_api_actions(registry)
        status = next(s for s in specs if s.name == "status")

        await status.handler(object(), "")

        assert seen["state"] is None

    def test_specs_are_independent_per_manager(self):
        class _Other(ManagerBase):
            endpoint_prefix = "other"

            @api_action(methods={"slash"})
            async def act(self):
                return "other"

        registry = ManagerRegistry()
        registry.register(_Other, lambda _app: _Other())
        registry.register(_SlashManager, lambda _app: _SlashManager())

        specs = collect_slash_specs_from_api_actions(registry)

        assert [spec.name for spec in specs] == [
            "act",
            "status",
            "renamed",
            "dual",
        ]
