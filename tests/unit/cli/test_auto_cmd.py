# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for the lazily-populated `auto` CLI group.

The generated subcommands are HTTP clients (the CLI runs in a separate process
with no ManagerRegistry), so the tests drive them against a fake transport and
assert the request they build.
"""

import types

import click
import pytest
from click.testing import CliRunner

from qwenpaw.cli import auto as auto_mod

# Module-level recorder: a class attribute referenced as `_FakeClient.calls`
# would be re-created per fixture reset, and instances cannot see it reliably.
CALLS = []


class _Resp:
    """Minimal response object: raise_for_status + json()."""

    def __init__(self, payload=None, fail=False):
        self._payload = payload if payload is not None else {"ok": True}
        self._fail = fail

    def raise_for_status(self):
        if self._fail:
            raise RuntimeError("500 server error")

    def json(self):
        return self._payload


class _FakeClient:
    """Context manager recording get/head/request calls."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.get_resp = _Resp({"via": "get"})
        self.request_resp = _Resp({"via": "request"})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def head(self, path):
        CALLS.append(("head", path, self.base_url))
        return _Resp()

    def get(self, path):
        CALLS.append(("get", path, self.base_url))
        return self.get_resp

    def request(self, method, path, json=None):  # noqa: A002 - mirrors httpx
        CALLS.append(("request", method, path, json))
        return self.request_resp


