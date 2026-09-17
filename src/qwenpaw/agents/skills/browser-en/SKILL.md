---
name: browser
description: "Drive a live browser with async Python against QwenPaw's builtin Browser SDK. The full reference is below; re-load this browser skill after context compaction."
metadata:
  builtin_skill_version: "0.3"
  qwenpaw:
    emoji: "🌐"
    requires: {}
---

# Browser

Work with discipline: perceive the current page, act through the documented
surface, then re-perceive before claiming success. State only facts observed
in this turn. When stuck, a complete delivery is the step you are stuck on
plus the partial results you have verified — never fill in content you did not
observe just to produce a full answer.

Respect the human boundary: for login, captcha, 2FA, or any human-only step,
call `await browser.handoff(...)` and stop. Never automate those flows.
When the browser cannot finish, do not substitute data from another channel
(such as web_search) and still call it a browser result — state each fact's
real source.

This is QwenPaw's builtin Browser SDK, not Playwright. Its surface is closed:
anything not listed does not exist. The complete reference is below; re-load
this browser skill with the Skill tool if it is no longer in context.

<!-- BEGIN GENERATED: browser-manual -->
QwenPaw Browser SDK — complete reference. This is QwenPaw's OWN internal
SDK and this is the ENTIRE API; these are all the entrypoints. The SDK
is already in scope as Browser — call the methods below directly. Write
async Python. Work in a loop: perceive → act → verify.

# Copy this shape:
browser = await Browser.connect()                  # connect once; reused all session
page = await browser.open("https://example.com")   # open a page
obs = await page.snapshot()                         # PERCEIVE — page text is obs.text
if len(obs.text) < 6000:
    print(obs.text)
else:
    # Large page: read selectively instead of dumping everything.
    lines = [line for line in obs.text.splitlines()
             if "keyword" in line]
    print(f"{len(obs.text)} chars total; {len(lines)} matching lines:")
    print("\n".join(lines[:80]))
# For a focused count, use: await page.snapshot(query="keyword")
await page.get_by_role("textbox", name="Search").fill("laptop")   # ACT
await page.get_by_role("button", name="Search").click()            # ACT
obs = await page.snapshot()                         # VERIFY — re-perceive to confirm
print("Verified; inspect obs.text with the selective pattern above.")

Session state: this is a stateful session — variables you assign (browser,
page) persist across calls, so connect once and reuse them. If a call
reports the session was reset, re-run await Browser.connect().

Chrome backend caveat: with backend=chrome you operate inside the user's
real browser. A session is a tab-ownership group — tabs are isolated per
session, but identity (cookies, logins, storage) is shared with the user's
profile and with every other session. Do not rely on session-level identity
isolation on this backend.

browser (orchestration):
await Browser.connect(*, identity: "auto"|"user"|"avatar"|"guest" = "auto") -> browser
    Connect as an identity: user, avatar, guest, or auto.

    ``auto`` picks ``user`` when Chrome is connected, otherwise ``guest``.
    An unavailable explicit identity raises instead of substituting.
await browser.open(url: str | None = None) -> page
    Open a page at ``url`` and return it.

    Reuses this session's active page when one exists; otherwise a
    new page is created. Pages are released when the response cycle ends;
    start each cycle by calling ``open(url)`` again.
await browser.pages() -> list of page ref (.id, .url, .title, .active)
    List open pages with URL, title, and active-state details.
await browser.switch_page(page: page ref (.id, .url, .title, .active)) -> none
    Make the given page ref active for later operations.
await browser.close_page(page: page ref (.id, .url, .title, .active)) -> none
    Close the given page ref in this session.
await browser.session_status() -> session status (.owner, .variant, .context, .connected)
    Report the owner, variant, context, and connected state.
await browser.handoff(reason: str, instructions: str = "") -> a result dict
    Hand a step back to a human (captcha, login, 2FA).

    Pass a short reason and instructions; the run stops on this signal —
    never automate these flows. The active cycle-scoped page is retained
    for one extra response cycle after the handoff.
await browser.present(url: str | None = None) -> page
    Open a page retained for the chat lifetime.
await browser.close() -> none
    Close this session's browser and release its context.

page (operation):
await page.goto(url: str) -> a result dict
    Navigate this page to ``url`` and return raw navigation facts.
await page.go_back() -> a result dict
    Navigate back to the previous page in history.
await page.go_forward() -> a result dict
    Navigate forward to the next page in history.
await page.reload() -> a result dict
    Reload the current page.
await page.keep() -> none
    Retain this page across response cycles for the current chat.
