# -*- coding: utf-8 -*-
"""Exercise built JavaScript in Chromium, without signing in or changing data."""

import os

import pytest


BASE_URL = os.environ.get("WELDON_TEST_CONSOLE_URL", "")


@pytest.mark.skipif(not BASE_URL, reason="Set WELDON_TEST_CONSOLE_URL to a running instance")
def test_built_login_survives_reload_and_tab_switch():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            url = BASE_URL.rstrip("/") + "/login?redirect=%2Fchat%2Flogin-smoke"

            def assert_login():
                page.locator('input[type="password"]').wait_for(timeout=20000)
                assert page.locator('button[type="submit"]').is_visible()
                assert "redirect=%2Fchat%2Flogin-smoke" in page.url
                assert not errors, errors

            page.goto(url, wait_until="networkidle")
            assert not errors, errors
            assert_login()
            other = browser.new_page()
            other.goto("about:blank")
            other.bring_to_front()
            page.bring_to_front()
            assert_login()
            page.reload(wait_until="networkidle")
            assert_login()
        finally:
            browser.close()
