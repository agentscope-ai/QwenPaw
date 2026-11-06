# -*- coding: utf-8 -*-
"""Committed public sources survive failed same-name candidate preparation."""

# Test setup observes the actual manager and resource events only.
# pylint: disable=protected-access
import asyncio
from contextlib import suppress

import pytest
import yaml

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.drivers.contracts import DriverCard
from .test_sdk_driver_lifecycle import (
    PLUGIN_ID,
    card,
    driver_plugin,
    events,
    seed_card,
    wait_until,
)


def manager_for(host):
    return host._workspaces["test"]._service_manager.services["driver_manager"]


async def label(host, scope=""):
    rows = await host.list_driver_capabilities("same", session_scope=scope)
    assert any(row["name"] == "echo" and row["enabled"] for row in rows)
    result = await host.call_driver("same", "echo", {}, session_scope=scope)
    return result.structured_content["label"]


async def replace(host, root, candidate, mode):
    if mode in {"register", "transient"}:
        await host.open_driver(
            candidate,
            session_scope=("session-a" if mode == "transient" else ""),
        )
    else:
        seed_card(root, "test", candidate)
        await getattr(manager_for(host), mode + "_driver")("same")


@pytest.mark.parametrize(
    "mode",
    ["register", "reload", "refresh", "transient"],
)
async def test_failed_same_name_candidate_keeps_old_public_calls_and_custody(
    tmp_path,
    mode,
):
    root = tmp_path / "host"
    scope = "session-a" if mode == "transient" else ""
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(
            card(config={"label": "old"}),
            session_scope=scope,
        )
        assert await label(host, scope) == "old"
        old_revision = events(context, "opened")[0][3]
        candidate = card(
            config={
                "label": "candidate",
                "wait_open": True,
                "fail_open": True,
            },
        )
        pending = asyncio.create_task(replace(host, root, candidate, mode))
        observations = []
        try:
            await wait_until(lambda: len(events(context, "open")) == 2)
            assert not events(context, "closed")
            try:
                observations.append(await label(host, scope))
            except SDKError as exc:
                observations.append(str(exc))
        finally:
            (tmp_path / "release-open").touch()
            with pytest.raises(
                SDKError,
                match="synthetic preparation failure",
            ):
                await pending
        try:
            observations.append(await label(host, scope))
        except SDKError as exc:
            observations.append(str(exc))
        # Candidate cleanup must leave the old committed connection open.
        assert len(events(context, "closed")) == 1
        assert events(context, "closed")[0][3] != old_revision
        assert len(events(context, "resource-close")) == 1
        assert observations == ["old", "old"], observations
        if scope:
            with pytest.raises(SDKError):
                await host.call_driver(
                    "same",
                    "echo",
                    {},
                    session_scope="other-session",
                )
        else:
            raw = yaml.safe_load(
                (
                    root / "workspaces/test/drivers/author-driver/same.yaml"
                ).read_text(),
            )
            assert raw["config"]["label"] == "candidate"
        await host.close_driver("same", session_scope=scope)
        assert len(events(context, "closed")) == 2
        assert len(events(context, "resource-close")) == 2
        await host.unload(PLUGIN_ID)
        host.assert_quiescent(PLUGIN_ID)


@pytest.mark.parametrize(
    "mode",
    ["register", "reload", "refresh", "transient"],
)
async def test_newer_same_name_candidate_wins_without_old_publication(
    tmp_path,
    mode,
):
    root = tmp_path / "host"
    scope = "session-a" if mode == "transient" else ""
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(
            card(config={"label": "old"}),
            session_scope=scope,
        )
        pending = asyncio.create_task(
            replace(
                host,
                root,
                card(config={"label": "superseded", "wait_open": True}),
                mode,
            ),
        )
        try:
            await wait_until(lambda: len(events(context, "open")) == 2)
            await replace(host, root, card(config={"label": "newest"}), mode)
            assert await label(host, scope) == "newest"
        finally:
            (tmp_path / "release-open").touch()
            with suppress(SDKError, RuntimeError, asyncio.CancelledError):
                await pending
        assert await label(host, scope) == "newest"
        if not scope:
            raw = yaml.safe_load(
                (
                    root / "workspaces/test/drivers/author-driver/same.yaml"
                ).read_text(),
            )
            assert raw["config"]["label"] == "newest"
        await host.close_driver("same", session_scope=scope)
        await wait_until(
            lambda: len(events(context, "closed")) == 3
            and len(events(context, "resource-close")) == 3,
        )


@pytest.mark.parametrize("action", ["disable", "delete", "deny", "whitelist"])
async def test_failed_candidate_does_not_override_later_restriction(
    tmp_path,
    action,
):
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"label": "old"}))
        with pytest.raises(SDKError, match="synthetic preparation failure"):
            await host.open_driver(card(config={"fail_open": True}))
        if action == "delete":
            await manager_for(host).delete_driver("same")
        elif action == "disable":
            await host.open_driver(card(enabled=False))
        elif action == "deny":
            await manager_for(host).sync_driver_policy(
                DriverCard(**card(effect="deny", config={"label": "old"})),
            )
        else:
            seed_card(root, "test", card(config={"label": "old", "tools": []}))
            await manager_for(host).refresh_driver("same")
        before = len(events(context, "invoke"))
        with pytest.raises(SDKError):
            await host.call_driver("same", "echo", {})
        assert len(events(context, "invoke")) == before