await page.wait_for_load_state(state: str = "load", *, timeout: float | None = None) -> none
    Wait until the page reaches the requested load state.

    ``networkidle`` semantics depend on the backend: the Playwright
    backend waits for true network quiescence, while CDP-based
    backends (cdp, chrome) degrade to ``document.readyState ==
    "complete"`` plus a fixed 500 ms quiet delay and do NOT track
    in-flight requests — content loaded by late XHR may still be
    missing when this returns.
await page.wait_for_timeout(timeout: float) -> none
    Sleep unconditionally for *timeout* milliseconds (capped at 30 000).

    Prefer :py:meth:`locator.wait_for(state, timeout)
    <LocatorView.wait_for>` when waiting for a specific DOM condition
    — it returns as soon as the condition is met and is both faster
    and more reliable than an unconditional sleep.
await page.screenshot() -> a result dict
    Capture this page to a PNG file in the active workspace.
page.get_by_role(role: str, *, name: str | None = None) -> locator
    Locate elements by accessible role and optional name.
page.get_by_text(text: str) -> locator
    Locate elements by their visible text.
page.get_by_label(text: str) -> locator
    Locate a form control by its associated label text.
page.get_by_placeholder(text: str) -> locator
    Locate an input by its placeholder text.
page.locator(selector: str) -> locator
    Locate elements by a CSS selector when no semantic locator fits.
page.frame_locator(selector: str) -> locator
    Scope subsequent locators to the iframe matching ``selector``.
await page.snapshot(query: str | None = None) -> observation (read .text; .match_count when you pass a query)
    Perceive the page and return readable content in ``.text``.

    Pass ``query`` to also report ``.match_count``.
await page.current_surface() -> surface facts (.url, .title, .load_state)
    Return this page's current URL, title, and load facts.
page.mouse -> coordinate/keyboard input surface (see methods below)
    Viewport-coordinate input surface.

    click(x, y) -> a result dict; verify the effect with snapshot().
page.keyboard -> coordinate/keyboard input surface (see methods below)
    Keyboard input surface.

    press(key) -> a result dict; verify the effect with snapshot().

page.get_by_* / page.locator(...) return a locator that mirrors a SUBSET
of Playwright's Python locator API — the Playwright-shaped part of this
SDK:
  compose/scope (chainable): get_by_role/get_by_text/get_by_label/
      get_by_placeholder, locator(sel), filter(...), nth(i), first, last (properties)
  iframe scope: page.frame_locator(sel).locator(...) (one frame; no nested frames)
  read (await): count()->int, inner_text()->str, text_content()->str|None,
      all_text_contents()->list, get_attribute(name)->str|None,
      input_value()->str, is_visible()->bool, is_enabled()->bool
  act (await; returns a short evidence line — read .evidence): click(), fill(v),
      type(t), press(key), check(), uncheck(), set_checked(b),
      select_option(*v), hover(), dblclick(), scroll(),
      focus(), blur(), clear(), wait_for(state), screenshot(),
      bounding_box()->dict|None (viewport ["x"] ["y"] ["width"] ["height"]; None when the element is not visible)
  strict-mode
      uniqueness is enforced — act only when the locator resolves to exactly
      one element (use count() to check). element_handle / raw CDP unavailable.

Backend differences (chrome/cdp vs playwright): on chrome/cdp the
accessible name is a heuristic (aria-labelledby > aria-label > alt >
title > text content) - container elements may match
get_by_role(name=) more broadly than under playwright, so
strict-mode errors are more likely there; narrow with
filter(has_text=) or a more specific role. is_enabled() reflects
only the disabled property, not aria-disabled. press() supports a
fixed key set: printable characters, Enter, Tab, Escape, Backspace,
Delete, Arrow keys, Home/End/PageUp/PageDown, and
Control/Shift/Alt/Meta combos - anything else fails with guidance.
type() sets the value directly and fires an input event; editors that
need real per-key events may not react - prefer fill() where possible.

Reading results (read these fields; the type names don't matter):
  snapshot()        -> .text (page text), .match_count (when you pass query)
  current_surface() -> .url, .title, .load_state
  page refs         -> .id, .url, .title, .active
  screenshot()      -> result dict; read ["path"]
  bounding_box()    -> viewport ["x"] ["y"] ["width"] ["height"]; None when the element is not visible
  mouse.click()/keyboard.press() -> result dict; fields depend on the backend, so verify with snapshot()
  actions           -> .evidence (a short line saying what happened)
  locator reads return plain str/int/bool/list directly.

If a locator fails, step DOWN one rung (don't jump):
  1. semantic  page.get_by_role/label/text            first choice
  2. css       page.locator(css)                       role missing/unstable
  3. coordinates use locator.bounding_box() first for an exact, low-cost viewport rectangle; use a screenshot to explore only when the element is absent from snapshot()
For captcha/login/2FA or any human-only step: await browser.handoff(reason,
instructions) and stop — never automate them.
<!-- END GENERATED: browser-manual -->
