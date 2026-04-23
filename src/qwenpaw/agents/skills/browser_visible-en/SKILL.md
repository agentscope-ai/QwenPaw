---
name: browser_visible
description: "Use this skill when the user needs to control the browser launch mode for browser_use. By default, browser_use launches the local Chrome/Chromium using managed CDP; `headed` controls whether the window is visible, and `private_mode` controls whether CDP is disabled in favor of Playwright."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🖥️"
    requires: {}
---

# Browser Launch Modes

`browser_use.start` has only two launch modes:

- Default: managed CDP
- `private_mode=true`: Playwright-managed

Parameter meanings:

- `headed`: whether to display the browser window
- `private_mode`: whether to disable CDP and use Playwright instead

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

Without CDP:
```json
{"action": "start", "private_mode": true}
```

Visible window + without CDP:
```json
{"action": "start", "headed": true, "private_mode": true}
```

## When to Use `private_mode`

Only set `private_mode=true` when the user explicitly requests one of the following:

- Does not want the browser managed via CDP
- Wants to use Playwright instead
- Wants to reduce the possibility of other local tools connecting via CDP

Otherwise, just set `headed=true` as needed.

## Notes

- The default is managed CDP
- The launch mode is entirely determined by the call parameters
- Managed CDP requires Chrome / Chromium / Edge to be installed locally
- `private_mode=true` does not mean absolutely undetectable — it simply switches to Playwright management
- When the user manually operates the visible browser, the idle timer may not be refreshed
- `private_mode` is an explicit parameter for each `start` call and is not persisted
- If a browser is already running, you must `stop` it and then `start` again to switch launch modes or window visibility
- Visible mode occupies the desktop and requires a graphical environment; it may not work on servers or headless environments