@pytest.mark.parametrize(
    "action",
    ["disable", "delete", "deny", "whitelist", "binding", "unaccepted-edit"],
)
async def test_candidate_never_masks_restrictions_or_unaccepted_edit(
    tmp_path,
    action,
):
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"label": "old"}))
        pending = asyncio.create_task(
            host.open_driver(
                card(config={"wait_open": True, "fail_open": True}),
            ),
        )
        try:
            await wait_until(lambda: len(events(context, "open")) == 2)
            if action == "delete":
                await manager_for(host).delete_driver("same")
            elif action == "disable":
                await host.open_driver(card(enabled=False))
            else:
                restricted = card(
                    effect="deny" if action == "deny" else "allow",
                    config={
                        "label": "old",
                        **({"tools": []} if action == "whitelist" else {}),
                    },
                )
                if action == "binding":
                    restricted["credentials"] = {
                        "oauth": {"kind": "oauth", "ref": "other"},
                    }
                if action == "unaccepted-edit":
                    restricted["endpoint"] = {"new": "not-yet-accepted"}
                seed_card(root, "test", restricted)
            before = len(events(context, "invoke"))
            with pytest.raises(SDKError):
                await host.call_driver("same", "echo", {})
            assert len(events(context, "invoke")) == before
        finally:
            (tmp_path / "release-open").touch()
            with pytest.raises(SDKError):
                await pending
        with pytest.raises(SDKError):
            await host.call_driver("same", "echo", {})


@pytest.mark.parametrize("approved", [False, True])
async def test_failed_candidate_preserves_ask_approval_before_old_invoke(
    tmp_path,
    approved,
):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(effect="ask", config={"label": "old"}))
        with pytest.raises(SDKError, match="synthetic preparation failure"):
            await host.open_driver(
                card(effect="ask", config={"fail_open": True}),
            )
        pending = asyncio.create_task(
            host.call_driver("same", "echo", {}, session_id="retained-ask"),
        )
        try:
            async with asyncio.timeout(3):
                while not (
                    requests := await host.approval_requests("retained-ask")
                ):
                    if pending.done():
                        await pending
                    await asyncio.sleep(0.005)
            assert not events(context, "invoke")
            assert await host.resolve_approval(
                requests[0].request_id,
                approved=approved,
            )
            if approved:
                assert (await pending).structured_content["label"] == "old"
                assert len(events(context, "invoke")) == 1
            else:
                with pytest.raises(SDKError):
                    await pending
                assert not events(context, "invoke")
        finally:
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending


async def test_failed_candidate_does_not_restore_revoked_credential(tmp_path):
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.credentials.types import CredentialRecord
    from qwenpaw.drivers.errors import CredentialNotFoundError

    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        store = AsyncCredentialStore(root / "workspaces/test/credentials.yaml")
        await store.put(
            CredentialRecord(
                ref="synthetic-oauth",
                kind="static",
                secrets={"value": "synthetic-token"},
            ),
        )
        credentials = {"oauth": {"kind": "static", "ref": "synthetic-oauth"}}
        await host.open_driver(
            card(credentials=credentials, config={"label": "old"}),
        )
        with pytest.raises(SDKError, match="synthetic preparation failure"):
            await host.open_driver(
                card(credentials=credentials, config={"fail_open": True}),
            )
        assert await label(host) == "old"
        pending = asyncio.create_task(
            host.call_driver("same", "echo", {"wait": True, "alias": "oauth"}),
        )
        try:
            await wait_until(lambda: len(events(context, "invoke")) == 2)
            await store.delete("synthetic-oauth")
        finally:
            (tmp_path / "release-call").touch()
            with pytest.raises(SDKError):
                await pending
        with pytest.raises(CredentialNotFoundError):
            await store.get("synthetic-oauth")


async def test_old_call_rechecks_disk_sample_after_new_candidate_reserved(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"label": "old"}))
        assert await label(host) == "old"
        first = asyncio.create_task(
            host.open_driver(
                card(
                    config={
                        "label": "candidate-one",
                        "wait_open": True,
                        "fail_open": True,
                    },
                ),
            ),
        )
        second = caller = None
        sampled, release_sample = asyncio.Event(), asyncio.Event()
        try:
            await wait_until(lambda: len(events(context, "open")) == 2)
            store = manager_for(host).card_store
            original_load = store.load
            intercepted = False

            async def load(*args, **kwargs):
                nonlocal intercepted
                value = await original_load(*args, **kwargs)
                if not intercepted:
                    intercepted = True
                    assert value.config["label"] == "candidate-one"
                    sampled.set()
                    await release_sample.wait()
                return value

            monkeypatch.setattr(store, "load", load)
            caller = asyncio.create_task(host.call_driver("same", "echo", {}))
            await asyncio.wait_for(sampled.wait(), 3)
            second = asyncio.create_task(
                host.open_driver(
                    card(
                        config={
                            "label": "candidate-two",
                            "wait_open": True,
                            "fail_open": True,
                        },
                    ),
                ),
            )
            await wait_until(lambda: len(events(context, "open")) == 3)
            release_sample.set()
            result = await asyncio.wait_for(caller, 3)
            assert result.structured_content["label"] == "old"
            assert not events(context, "closed")
        finally:
            release_sample.set()
            (tmp_path / "release-open").touch()
            outcomes = await asyncio.gather(
                *(task for task in (first, second) if task is not None),
                return_exceptions=True,
            )
            assert all(isinstance(outcome, SDKError) for outcome in outcomes)
            if caller is not None:
                await asyncio.gather(caller, return_exceptions=True)
        assert await label(host) == "old"
        await host.close_driver("same")
        assert len(events(context, "closed")) == 3
        assert len(events(context, "resource-close")) == 3
