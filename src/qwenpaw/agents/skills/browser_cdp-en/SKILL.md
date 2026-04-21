---
name: browser_cdp
description: "Use this skill when the user explicitly wants to connect to a running Chrome browser, scan local CDP ports, specify a `cdp_port`, or share a single browser across multiple agents/tools. By default, browser_use already launches the browser using managed CDP; if the user does not want to expose browser history, cookies, or other sensitive data, recommend using `private_mode=true` instead."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🔌"
    requires: {}
---

# Browser CDP Reference

By default, **browser_use** launches and manages the local Chrome/Chromium via **managed CDP**, but this does not mean the CDP port should be exposed to the user or other tools every time.

This skill focuses on more "explicit" CDP usage:

1. **Scanning local CDP ports**
2. **Connecting to an existing Chrome (`connect_cdp`)**
3. **Explicitly specifying a `cdp_port` when launching the browser**
4. **Sharing a single browser instance across multiple agents/tools**

In other words:

- The default `start` uses managed CDP under the hood, but users typically do not need to understand or be aware of CDP details
- Only enter the scope of this skill when the user explicitly mentions "connect to an existing browser / scan ports / specify a port / share a browser"

> **Privacy Recommendation**
>
> If the user does not want to expose browser history, cookies, page content, or session data, recommend using `private_mode=true`, which switches to Playwright-managed mode.

> **Warning: One browser instance per workspace**
>
> Only one browser can be running or connected per workspace at a time. If a browser instance already exists, you must execute `stop` first before switching to a new browser or a new CDP connection.

---

## When to Use

Use this skill only when the user explicitly expresses one of the following intentions:

- "Connect to my already-open Chrome"
- "Scan for available CDP ports on this machine"
- "Launch the browser with a fixed debug port"
- "Let other agents/tools connect to this browser too"
- "Attach to the browser via the remote debugging port"

In the following cases, you should typically **not** use this skill:

- The user just says "open the browser"
- The user just says "open a visible window"
- The user does not mention sharing, ports, CDP, or remote debugging

In these cases, use the standard `start`, adding `headed=true` if needed — refer to **browser_visible**.

---

## Scenario 1: Scanning Local CDP Ports

Default scan range is **9000–10000**:

```json
{"action": "list_cdp_targets"}
```

Specify a single port:

```json
{"action": "list_cdp_targets", "port": 9222}
```

Custom scan range:

```json
{"action": "list_cdp_targets", "port_min": 8000, "port_max": 12000}
```

Use cases:

- The user has manually launched Chrome with a remote debugging port
- You do not know the exact port and need to scan first
- You need to verify available attach targets on the local machine before connecting

---

## Scenario 2: Connecting to an Existing Chrome

Connect to an existing CDP endpoint:

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

Characteristics:

- After a successful connection, you can continue using standard operations such as `open`, `snapshot`, `click`, `type`, etc.
- This **attaches to an external browser**, not a new process launched by QwenPaw
- `stop` only disconnects — it **will not close the external browser**
- External CDP connections are also subject to idle auto-stop management, but the auto-stop semantics for external CDP is "auto-disconnect, not close the external browser"

Use cases:

- The user has their own Chrome open and wants the agent to take over directly
- You need to attach to the user's existing login state or open tabs

---

## Scenario 3: Launching with an Explicit cdp_port

If the user explicitly requests a fixed port, or needs to provide the endpoint to other tools, specify `cdp_port` in `start`:

```json
{"action": "start", "cdp_port": 9222}
```

To also open a visible window:

```json
{"action": "start", "headed": true, "cdp_port": 9222}
```

Current behavior:

- If the explicitly specified `cdp_port` is already in use, an error is raised immediately — it will not forcefully reuse the port
- If `cdp_port` is not specified, an available port is automatically selected, which usually avoids multi-workspace conflicts
- Auto-selecting an available port still has a tiny race window: between "finding an available port" and "Chrome actually binding to the port", another process could theoretically claim it; on failure, cleanup occurs and an error is reported, but there is no automatic retry

Therefore:

- **Do not pass `cdp_port` proactively when the user has not explicitly requested a port**
- **Only pass `cdp_port` explicitly when the user requests a fixed port or external sharing**

---

## Multi-Workspace and Port Conflicts

The current port strategy for multiple workspaces:

- **Explicitly specified port**: checks whether `127.0.0.1:cdp_port` is already in use; if so, fails immediately and prompts the user to choose a different port or stop the old process
- **No explicit port**: reduces conflict probability by automatically selecting an available port

This means:

- Multiple workspaces using the default launch can usually coexist
- If multiple workspaces all request the same fixed `cdp_port`, the later one will fail because the port is already in use

---

## Stop Behavior

CDP-related stop behavior differs depending on the type:

### 1. Managed CDP launched by QwenPaw

For example:

```json
{"action": "start"}
```

Or:

```json
{"action": "start", "cdp_port": 9222}
```

These browsers are launched and owned by QwenPaw. `stop` will:

- Disconnect the Playwright / CDP connection
- Terminate the browser process

### 2. External CDP Browser

For example:

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

These browsers are not launched by QwenPaw. `stop` will only:

- Disconnect
- **Not close the external browser process**

---

## Division of Responsibility with browser_visible

- **browser_visible**: handles "whether to show a window" and "whether to use private_mode"
- **browser_cdp**: handles "whether to connect / expose / specify / scan CDP ports"

In short:

- User cares about "seeing the browser window" → think browser_visible first
- User cares about "connecting to an existing browser / specifying a debug port / sharing with others" → think browser_cdp first

---

## Notes

- Although the default `start` uses managed CDP internally, this is the tool's default implementation detail and does not mean CDP concepts should be exposed to the user every time
- Before using explicit CDP capabilities, warn the user about the risk of sensitive data exposure
- Auto-stop for external CDP means "auto-disconnect," not "auto-close the user's browser"
- Activity is currently refreshed primarily by tool operations; the user's manual interactions in the browser window typically do not reset the idle timer
- `private_mode` is an explicit parameter for each `start` call and is not persisted as workspace state
