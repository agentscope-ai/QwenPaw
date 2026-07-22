# -*- coding: utf-8 -*-
"""Desktop release verification script.

Drives a running QwenPaw desktop backend (either Tauri packaging flavour:
tauri-win / tauri-mac) end-to-end:

1. ``GET /api/version`` — health + version match.
2. ``GET /``           — frontend HTML served.
3. ``PUT /api/models/<provider>/config``            — install API key.
4. ``POST /api/models/<provider>/models``           — register the chat model
                                                       (newer aliases like
                                                       qwen3.6-plus aren't in
                                                       the built-in catalogue).
5. ``PUT /api/models/active``                       — mark it active globally.
6. **UI single-round factual Q&A**                  — drive the real SPA:
   - Open the page and wait for the chat input to render.
   - Send "What is the tallest mountain in the world?" via the
     input box.
   - Assert the AI bubble mentions "Everest".

   This proves the full path: install package -> launch -> render UI ->
   send message via input box -> receive bubble back with correct answer.

UI flavours:
- ``--ui-mode tauri-macos``    Playwright + headless WebKit (same engine as
                               the Tauri webview on macOS).
- ``--ui-mode tauri-windows``  Playwright + headless Chromium (same engine
                               family as Tauri's WebView2 on Windows).

Designed to be invoked by ``.github/workflows/desktop-release.yml`` after the
desktop server has been booted on ``--base-url``. The API layer uses only
the Python standard library; UI drivers lazy-import Playwright so callers
without it installed can still use ``--skip-ui``.

Exit codes:
    0  all assertions pass
    1  assertion / HTTP / UI failure
    2  argument / configuration error
    3  UI driver could not be initialised (missing browser / driver)
"""

from __future__ import annotations

import abc
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "qwen3.6-plus"
DEFAULT_PROVIDER = "dashscope"
DEFAULT_TIMEOUT = 120
SESSION_ID = "release-verify-session"
USER_ID = "release-verify-user"

# Selectors come straight from e2e/pages/chat_page.py so they stay in sync
# with what the real UI tests expect.
SEL_INPUT = "textarea.qwenpaw-sender-input"
SEL_SEND_BTN = "button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary"
SEL_USER_BUBBLE = ".qwenpaw-bubble.qwenpaw-bubble-end"
SEL_AI_BUBBLE = ".qwenpaw-bubble.qwenpaw-bubble-start"


# =============================================================================
# HTTP helper
# =============================================================================


def _http(
    method: str,
    url: str,
    body: dict | None = None,
    timeout: int = 30,
) -> str:
    """Issue an HTTP request and return the decoded body text.

    Raises ``RuntimeError`` with a readable message on any failure so callers
    can surface it directly via ``::error::`` annotations.
    """
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            f"HTTP {exc.code} {method} {url}: {detail[:300]}",
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Network error {method} {url}: {exc.reason}",
        ) from exc


# =============================================================================
# API-level verification
# =============================================================================


def health_check(base_url: str) -> str:
    """Verify ``/api/version`` and return the reported version string."""
    body = _http("GET", f"{base_url}/api/version")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"/api/version returned non-JSON: {body[:200]}",
        ) from exc
    version = payload.get("version") or ""
    if not version:
        raise RuntimeError(
            f"/api/version missing 'version' field: {body[:200]}",
        )
    print(f"PASS  /api/version -> {version}")
    return version


def verify_frontend(base_url: str) -> None:
    """Verify the bundled console frontend is served at ``/``."""
    body = _http("GET", f"{base_url}/")
    lower = body.lower()
    if "<html" not in lower:
        raise RuntimeError(
            f"Frontend root did not return HTML (first 200 chars): "
            f"{body[:200]}",
        )
    if "qwenpaw" not in lower:
        raise RuntimeError(
            "Frontend HTML does not mention QwenPaw — wrong bundle?",
        )
    print("PASS  GET / -> frontend HTML served")


