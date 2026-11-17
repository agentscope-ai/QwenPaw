# -*- coding: utf-8 -*-
"""Verify that theme-token overrides reach real components in a browser.

The unit suite can only assert on the stylesheet text an override produces.
This script mounts `theme-verify.html` (a real component tree), applies
overrides through the public registry path, and reads the *computed* colours
back in both schemes. Run from the `console/` directory:

    python scripts/verify_theme_tokens.py

Requires Playwright's Chromium (`python -m playwright install chromium`).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CONSOLE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONSOLE_ROOT.parent
OUT_DIR = REPO_ROOT / "out"
PORT = 5199
URL = f"http://127.0.0.1:{PORT}/theme-verify.html"

# Each selector consumes a different family through a real stylesheet rule.
SELECTORS = {
    "page_bg": "#root > div",
    "card": "#root > div > div",
    "retry_button": "#root button",
    "error_text": "#root p",
    "text_secondary": "#probe-text",
}

# One swatch per representative role: backgrounds, borders, text, accent and
# the status colours. Each consumes its own custom property directly, so the
# computed value is the token itself rather than a token a shared rule happens
# to use.
ROLE_SELECTORS = {
    "bg": "role_bg",
    "surface": "role_surface",
    "border": "role_border",
    "text": "role_text",
    "accent": "role_accent",
    "error-text": "role_error_text",
    "success-bg": "role_success_bg",
    "warning-border": "role_warning_border",
    "info-text": "role_info_text",
}
for _token, _name in ROLE_SELECTORS.items():
    SELECTORS[_name] = f"#probe-role-{_token}"

# Stands in for App.tsx writing the user preset inline on <html>.
PRESET_BEFORE = {"--app-bg": "#0f0f0f"}
PRESET_AFTER = {"--app-bg": "#2a2a2a"}

OVERRIDE = {
    "bg": {"light": "#010203", "dark": "#040506"},
    "surface": {"light": "#070809", "dark": "#0a0b0c"},
    "surface-raised": {"light": "#0d0e0f", "dark": "#101112"},
    "border": {"light": "#131415", "dark": "#161718"},
    "text": {"light": "#191a1b", "dark": "#1c1d1e"},
    "text-secondary": {"light": "#1f2021", "dark": "#222324"},
    "text-tertiary": {"light": "#252627", "dark": "#28292a"},
    "border-subtle": {"light": "#2b2c2d", "dark": "#2e2f30"},
    "border-strong": {"light": "#313233", "dark": "#343536"},
    "accent": {"light": "#373839", "dark": "#3a3b3c"},
    "accent-hover": {"light": "#3d3e3f", "dark": "#404142"},
    "accent-ring": {"light": "#434445", "dark": "#464748"},
    "error-text": {"light": "#494a4b", "dark": "#4c4d4e"},
    "success-bg": {"light": "#4f5051", "dark": "#525354"},
    "warning-border": {"light": "#555657", "dark": "#58595a"},
    "info-text": {"light": "#5b5c5d", "dark": "#5e5f60"},
}

REQUIRED_CAPABILITY = "themeTokens"


def rgb(value: str) -> str:
    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    return f"rgb({red}, {green}, {blue})"


def wait_for_port(timeout: float = 180.0) -> None:
    """Poll the harness URL until vite answers with 200."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=5) as response:
                if response.status == 200:
                    return
                last = f"status {response.status}"
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(1.0)
    raise SystemExit(f"vite did not serve {URL} within {timeout}s: {last}")


def capture(page, scheme: str) -> dict:
    page.evaluate("scheme => window.__themeProbe.setScheme(scheme)", scheme)
    page.wait_for_timeout(120)
    return {
        name: page.evaluate("s => window.__themeProbe.read(s)", selector)
        for name, selector in SELECTORS.items()
    }