@pytest.fixture()
def fake_client(monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(auto_mod, "client", _FakeClient)
    printed = []
    monkeypatch.setattr(auto_mod, "print_json", printed.append)
    return {"calls": CALLS, "printed": printed}


def _spec(
    name,
    methods=("cli",),
    http_path=None,
    http_method="GET",
    cli_command=None,
):
    """A stand-in ApiActionSpec carrying only the fields auto.py reads."""
    return types.SimpleNamespace(
        name=name,
        methods=frozenset(methods),
        http_path=http_path,
        http_method=http_method,
        cli_command=cli_command,
    )


def _manager(prefix="crons", actions=None):
    class _Mgr:
        endpoint_prefix = prefix
        _api_actions = actions if actions is not None else []

    return _Mgr


# ── _base_url ────────────────────────────────────────────────────────────


class TestBaseUrl:
    def test_explicit_base_url_wins_and_is_rstripped(self):
        ctx = click.Context(click.Command("x"), obj={"host": "h", "port": 1})
        assert auto_mod._base_url(ctx, "http://a:9/") == "http://a:9"

    def test_strips_multiple_trailing_slashes(self):
        ctx = click.Context(click.Command("x"), obj={})
        assert auto_mod._base_url(ctx, "http://a:9///") == "http://a:9"

    def test_falls_back_to_ctx_host_and_port(self):
        ctx = click.Context(
            click.Command("x"),
            obj={"host": "1.2.3.4", "port": 9999},
        )
        assert auto_mod._base_url(ctx, None) == "http://1.2.3.4:9999"

    def test_defaults_when_ctx_obj_is_empty(self):
        ctx = click.Context(click.Command("x"), obj={})
        assert auto_mod._base_url(ctx, None) == "http://127.0.0.1:8088"

    def test_defaults_when_ctx_obj_is_none(self):
        ctx = click.Context(click.Command("x"), obj=None)
        assert auto_mod._base_url(ctx, None) == "http://127.0.0.1:8088"


# ── _ensure_daemon_alive ─────────────────────────────────────────────


class TestEnsureDaemonAlive:
    def test_healthy_daemon_returns_silently(self, fake_client):
        auto_mod._ensure_daemon_alive("http://x")
        assert any(c[0] == "head" for c in fake_client["calls"])

    def test_unreachable_daemon_exits_with_code_2(
        self,
        fake_client,
        monkeypatch,
    ):
        monkeypatch.setattr(auto_mod, "client", lambda url: _BoomClient())
        with pytest.raises(SystemExit) as exc:
            auto_mod._ensure_daemon_alive("http://x")
        assert exc.value.code == 2

    def test_error_message_names_the_url_and_the_fix(
        self,
        fake_client,
        capsys,
        monkeypatch,
    ):
        monkeypatch.setattr(auto_mod, "client", lambda url: _BoomClient())
        with pytest.raises(SystemExit):
            auto_mod._ensure_daemon_alive("http://down:1")
        err = capsys.readouterr().err
        assert "http://down:1" in err
        assert "qwenpaw app" in err

    def test_non_2xx_health_response_exits_2(self, fake_client, monkeypatch):
        class _Client(_FakeClient):
            def head(self, path):
                return _Resp(fail=True)

        monkeypatch.setattr(auto_mod, "client", _Client)
        with pytest.raises(SystemExit) as exc:
            auto_mod._ensure_daemon_alive("http://x")
        assert exc.value.code == 2


class _BoomClient:
    def __enter__(self):
        raise ConnectionError("refused")

    def __exit__(self, *a):
        return False


# ── _load_manager_classes ────────────────────────────────────────────


class TestLoadManagerClasses:
    def test_loads_the_configured_manager(self):
        classes = auto_mod._load_manager_classes()
        from qwenpaw.app.crons.manager import CronManager

        assert CronManager in classes

    def test_a_bad_entry_is_skipped_not_raised(self, monkeypatch):
        monkeypatch.setattr(
            auto_mod,
            "_MANAGER_CLASSES",
            ["no.such.module:Nope"],
        )
        assert auto_mod._load_manager_classes() == []

    def test_mixed_good_and_bad_keeps_the_good(self, monkeypatch):
        monkeypatch.setattr(
            auto_mod,
            "_MANAGER_CLASSES",
            ["no.such.module:Nope", "qwenpaw.app.crons.manager:CronManager"],
        )
        from qwenpaw.app.crons.manager import CronManager

        assert auto_mod._load_manager_classes() == [CronManager]


# ── _LazyAutoGroup registration ─────────────────────────────────────


class TestLazyGroup:
    def _group_with(self, monkeypatch, actions, prefix="crons"):
        monkeypatch.setattr(
            auto_mod,
            "_load_manager_classes",
            lambda: [_manager(prefix, actions)],
        )
        return auto_mod._LazyAutoGroup(name="auto")

    def test_registers_a_command_per_cli_action(self, monkeypatch):
        group = self._group_with(
            monkeypatch,
            [
                _spec("list_jobs", http_path="/crons/jobs"),
                _spec(
                    "delete_job",
                    http_path="/crons/jobs/{job_id}",
                    http_method="DELETE",
                ),
            ],
        )
        names = group.list_commands(click.Context(group))
        assert "crons-list_jobs" in names
        assert "crons-delete_job" in names

    def test_skips_actions_without_the_cli_method(self, monkeypatch):
        group = self._group_with(
            monkeypatch,
            [_spec("only_http", methods=("http",))],
        )
        assert group.list_commands(click.Context(group)) == []

    def test_explicit_cli_command_overrides_the_prefix_name(self, monkeypatch):
        group = self._group_with(
            monkeypatch,
            [
                _spec(
                    "list_jobs",
                    cli_command="jobs-ls",
                    http_path="/crons/jobs",
                ),
            ],
        )
        assert "jobs-ls" in group.list_commands(click.Context(group))
        assert "crons-list_jobs" not in group.list_commands(
            click.Context(group),
        )

    def test_no_prefix_uses_the_bare_action_name(self, monkeypatch):
        group = self._group_with(
            monkeypatch,
            [_spec("ping", http_path="/p")],
            prefix="",
        )
        assert "ping" in group.list_commands(click.Context(group))

    def test_help_text_mentions_the_manager_and_action(self, monkeypatch):
        group = self._group_with(
            monkeypatch,
            [_spec("list_jobs", http_path="/x")],
        )
        cmd = group.get_command(click.Context(group), "crons-list_jobs")
        assert "Auto:" in cmd.help
        assert "list_jobs" in cmd.help

    def test_loading_only_happens_once(self, monkeypatch):
        calls = {"n": 0}

        def counting_loader():
            calls["n"] += 1
            return [_manager("crons", [_spec("a", http_path="/a")])]

        monkeypatch.setattr(auto_mod, "_load_manager_classes", counting_loader)
        group = auto_mod._LazyAutoGroup(name="auto")
        ctx = click.Context(group)
        group.list_commands(ctx)
        group.list_commands(ctx)
        group.get_command(ctx, "crons-a")
        assert calls["n"] == 1

    def test_get_command_returns_none_for_unknown(self, monkeypatch):
        group = self._group_with(monkeypatch, [_spec("a", http_path="/a")])
        assert group.get_command(click.Context(group), "nope") is None


# ── generated command execution ─────────────────────────────────────


class TestGeneratedCommand:
    def _build(self, monkeypatch, spec, prefix="crons"):
        monkeypatch.setattr(
            auto_mod,
            "_load_manager_classes",
            lambda: [_manager(prefix, [spec])],
        )
        group = auto_mod._LazyAutoGroup(name="auto")
        return group

    def test_get_request_uses_explicit_http_path(
        self,
        fake_client,
        monkeypatch,
    ):
        group = self._build(
            monkeypatch,
            _spec("list_jobs", http_path="/crons/jobs", http_method="GET"),
        )
        result = CliRunner().invoke(
            group,
            ["crons-list_jobs", "--base-url", "http://x"],
        )

        assert result.exit_code == 0, result.output
        assert ("get", "/crons/jobs", "http://x") in fake_client["calls"]

    def test_path_falls_back_to_prefix_and_name(
        self,
        fake_client,
        monkeypatch,
    ):
        group = self._build(monkeypatch, _spec("list_jobs", http_path=None))
        result = CliRunner().invoke(
            group,
            ["crons-list_jobs", "--base-url", "http://x"],
        )

        assert result.exit_code == 0, result.output
        assert ("get", "/crons/list_jobs", "http://x") in fake_client["calls"]

    def test_response_is_printed(self, fake_client, monkeypatch):
        group = self._build(
            monkeypatch,
            _spec("list_jobs", http_path="/crons/jobs"),
        )
        CliRunner().invoke(
            group,
            ["crons-list_jobs", "--base-url", "http://x"],
        )

        assert fake_client["printed"] == [{"via": "get"}]

    def test_post_sends_json_body(self, fake_client, monkeypatch):
        group = self._build(
            monkeypatch,
            _spec("create", http_path="/crons/jobs", http_method="POST"),
        )
        result = CliRunner().invoke(
            group,
            ["crons-create", "--base-url", "http://x", "--data", '{"a": 1}'],
        )

        assert result.exit_code == 0, result.output
        assert ("request", "POST", "/crons/jobs", {"a": 1}) in fake_client[
            "calls"
        ]

    def test_post_without_data_sends_empty_body(
        self,
        fake_client,
        monkeypatch,
    ):
        group = self._build(
            monkeypatch,
            _spec("create", http_path="/c", http_method="POST"),
        )
        CliRunner().invoke(group, ["crons-create", "--base-url", "http://x"])

        assert ("request", "POST", "/c", {}) in fake_client["calls"]

    def test_delete_is_uppercased(self, fake_client, monkeypatch):
        group = self._build(
            monkeypatch,
            _spec(
                "delete_job",
                http_path="/crons/jobs/{job_id}",
                http_method="delete",
            ),
        )
        result = CliRunner().invoke(
            group,
            [
                "crons-delete_job",
                "--base-url",
                "http://x",
                "--path-params",
                '{"job_id": "j1"}',
            ],
        )

        assert result.exit_code == 0, result.output
        assert ("request", "DELETE", "/crons/jobs/j1", {}) in fake_client[
            "calls"
        ]

    def test_placeholder_without_params_is_a_usage_error(
        self,
        fake_client,
        monkeypatch,
    ):
        group = self._build(
            monkeypatch,
            _spec("delete_job", http_path="/crons/jobs/{job_id}"),
        )
        result = CliRunner().invoke(
            group,
            ["crons-delete_job", "--base-url", "http://x"],
        )

        assert result.exit_code != 0
        assert "placeholders" in result.output

    def test_invalid_path_params_json_is_a_usage_error(
        self,
        fake_client,
        monkeypatch,
    ):
        group = self._build(
            monkeypatch,
            _spec("delete_job", http_path="/crons/jobs/{job_id}"),
        )
        result = CliRunner().invoke(
            group,
            [
                "crons-delete_job",
                "--base-url",
                "http://x",
                "--path-params",
                "not-json",
            ],
        )

        assert result.exit_code != 0
        assert "--path-params must be valid JSON" in result.output

    def test_missing_path_parameter_is_a_usage_error(
        self,
        fake_client,
        monkeypatch,
    ):
        group = self._build(
            monkeypatch,
            _spec("delete_job", http_path="/crons/jobs/{job_id}"),
        )
        result = CliRunner().invoke(
            group,
            [
                "crons-delete_job",
                "--base-url",
                "http://x",
                "--path-params",
                "{}",
            ],
        )

        assert result.exit_code != 0
        assert "Missing path parameter" in result.output

    def test_invalid_data_json_propagates(self, fake_client, monkeypatch):
        group = self._build(
            monkeypatch,
            _spec("create", http_path="/c", http_method="POST"),
        )
        result = CliRunner().invoke(
            group,
            ["crons-create", "--base-url", "http://x", "--data", "{bad"],
        )

        assert result.exit_code != 0

    def test_http_error_surfaces_as_a_nonzero_exit(
        self,
        fake_client,
        monkeypatch,
    ):
        class _FailingClient(_FakeClient):
            def get(self, path):
                return _Resp(fail=True)

        monkeypatch.setattr(auto_mod, "client", _FailingClient)
        group = self._build(
            monkeypatch,
            _spec("list_jobs", http_path="/crons/jobs"),
        )
        result = CliRunner().invoke(
            group,
            ["crons-list_jobs", "--base-url", "http://x"],
        )

        assert result.exit_code != 0

    def test_daemon_down_aborts_before_the_call(
        self,
        fake_client,
        monkeypatch,
    ):
        monkeypatch.setattr(auto_mod, "client", lambda url: _BoomClient())
        group = self._build(
            monkeypatch,
            _spec("list_jobs", http_path="/crons/jobs"),
        )
        result = CliRunner().invoke(
            group,
            ["crons-list_jobs", "--base-url", "http://x"],
        )

        assert result.exit_code == 2