def configure_provider(
    base_url: str,
    provider_id: str,
    api_key: str,
) -> None:
    """Write the DashScope API key into ProviderManager."""
    _http(
        "PUT",
        f"{base_url}/api/models/{provider_id}/config",
        body={"api_key": api_key},
    )
    print(f"PASS  configured provider '{provider_id}'")


def ensure_model(
    base_url: str,
    provider_id: str,
    model: str,
) -> None:
    """Register ``model`` on ``provider_id`` if it isn't already known.

    DashScope ships only a few model ids in the built-in catalogue
    (``qwen3-max`` / ``deepseek-v3.2`` / ...), so verifying against newer
    aliases like ``qwen3.6-plus`` requires an explicit add first. The
    endpoint returns 201 on first add; later runs may 4xx because the model
    already exists — both outcomes are fine for our purposes.
    """
    try:
        _http(
            "POST",
            f"{base_url}/api/models/{provider_id}/models",
            body={"id": model, "name": model},
        )
        print(f"PASS  registered model '{model}' on '{provider_id}'")
    except RuntimeError as exc:
        # 4xx (e.g. 409 already-registered) is expected and downgraded
        # to info; 5xx and others are likely real failures and surface
        # as warnings so they show up in CI logs.
        msg = str(exc)
        is_4xx = (
            any(
                f" {code} " in f" {msg} " or f"HTTP {code}" in msg
                for code in (400, 401, 403, 404, 409, 422)
            )
            or "already" in msg.lower()
        )
        if is_4xx:
            print(f"INFO  add-model: {exc}")
        else:
            print(f"WARN  add-model unexpected: {exc}", file=sys.stderr)


def set_active_model(
    base_url: str,
    provider_id: str,
    model: str,
) -> None:
    """Mark ``provider_id/model`` as the global active LLM."""
    _http(
        "PUT",
        f"{base_url}/api/models/active",
        body={
            "provider_id": provider_id,
            "model": model,
            "scope": "global",
        },
    )
    print(f"PASS  active model -> {provider_id}/{model}")


# =============================================================================
# UI driver abstraction
# =============================================================================


class UIDriverInitError(RuntimeError):
    """Raised when a UI driver cannot start (missing browser / driver)."""


class UIDriver(abc.ABC):
    """High-level interface implemented by each platform-specific driver."""

    @abc.abstractmethod
    def open(self, url: str) -> None:
        """Navigate to ``url`` and wait until the chat input is visible."""

    @abc.abstractmethod
    def chat_one_round(self, message: str, timeout: int) -> str:
        """Send ``message`` and return the resulting AI bubble's full text."""

    @abc.abstractmethod
    def close(self) -> None:
        """Tear down browser / webdriver resources (best effort)."""