def collect_failures(report: dict, expects: list) -> list[str]:
    """Everything the run claims to prove, so a wrong result exits non-zero."""
    failures = []
    for name, prop, token, scheme in expects:
        got = report[f"override_{scheme}"][name].get(prop)
        want = rgb(OVERRIDE[token][scheme])
        if got != want:
            failures.append(
                f"{name}.{prop} [{scheme}] = {got!r}, want {want!r}",
            )

    after = report["after_dispose_light"]["page_bg"].get("backgroundColor")
    want_preset = rgb(PRESET_AFTER["--app-bg"])
    report["restored_after_dispose"] = after == want_preset
    if not report["restored_after_dispose"]:
        failures.append(
            "page_bg.backgroundColor after dispose = "
            f"{after!r}, want the new preset {want_preset!r}",
        )

    before = report["preset_before_light"]["page_bg"].get("backgroundColor")
    want_before = rgb(PRESET_BEFORE["--app-bg"])
    if before != want_before:
        failures.append(
            f"preset before the override = {before!r}, want {want_before!r}",
        )

    during = report["override_after_preset_change_light"]["page_bg"].get(
        "backgroundColor",
    )
    want_override = rgb(OVERRIDE["bg"]["light"])
    if during != want_override:
        failures.append(
            "an override stopped winning after the preset changed: "
            f"{during!r}, want {want_override!r}",
        )

    rejected = report.get("undeclared_rejected")
    if not isinstance(rejected, str) or rejected == "ACCEPTED":
        failures.append(
            f"a plugin that never declared themeTokens was accepted: {rejected!r}",
        )
    elif "themeTokens" not in rejected:
        failures.append(
            "the undeclared-token rejection does not name themeTokens: "
            f"{rejected!r}",
        )

    button = "retry_button"
    button_baseline = report["baseline_light"][button].get("backgroundColor")
    stacking = [
        ("stacked_light", "rgb(176, 176, 176)"),
        ("stacked_after_top_dispose", "rgb(160, 160, 160)"),
        ("stacked_after_all_dispose", button_baseline),
    ]
    for stage, want in stacking:
        got = report[stage][button].get("backgroundColor")
        if got != want:
            failures.append(
                f"{stage}.{button}.backgroundColor = {got!r}, want {want!r}",
            )
    return failures


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    log_path = OUT_DIR / "theme_tokens_vite.log"
    log_file = log_path.open("w", encoding="utf-8")
    vite_entry = CONSOLE_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_entry.exists():
        raise SystemExit(f"missing vite entry: {vite_entry}")
    server = subprocess.Popen(
        [
            "node",
            str(vite_entry),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--strictPort",
        ],
        cwd=str(CONSOLE_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_port()
        if server.poll() is not None:
            raise SystemExit(
                f"vite exited with {server.returncode}; see {log_path}",
            )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on(
                "pageerror",
                lambda exc: errors.append(f"pageerror: {exc}"),
            )
            page.on(
                "console",
                lambda msg: (
                    errors.append(f"console.{msg.type}: {msg.text}")
                    if msg.type in ("error", "warning")
                    else None
                ),
            )
            # A module script defers DOMContentLoaded until it has executed,
            # and the first vite request has to pre-bundle antd, so wait only
            # for the navigation commit and let the ready marker gate the rest.
            page.goto(URL, wait_until="commit", timeout=120_000)
            try:
                page.wait_for_selector(
                    "[data-probe-ready='1']",
                    timeout=90_000,
                )
            except Exception:
                print("PROBE NOT READY; browser messages:")
                for line in errors[-40:]:
                    print(" ", line)
                raise

            report: dict = {"url": URL, "override": OVERRIDE}

            report["baseline_light"] = capture(page, "light")
            report["baseline_dark"] = capture(page, "dark")

            # Stand in for the user preset, which App.tsx writes inline on
            # <html>. Everything below has to keep working with it present.
            page.evaluate(
                "values => window.__themeProbe.setPreset(values)",
                PRESET_BEFORE,
            )
            page.wait_for_timeout(120)
            report["preset_before_light"] = capture(page, "light")

            # A plugin that never declared the capability must be rejected, so
            # the failure surfaces at the call site instead of as a silent
            # no-op in the UI.
            report["undeclared_rejected"] = page.evaluate(
                """() => {
                    try {
                        window.__themeProbe.overrideRaw("probe-raw", {
                            accent: { light: "#ffffff", dark: "#000000" },
                        });
                        return "ACCEPTED";
                    } catch (error) {
                        return String(
                            error && error.message ? error.message : error,
                        );
                    }
                }""",
            )

            page.evaluate(
                "tokens => window.__themeProbe.override('probe', tokens)",
                OVERRIDE,
            )
            page.wait_for_timeout(150)
            report["override_light"] = capture(page, "light")
            report["override_dark"] = capture(page, "dark")
            page.screenshot(path=str(OUT_DIR / "theme_tokens_dark.png"))

            # The preset may change while an override is active; disposing it
            # must reveal the *current* preset, not the earlier one.
            page.evaluate(
                "values => window.__themeProbe.setPreset(values)",
                PRESET_AFTER,
            )
            page.wait_for_timeout(120)
            report["override_after_preset_change_light"] = capture(
                page,
                "light",
            )

            page.evaluate("() => window.__themeProbe.dispose('probe')")
            page.wait_for_timeout(150)
            report["after_dispose_light"] = capture(page, "light")
            page.evaluate(
                "values => window.__themeProbe.setPreset(values)",
                {"--app-bg": ""},
            )

            # Two plugins claim the same role: the later one wins, and undoing
            # them one at a time must walk back through each layer.
            page.evaluate(
                """() => {
                    window.__themeProbe.override("p-lower", {
                        accent: { light: "#a0a0a0", dark: "#a1a1a1" },
                    });
                    window.__themeProbe.override("p-upper", {
                        accent: { light: "#b0b0b0", dark: "#b1b1b1" },
                    });
                }""",
            )
            page.wait_for_timeout(150)
            report["stacked_light"] = capture(page, "light")
            page.evaluate("() => window.__themeProbe.dispose('p-upper')")
            page.wait_for_timeout(150)
            report["stacked_after_top_dispose"] = capture(page, "light")
            page.evaluate("() => window.__themeProbe.dispose('p-lower')")
            page.wait_for_timeout(150)
            report["stacked_after_all_dispose"] = capture(page, "light")

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        log_file.close()

    # Explicit expectations: a token that reaches the component must change the
    # computed colour to the declared value in the matching scheme.
    expects = [
        ("page_bg", "backgroundColor", "bg", "light"),
        ("card", "backgroundColor", "surface", "dark"),
        ("retry_button", "backgroundColor", "accent", "light"),
        ("error_text", "color", "error-text", "dark"),
        ("text_secondary", "color", "text-secondary", "light"),
    ]
    expects += [
        (selector, "backgroundColor", token, scheme)
        for token, selector in ROLE_SELECTORS.items()
        for scheme in ("light", "dark")
    ]
    failures = collect_failures(report, expects)

    report["checks"] = {"expected": len(expects), "failures": failures}
    target = OUT_DIR / "theme_tokens_verify.json"
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        "utf-8",
    )
    print(json.dumps(report["checks"], indent=2))
    print("restored_after_dispose:", report["restored_after_dispose"])
    print("undeclared_rejected:", report["undeclared_rejected"])
    print("report:", target)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
