---
name: browser_visible
description: "Use this skill when the user needs to control the browser launch mode for browser. By default browser is managed by Playwright and opens no debugging port (pass an explicit `cdp_port` to let another local tool attach); `headed` controls whether the window is visible, and `private_mode` is kept for backward compatibility and no longer changes the default."
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🖥️"
    requires: {}
---

> **Deprecated:** This reference supports the stable `browser` implementation.
> hatch. Prefer the unified `browser` tool when experimental mode is enabled.

# Browser Launch Modes

`browser.start` launch modes:

- Default: Playwright-managed, no debugging port
- `cdp_port=N`: managed CDP, opens a local debugging port so other local tools can attach (see the browser_cdp skill)
- `private_mode=true`: same as the default, kept for backward compatibility

Parameter meanings:

- `headed`: whether to display the browser window
- `private_mode`: kept for backward compatibility; it no longer changes the launch mode

The two parameters are independent and can be freely combined.

## Common Usage

Default launch:
```json
{"action": "start"}
```

Open a visible window:
```json
{"action": "start", "headed": true}
```

## `private_mode`

Already the default behavior — do not set it. The parameter is kept only so that older calls keep working, and passing it together with `cdp_port` is rejected.

## Notes

- The default is Playwright-managed with no debugging port
- The launch mode is entirely determined by the call parameters
- Managed CDP requires Chrome / Chromium / Edge to be installed locally
- When the user manually operates the visible browser, the idle timer may not be refreshed
- `private_mode` is an explicit parameter for each `start` call and is not persisted
- If a browser is already running, you must `stop` it and then `start` again to switch launch modes or window visibility
- Visible mode occupies the desktop and requires a graphical environment; it may not work on servers or headless environments