class PlaywrightDriver(UIDriver):
    """Headless browser driver backed by Playwright.

    Supports both Chromium (for Legacy desktop) and WebKit (for Tauri
    macOS — same engine as the Tauri webview). The ``browser`` arg
    selects which backend to launch.
    """

    INPUT_VISIBLE_TIMEOUT_MS = 60_000
    NAVIGATE_TIMEOUT_MS = 60_000

    def __init__(
        self,
        browser: str = "chromium",
        screenshot_dir: str | None = None,
        headless: bool = True,
        cdp_url: str = "",
    ) -> None:
        self._screenshot_dir = screenshot_dir
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise UIDriverInitError(
                "playwright is not installed; "
                "run 'pip install -r scripts/verify/"
                "requirements-verify.txt'",
            ) from exc

        try:
            self._pw = sync_playwright().start()
            if cdp_url:
                self._browser = self._pw.chromium.connect_over_cdp(cdp_url)
                for i in range(60):
                    if (
                        self._browser.contexts
                        and self._browser.contexts[0].pages
                    ):
                        break
                    if i and i % 10 == 0:
                        print(
                            f"  CDP: waiting for page "
                            f"({i * 0.5:.0f}s elapsed)...",
                        )
                    time.sleep(0.5)
                if (
                    not self._browser.contexts
                    or not self._browser.contexts[0].pages
                ):
                    raise UIDriverInitError(
                        "CDP connected but no page appeared within 30s",
                    )
                self._context = self._browser.contexts[0]
                self._page = self._context.pages[0]
            else:
                launcher = getattr(self._pw, browser, None)
                if launcher is None:
                    raise UIDriverInitError(
                        f"playwright has no browser '{browser}'",
                    )
                self._browser = launcher.launch(headless=headless)
                self._context = self._browser.new_context()
                self._page = self._context.new_page()
        except UIDriverInitError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UIDriverInitError(
                f"failed to start {browser}: {exc}",
            ) from exc

    def _screenshot(self, name: str) -> None:
        """Best-effort screenshot. Never raises."""
        if not self._screenshot_dir:
            return
        try:
            path = os.path.join(self._screenshot_dir, f"{name}.png")
            self._page.screenshot(path=path, full_page=True)
            print(f"  [screenshot] {path}")
        except Exception:  # noqa: BLE001
            pass

    def open(self, url: str) -> None:
        self._page.goto(url, timeout=self.NAVIGATE_TIMEOUT_MS)
        self._page.locator(SEL_INPUT).first.wait_for(
            state="visible",
            timeout=self.INPUT_VISIBLE_TIMEOUT_MS,
        )
        self._screenshot("01-page-loaded")

    def wait_for_input(self) -> None:
        """Wait for chat input on the current page (no navigation)."""
        self._page.locator(SEL_INPUT).first.wait_for(
            state="visible",
            timeout=self.INPUT_VISIBLE_TIMEOUT_MS,
        )
        self._screenshot("01-page-loaded")

    # Same 4-channel disabled detection as e2e/pages/chat_page.py:
    #   1. button.disabled property
    #   2. disabled attribute
    #   3. aria-disabled="true"
    #   4. framework-injected disabled / loading class
    _JS_SEND_DISABLED = """() => {
      const btn = document.querySelector(
        'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
      );
      if (!btn) return true;
      if (btn.disabled === true) return true;
      if (btn.hasAttribute('disabled')) return true;
      if (btn.getAttribute('aria-disabled') === 'true') return true;
      const cls = btn.className || '';
      if (/qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls)) {
        return true;
      }
      return false;
    }"""

    def _wait_for_send_enabled(self, timeout: int) -> None:
        """Block until the send button is clickable (or timeout).

        The chat UI throttles the button while a previous round is still
        streaming. Trying to fill+click during that window produces a
        no-op and leaves the verifier waiting on a bubble that never
        comes.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            disabled = self._page.evaluate(self._JS_SEND_DISABLED)
            if not disabled:
                return
            time.sleep(0.5)
        raise RuntimeError(
            f"Send button never became enabled within {timeout}s",
        )

    # End-of-streaming detection JS shared with e2e/pages/chat_page.py.
    # Two paths, whichever fires first releases the wait:
    #   Path A: send button went through a disabled -> enabled transition
    #           (we must have seen disabled at least once during this
    #           round, then seen it come back to enabled) AND the last
    #           AI bubble has at least 2 real characters after stripping
    #           "Thinking" / "Loading" placeholders.
    #   Path B: last AI bubble content has been unchanged for >= 2500ms
    #           and has at least 2 real characters (fallback for the
    #           known "button stays forever disabled" bug). With
    #           bootstrap pre-skipped (see verify_ui_chat docstring),
    #           rounds are short single-step replies; 2.5s is plenty.
    _JS_BUBBLE_READY = """(expectedCount) => {
      const btn = document.querySelector(
        'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
      );
      let btnDisabled = true;
      if (btn) {
        const cls = btn.className || '';
        const disabledByCls = /qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls);
        const disabledByAttr = btn.disabled === true
          || btn.hasAttribute('disabled')
          || btn.getAttribute('aria-disabled') === 'true';
        btnDisabled = disabledByAttr || disabledByCls;
      }

      // Track whether we have ever seen the button in the disabled
      // state during this round. Path A only fires after a full
      // disabled -> enabled transition, not when the button simply
      // hasn't been disabled yet (which looks the same as "enabled").
      const stateKey = '__qwenpaw_btn_was_disabled__';
      if (btnDisabled) {
        window[stateKey] = true;
      }
      const sawDisabled = !!window[stateKey];
      const btnRecovered = sawDisabled && !btnDisabled;

      const aiMsgs = document.querySelectorAll(
        '.qwenpaw-bubble.qwenpaw-bubble-start'
      );
      if (aiMsgs.length <= expectedCount) {
        return false;
      }
      const last = aiMsgs[aiMsgs.length - 1];
      const raw = (last.innerText || '').trim();
      const stripped = raw
        .replace(/Thinking/gi, '')
        .replace(/Loading/gi, '')
        .trim();
      const hasRealText = stripped.length >= 2;

      let contentStable = false;
      if (hasRealText) {
        const key = '__qwenpaw_ai_stable_cache__';
        const now = Date.now();
        const cache = window[key] || {};
        if (cache.text !== raw) {
          window[key] = { text: raw, since: now };
        } else if ((now - cache.since) >= 2500) {
          // 2500ms is empirical — long enough to ride out SSE chunk
          // gaps on a busy CI runner, short enough to avoid extending
          // the verify step. Revisit if streaming cadence changes.
          contentStable = true;
        }
      }

      if (btnRecovered && hasRealText) {
        return true;
      }
      if (contentStable) {
        return true;
      }
      return false;
    }"""

    def _wait_previous_round_idle(self) -> None:
        """Wait for any prior round's streaming to finish.

        Runs the same dual-path JS as
        ``e2e/pages/chat_page.py::send_message``: button recovered to
        enabled **or** last AI bubble content stable for 1500ms.  Uses
        a separate cache key so it doesn't clobber Gate 2's cache.
        Best-effort: timeouts (8s) are swallowed.
        """
        if self._page.locator(SEL_USER_BUBBLE).count() == 0:
            return
        try:
            _idle_js = """() => {
  const btn = document.querySelector(
    'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary',
  );
  if (btn) {
    const cls = btn.className || '';
    const disabledByCls =
      /qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls);
    const disabledByAttr = btn.disabled === true
      || btn.hasAttribute('disabled')
      || btn.getAttribute('aria-disabled') === 'true';
    if (!disabledByAttr && !disabledByCls) return true;
  }
  const aiMsgs = document.querySelectorAll(
    '.qwenpaw-bubble.qwenpaw-bubble-start',
  );
  if (aiMsgs.length === 0) return true;
  const last = aiMsgs[aiMsgs.length - 1];
  const raw = (last.innerText || '').trim();
  const key = '__qwenpaw_send_idle_cache__';
  const now = Date.now();
  const cache = window[key] || {};
  if (cache.text !== raw) {
    window[key] = { text: raw, since: now };
    return false;
  }
  // 1500ms is empirical — tuned against real CI runners. May need
  // adjustment if SSE chunk cadence changes.
  return (now - cache.since) >= 1500;
}"""
            self._page.wait_for_function(_idle_js, timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                self._page.evaluate(
                    "() => { try { delete window."
                    "__qwenpaw_send_idle_cache__; } catch(e) {} }",
                )
            except Exception:  # noqa: BLE001
                pass

    def chat_one_round(self, message: str, timeout: int) -> str:
        self._wait_previous_round_idle()

        ai_count_before = self._page.locator(SEL_AI_BUBBLE).count()
        user_count_before = self._page.locator(SEL_USER_BUBBLE).count()

        # Defensive input flow borrowed from e2e/pages/chat_page.py:
        # focus the textarea, clear any leftover text, fill the new
        # message, then click send (or fall back to Enter).
        input_box = self._page.locator(SEL_INPUT).first
        input_box.click()
        time.sleep(0.2)
        input_box.fill("")
        time.sleep(0.2)
        input_box.fill(message)
        time.sleep(0.5)

        # Reset Gate 2 state-machine caches so a fresh round starts
        # from a clean slate (prior round's disabled-flag / content
        # stable cache must not carry over).
        try:
            self._page.evaluate(
                "() => { delete window.__qwenpaw_btn_was_disabled__;"
                " delete window.__qwenpaw_ai_stable_cache__; }",
            )
        except Exception:  # noqa: BLE001
            pass

        send_btn = self._page.locator(SEL_SEND_BTN).first
        if send_btn.is_visible() and send_btn.is_enabled():
            send_btn.click()
        else:
            input_box.press("Enter")

        # Gold-standard "message actually sent" check: a new user bubble
        # must appear. Treating button-disabled as the signal turns out
        # to be racy (e2e/ tried it and dropped it); the user bubble
        # showing up is what the SPA actually does once the request was
        # accepted.
        send_timeout_ms = min(30, timeout) * 1000
        try:
            self._page.wait_for_function(
                """(expected) => {
                  const msgs = document.querySelectorAll(
                    '.qwenpaw-bubble.qwenpaw-bubble-end'
                  );
                  return msgs.length > expected;
                }""",
                arg=user_count_before,
                timeout=send_timeout_ms,
            )
        except Exception:  # noqa: BLE001
            # Fall back to pressing Enter — some layouts ignore the
            # send button click but accept Enter on the textarea.
            try:
                input_box.click()
                time.sleep(0.2)
                input_box.press("Enter")
                self._page.wait_for_function(
                    """(expected) => {
                      const msgs = document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-end'
                      );
                      return msgs.length > expected;
                    }""",
                    arg=user_count_before,
                    timeout=send_timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"User bubble never appeared for: {message!r}",
                ) from exc

        self._screenshot("02-message-sent")
        timeout_ms = timeout * 1000

        # Gate 1: a new AI bubble appears in the DOM.
        try:
            self._page.wait_for_function(
                """(expectedCount) => {
                  const aiMsgs = document.querySelectorAll(
                    '.qwenpaw-bubble.qwenpaw-bubble-start'
                  );
                  return aiMsgs.length > expectedCount;
                }""",
                arg=ai_count_before,
                timeout=timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"No new AI bubble within {timeout}s for: {message!r}",
            ) from exc

        # Gate 2: streaming actually finished. Path A (button enabled +
        # real text) or Path B (content stable >= 2500ms + real text)
        # may release first; whichever fires accepts the round.
        try:
            self._page.wait_for_function(
                self._JS_BUBBLE_READY,
                arg=ai_count_before,
                timeout=timeout_ms,
            )
        except Exception:  # noqa: BLE001
            # Don't fail outright — return whatever text we have so the
            # caller's substring assertion can still succeed when most
            # of the streaming arrived but the end-of-stream signal was
            # lost (a known SPA quirk e2e/ also tolerates).
            pass

        self._screenshot("03-reply-received")
        last_locator = self._page.locator(SEL_AI_BUBBLE).last
        try:
            raw = (last_locator.inner_text() or "").strip()
        except Exception:  # noqa: BLE001
            return ""
        # Strip placeholders so callers don't accidentally satisfy a
        # substring assertion on the loading indicator.
        return raw.replace("Thinking", "").replace("Loading", "").strip()

    def close(self) -> None:
        for closer in (
            getattr(self, "_page", None),
            getattr(self, "_context", None),
            getattr(self, "_browser", None),
        ):
            if closer is None:
                continue
            try:
                closer.close()
            except Exception:  # noqa: BLE001
                pass
        pw = getattr(self, "_pw", None)
        if pw is not None:
            try:
                pw.stop()
            except Exception:  # noqa: BLE001
                pass


UI_MODES = ("tauri-macos", "tauri-windows")


def make_driver(
    ui_mode: str,
    screenshot_dir: str | None = None,
    headless: bool = True,
    cdp_url: str = "",
) -> UIDriver:
    """Build a concrete ``UIDriver`` for the requested mode."""
    if ui_mode == "tauri-macos":
        return PlaywrightDriver("webkit", screenshot_dir, headless)
    if ui_mode == "tauri-windows":
        return PlaywrightDriver(
            "chromium",
            screenshot_dir,
            headless,
            cdp_url,
        )
    raise UIDriverInitError(f"unknown ui-mode: {ui_mode!r}")


# =============================================================================
# UI-level verification (three-round conversation)
# =============================================================================


def verify_ui_loaded(
    driver: UIDriver,
    base_url: str,
    skip_navigate: bool = False,
) -> None:
    """Verify the SPA loads and the chat input becomes visible.

    Runs without an API key — proves the desktop bundle's frontend
    is wired up correctly. Catches broken Vite bundles, missing
    asset paths, CSP misconfigurations, and Tauri webview load
    failures even when LLM credentials are unavailable.
    """
    if skip_navigate:
        print("--> CDP mode: waiting for SPA on existing page")
        driver.wait_for_input()
    else:
        print(f"--> opening UI at {base_url}")
        driver.open(base_url)
    print("PASS  UI loaded, chat input visible")


def verify_ui_chat(
    driver: UIDriver,
    timeout: int,
) -> None:
    """Drive the loaded SPA with one factual question to prove LLM works.

    Assumes the SPA is already loaded by ``verify_ui_loaded``. Uses a
    single-round factual question ("tallest mountain") to avoid
    multi-turn SPA timing races. Any of Everest / 珠穆朗玛 / 8848 in
    the reply proves the full path:
    textarea filled -> send clicked -> backend received -> LLM
    invoked -> SSE streamed -> AI bubble rendered with real content.
    """
    expected_any = (
        "Everest",
        "everest",
        "珠穆朗玛",
        "Chomolungma",
        "8848",
        "8849",
    )

    question = "What is the tallest mountain in the world?"
    print(f"--> sending: {question!r}")
    reply = driver.chat_one_round(question, timeout)
    preview = reply.replace("\n", " ")[:200]
    print(f"<-- agent: {preview}...")

    if not any(kw in reply for kw in expected_any):
        raise RuntimeError(
            f"LLM reply does not mention Everest / 珠穆朗玛 / 8848. "
            f"Got: {reply[:500]}",
        )
    print("PASS  LLM responded with correct factual answer")


def _run_llm_with_retry(
    driver: UIDriver,
    timeout: int,
    retries: int,
    allow_flaky: bool,
) -> int:
    """Run the LLM chat round with retries; return process exit code."""
    attempts = max(1, retries + 1)
    last_err: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            verify_ui_chat(driver, timeout)
            return 0
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(
                f"WARN  LLM round attempt {attempt}/{attempts} "
                f"failed: {exc}",
                file=sys.stderr,
            )
            if attempt < attempts:
                backoff = 5 * (2 ** (attempt - 1))
                print(f"  retrying in {backoff}s...")
                time.sleep(backoff)
    if allow_flaky:
        print(
            "::warning::LLM verification failed after "
            f"{attempts} attempts but --allow-flaky-llm is set; "
            f"continuing. Last error: {last_err}",
        )
        return 0
    print(
        f"FAIL  LLM verification failed after {attempts} attempts: "
        f"{last_err}",
        file=sys.stderr,
    )
    return 1


# =============================================================================
# main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a running QwenPaw desktop backend end-to-end: API "
            "health + provider config + single-round UI chat."
        ),
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the running desktop backend, e.g. "
        "http://127.0.0.1:8088",
    )
    parser.add_argument(
        "--ui-mode",
        choices=UI_MODES,
        required=True,
        help="UI driver flavour. 'tauri-macos' uses Playwright + WebKit; "
        "'tauri-windows' uses Playwright + Chromium over CDP.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("QWENPAW_DASHSCOPE_API_KEY", ""),
        help="DashScope API key. Falls back to env "
        "QWENPAW_DASHSCOPE_API_KEY. Empty value -> auto skip-chat.",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        help=f"Provider id (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model id (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Skip the entire LLM chain (provider config + UI chat). "
        "Implied when no API key is available.",
    )
    parser.add_argument(
        "--skip-ui",
        action="store_true",
        help="Skip the UI driver portion entirely (no SPA load "
        "check, no chat round). API-level checks still run. "
        "Useful for environments without a browser.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Per-chat timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--screenshot-dir",
        default=os.environ.get("RUNNER_TEMP", ""),
        help="Directory to save UI screenshots. Defaults to "
        "env RUNNER_TEMP (set by GitHub Actions). Empty = no "
        "screenshots.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run the browser in headed mode (visible window) "
        "instead of headless. Requires a display server.",
    )
    parser.add_argument(
        "--cdp-url",
        default="",
        help="CDP endpoint URL (e.g. http://127.0.0.1:9222). "
        "When set, connects to the existing WebView2 via CDP "
        "instead of launching a new Playwright browser.",
    )
    parser.add_argument(
        "--llm-retries",
        type=int,
        default=3,
        help="Retries for the LLM round on transient failures "
        "(DashScope 5xx / SSE jitter). Uses exponential backoff "
        "(5s, 10s, 20s, ...). Default: 3.",
    )
    parser.add_argument(
        "--allow-flaky-llm",
        action="store_true",
        help="If all LLM retries fail, emit a warning and exit 0 "
        "instead of failing. Use for fork CI where a flaky LLM "
        "should not block release. Release pipelines should NOT "
        "set this — they need the assertion.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    skip_chat = args.skip_chat or not args.api_key

    started = time.monotonic()
    driver: UIDriver | None = None
    try:
        # ---- API-level checks (always run, no key needed) ----
        health_check(base_url)
        verify_frontend(base_url)

        # ---- UI load (always run unless --skip-ui, no key needed) ----
        # This catches broken Vite bundles, missing assets, CSP issues,
        # and Tauri webview load failures even without LLM credentials.
        if args.skip_ui:
            print("SKIP  UI verification (--skip-ui)")
        else:
            try:
                ss_dir = (
                    os.path.join(
                        args.screenshot_dir,
                        "verify-screenshots",
                    )
                    if args.screenshot_dir
                    else None
                )
                driver = make_driver(
                    args.ui_mode,
                    ss_dir,
                    headless=not args.headed,
                    cdp_url=args.cdp_url,
                )
            except UIDriverInitError as exc:
                print(f"FAIL  UI driver init: {exc}", file=sys.stderr)
                return 3
            verify_ui_loaded(
                driver,
                base_url,
                skip_navigate=bool(args.cdp_url),
            )

        # ---- LLM chat round (only when key is available) ----
        if skip_chat:
            reason = (
                "explicit --skip-chat"
                if args.skip_chat
                else "no DashScope API key provided"
            )
            print(f"SKIP  LLM verification ({reason})")
        elif driver is None:
            # --skip-ui was set; nothing to drive.
            print("SKIP  LLM verification (--skip-ui)")
        else:
            configure_provider(base_url, args.provider, args.api_key)
            ensure_model(base_url, args.provider, args.model)
            set_active_model(base_url, args.provider, args.model)
            rc = _run_llm_with_retry(
                driver,
                args.timeout,
                args.llm_retries,
                args.allow_flaky_llm,
            )
            if rc != 0:
                return rc
    except RuntimeError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    finally:
        if driver is not None:
            driver.close()

    elapsed = time.monotonic() - started
    print(f"OK    desktop verification completed in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
