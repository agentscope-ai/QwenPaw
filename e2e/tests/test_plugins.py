# -*- coding: utf-8 -*-
"""
QwenPaw Plugin Manager end-to-end tests.

UI-driven only: any pure API/contract checks for the Plugin Manager
endpoints belong in ``tests/integration/`` (which already covers them).

Cases:
- PLUGIN-001 P0  test_plugin_manager_page_loads
- COMPAT-001 P1  test_market_compat_tags_render
- COMPAT-002 P1  test_incompatible_install_warning_modal
- DATA-BASE-PATH-001 P1  test_data_context_console_preserves_nested_base_path
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import Page, expect

from pages.plugin_page import PluginPage
from mocks import plugin_market
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


@pytest.mark.ui_smoke
@pytest.mark.p1
@pytest.mark.plugins
@pytest.mark.test_id("DATA-BASE-PATH-001")
def test_data_context_console_preserves_nested_base_path(page: Page) -> None:
    prefix = "/api/frontend_plugin/tenant"
    origin = "https://qwenpaw.test"
    plugin_path = "/api/frontend_plugin/qwenpaw-data/files/ui/dist"
    main_path = f"{prefix}{plugin_path}/data-console/index.html"
    context_path = f"{prefix}{plugin_path}/context-console/index.html"
    app_dir = Path(__file__).resolve().parents[2] / "plugins/apps/qwenpaw-data"
    static_root = app_dir / "ui/public/data-console"
    static_path = f"{prefix}{plugin_path}/data-console/"
    bridge = (app_dir / "scripts/context-console/paw-bridge.js").read_text(
        encoding="utf-8",
    )
    api_requests = []
    replayed_bodies = []

    def serve(route) -> None:
        url = route.request.url
        path = urlparse(url).path
        if path == context_path:
            route.fulfill(
                status=200,
                content_type="text/html",
                body=(
                    f"<script>{bridge}</script>"
                    "<script>(async () => {"
                    "window.apiCallsCompleted = 0;"
                    "fetch('/api/qwenpaw-data/context/status').then(() => {"
                    "window.apiCallsCompleted += 1;});"
                    "const xhr = new XMLHttpRequest();"
                    "xhr.open('GET', '/api/qwenpaw-data/context/config');"
                    "xhr.onload = () => {window.apiCallsCompleted += 1;};"
                    "xhr.send();"
                    "const consumed = new Request("
                    "'/api/qwenpaw-data/context/replayed',"
                    "{method: 'POST', body: 'old'});"
                    "await consumed.text();"
                    "await fetch(consumed, {method: 'POST', body: 'new'}).then(() => {"
                    "window.apiCallsCompleted += 1;});"
                    "const fresh = new Request("
                    "'/api/qwenpaw-data/context/fresh',"
                    "{method: 'POST', body: 'fresh-body'});"
                    "await fetch(fresh).then(() => {"
                    "window.apiCallsCompleted += 1;});"
                    "})();</script>"
                ),
            )
        elif path.startswith(static_path):
            relative = unquote(path.removeprefix(static_path))
            target = (static_root / relative).resolve()
            if (
                static_root.resolve() not in target.parents
                or not target.is_file()
            ):
                route.abort()
            else:
                route.fulfill(status=200, path=target)
        elif path.startswith(f"{prefix}/api/"):
            if path.startswith(f"{prefix}/api/qwenpaw-data/context/"):
                api_requests.append(url)
            if path.endswith(("/replayed", "/fresh")):
                replayed_bodies.append(route.request.post_data)
            route.fulfill(
                status=200,
                content_type="application/json",
                body="{}",
            )
        else:
            route.abort()

    page.context.route("**/*", serve)
    page.goto(f"{origin}{main_path}", wait_until="domcontentloaded")
    entry = page.locator('[aria-label="数据语义配置中心"]')
    entry.wait_for(state="visible")
    with page.expect_popup() as popup_info:
        entry.click()
    context_page = popup_info.value
    context_page.wait_for_load_state("domcontentloaded")
    context_page.wait_for_function("window.apiCallsCompleted === 4")

    outcomes = context_page.evaluate(
        """async () => {
            const aborted = AbortSignal.abort();
            const live = new AbortController().signal;
            const outcomes = {};
            for (const [name, requestSignal, init] of [
                ["omitted", aborted],
                ["undefined", aborted, {signal: undefined}],
                ["override", aborted, {signal: live}],
                ["null", aborted, {signal: null}],
                ["inherited-override", aborted, Object.create({signal: live})],
                ["aborted-override", live, {signal: aborted}],
            ]) {
                const request = new Request(
                    `/api/qwenpaw-data/context/${name}`,
                    {signal: requestSignal},
                );
                try {
                    const response = init === undefined
                        ? await fetch(request)
                        : await fetch(request, init);
                    outcomes[name] = response.status;
                } catch (error) {
                    outcomes[name] = error.name;
                }
            }
            return outcomes;
        }""",
    )

    assert context_page.url == f"{origin}{context_path}#/data-source"
    assert api_requests == [
        f"{origin}{prefix}/api/qwenpaw-data/context/status",
        f"{origin}{prefix}/api/qwenpaw-data/context/config",
        f"{origin}{prefix}/api/qwenpaw-data/context/replayed",
        f"{origin}{prefix}/api/qwenpaw-data/context/fresh",
        f"{origin}{prefix}/api/qwenpaw-data/context/override",
        f"{origin}{prefix}/api/qwenpaw-data/context/null",
        f"{origin}{prefix}/api/qwenpaw-data/context/inherited-override",
    ]
    assert replayed_bodies == ["new", "fresh-body"]
    assert outcomes == {
        "omitted": "AbortError",
        "undefined": "AbortError",
        "override": 200,
        "null": 200,
        "inherited-override": 200,
        "aborted-override": "AbortError",
    }


@pytest.mark.ui_smoke
@pytest.mark.p1
@pytest.mark.plugins
@pytest.mark.test_id("DATA-BASE-PATH-002")
@pytest.mark.parametrize("prefix", ["", "/qwenpaw"], ids=["root", "mounted"])
def test_data_context_bridge_preserves_request_options(page: Page, prefix: str):
    origin = "https://qwenpaw.test"
    context_path = "/api/frontend_plugin/qwenpaw-data/files/ui/dist/context-console/index.html"
    page.route(
        f"{origin}{prefix}{context_path}",
        lambda route: route.fulfill(body="<html></html>", content_type="text/html"),
    )
    page.goto(f"{origin}{prefix}{context_path}")
    page.evaluate(
        """() => {
            window.fetch = async (input, init) => {
                const request = new Request(input, init);
                return {
                    url: request.url,
                    credentials: request.credentials,
                    redirect: request.redirect,
                    cache: request.cache,
                    mode: request.mode,
                    referrerPolicy: request.referrerPolicy,
                    integrity: request.integrity,
                    keepalive: request.keepalive,
                };
            };
        }""",
    )
    app_dir = Path(__file__).resolve().parents[2] / "plugins/apps/qwenpaw-data"
    page.add_script_tag(path=app_dir / "scripts/context-console/paw-bridge.js")

    preserved, overridden = page.evaluate(
        """async () => {
            const request = new Request('/api/qwenpaw-data/context/status?probe=1', {
                credentials: 'omit', redirect: 'manual', cache: 'no-store',
                mode: 'same-origin', referrerPolicy: 'no-referrer',
                integrity: 'sha256-test', keepalive: true,
            });
            const init = Object.assign(Object.create({redirect: 'error'}), {
                credentials: 'include', cache: 'reload', keepalive: false,
                referrerPolicy: undefined,
            });
            return [await fetch(request), await fetch(request, init)];
        }""",
    )
    assert preserved == {
        "url": f"{origin}{prefix}/api/qwenpaw-data/context/status?probe=1",
        "credentials": "omit",
        "redirect": "manual",
        "cache": "no-store",
        "mode": "same-origin",
        "referrerPolicy": "no-referrer",
        "integrity": "sha256-test",
        "keepalive": True,
    }
    assert overridden == {
        **preserved,
        "credentials": "include",
        "redirect": "error",
        "cache": "reload",
        "keepalive": False,
    }


# ============================================================================
# PLUGIN-001 P0 — Plugin Manager page loads
# ============================================================================


@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.plugins
class TestPluginManagerPageLoads:
    """PLUGIN-001: /plugin-manager renders header, install button, two tabs."""

    @pytest.mark.test_id("PLUGIN-001")
    def test_plugin_manager_page_loads(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name

        log_test_step("1. Navigate to /plugin-manager")
        plugin_page.open()

        log_test_step("2. 'Install Plugin' button visible (page-ready signal)")
        expect(
            plugin_page.page.locator(plugin_page.INSTALL_BTN).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_step("3. 'Installed' and 'Official' tabs both visible")
        expect(
            plugin_page.page.locator(plugin_page.TAB_INSTALLED).first
        ).to_be_visible(timeout=plugin_page.timeout)
        expect(
            plugin_page.page.locator(plugin_page.TAB_OFFICIAL).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")


# ============================================================================
# COMPAT-001/002 P1 — Plugin Market version compatibility (upstream #5661)
#
# Market catalog data comes from the network (platform.agentscope.io
# proxy), so the catalog / version / install endpoints are intercepted
# with page.route mocks; all UI interactions and assertions stay real.
# ============================================================================


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.plugins
class TestPluginCompatibility:
    """Market tab compat tags + incompatible-install warning modal."""

    def _open_market_tab(self, plugin_page: PluginPage) -> None:
        """Register mocks, open the plugin market and switch to list view."""
        plugin_market.register(plugin_page.page)
        plugin_page.open()
        plugin_page.page.locator(plugin_page.TAB_MARKET).first.click()
        # The market defaults to card view; the catalog rows the assertions
        # rely on only render in list view. The toggle lives inside the
        # ACTIVE pane (MARKET_LIST_TOGGLE carries the pane scope): every
        # pane renders its own toggle with identical aria-labels, so an
        # unscoped locator resolved to the hidden Installed pane's toggle.
        # The old bare ``except: pass`` swallowed that failed click and
        # left the Market pane in card view, where no catalogRow renders
        # at all (failure screenshot 2026-10-14: Market tab active, both
        # mocked cards still in card view). A failed switch is now a
        # loud failure instead of a silent wrong-view assertion.
        list_toggle = plugin_page.page.locator(
            plugin_page.MARKET_LIST_TOGGLE
        ).first
        list_toggle.click(timeout=plugin_page.timeout)
        plugin_page.page.locator(plugin_page.MARKET_ROW).first.wait_for(
            state="visible", timeout=plugin_page.timeout
        )

    @pytest.mark.test_id("COMPAT-001")
    def test_market_compat_tags_render(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = plugin_page.page

        log_test_step(
            "1. Open Market tab with mocked catalog (1 compat + 1 legacy)"
        )
        self._open_market_tab(plugin_page)

        log_test_step(
            "2. Compatible plugin row shows a green 'QwenPaw 2.x' tag"
        )
        compat_row = (
            page.locator(plugin_page.MARKET_ROW)
            .filter(has_text=plugin_market.COMPATIBLE_PLUGIN_NAME)
            .first
        )
        expect(compat_row).to_be_visible(timeout=plugin_page.timeout)
        green_tag = compat_row.locator(plugin_page.COMPAT_TAG_GREEN).first
        expect(green_tag).to_be_visible(timeout=plugin_page.timeout)
        assert "2.x" in (
            green_tag.inner_text() or ""
        ), f"green tag text unexpected: {green_tag.inner_text()!r}"

        log_test_step(
            "3. Incompatible plugin row shows an orange 'QwenPaw 1.x' tag"
        )
        legacy_row = (
            page.locator(plugin_page.MARKET_ROW)
            .filter(has_text=plugin_market.INCOMPATIBLE_PLUGIN_NAME)
            .first
        )
        expect(legacy_row).to_be_visible(timeout=plugin_page.timeout)
        orange_tag = legacy_row.locator(plugin_page.COMPAT_TAG_ORANGE).first
        expect(orange_tag).to_be_visible(timeout=plugin_page.timeout)
        assert "1.x" in (
            orange_tag.inner_text() or ""
        ), f"orange tag text unexpected: {orange_tag.inner_text()!r}"

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")

    @pytest.mark.test_id("COMPAT-002")
    def test_incompatible_install_warning_modal(
        self,
        plugin_page: PluginPage,
        request: pytest.FixtureRequest,
    ) -> None:
        test_name = request.node.name
        page = plugin_page.page

        log_test_step("1. Open Market tab with mocked catalog")
        self._open_market_tab(plugin_page)

        log_test_step("2. Click Install on the incompatible plugin")
        legacy_row = (
            page.locator(plugin_page.MARKET_ROW)
            .filter(has_text=plugin_market.INCOMPATIBLE_PLUGIN_NAME)
            .first
        )
        expect(legacy_row).to_be_visible(timeout=plugin_page.timeout)
        # Card view reveals the install action only on hover.
        legacy_row.hover()
        page.wait_for_timeout(300)
        legacy_row.locator(plugin_page.MARKET_INSTALL_BTN).first.click()

        log_test_step("3. 'Compatibility Warning' Modal.confirm appears")
        modal = page.locator(plugin_page.COMPAT_MODAL).first
        expect(modal).to_be_visible(timeout=plugin_page.timeout)
        expect(
            page.locator(plugin_page.COMPAT_MODAL_TITLE).first
        ).to_be_visible(timeout=plugin_page.timeout)

        log_test_step(
            "4. Confirm 'Install anyway' — modal closes (install mocked)"
        )
        page.locator(plugin_page.COMPAT_MODAL_OK).first.click()
        expect(modal).not_to_be_visible(timeout=plugin_page.timeout)

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
