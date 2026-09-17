# Browser

Browser is a built-in QwenPaw capability. Through the `browser` tool an Agent
writes async Python that drives a real browser to open pages, fill forms,
click, and read page content. It can either launch a standalone browser or work
inside the Chrome you already use and are already signed in to.

> **Beta feature:** the new unified browser is enabled by default. You can
> switch back to the legacy implementation from the Console at any time; the
> switch takes effect only after the service restarts.

---

## Two kinds of browser

| Which browser          | What it is                                                              | Requirement                              |
| ---------------------- | ----------------------------------------------------------------------- | ---------------------------------------- |
| **Standalone browser** | QwenPaw launches its own Chromium, isolated from your everyday browsing | None                                     |
| **Your own Chrome**    | Works in tabs of your signed-in Chrome, visible to you the whole time   | Install the [Chrome extension](./chrome) |

Both use the same `browser` tool and the same SDK, so the Agent writes exactly
the same code. The only difference is whose browser and whose signed-in session
is used.

---

## How it works

The Agent uses QwenPaw's own Browser SDK (not Playwright), and the API surface
is closed: only the methods the SDK exposes exist. The complete API reference
is delivered to the Agent together with the built-in **browser** skill, so
there is nothing for you to configure.

Every round follows a fixed discipline:

1. **Perceive** — read the current page state first and confirm what is there.
2. **Act** — then navigate, click, or fill.
3. **Verify** — perceive again afterwards, and only claim success once the
   result matches.

That is why you see the Agent look at the page again before each move: it is
deliberate. The Agent only states what it actually observed this round, and
when it gets stuck it says where it got stuck instead of guessing a complete
answer.

### When you need to step in

For sign-in, CAPTCHA, two-factor authentication, or any step that must be done
by a person, the Agent stops and hands that step back to you with an
explanation instead of trying to automate it. Complete it in the browser and
then let the Agent continue.

> A headless run (no visible window) cannot hand a step back to a person. For
> tasks that need human input, make sure the browser is headed — see the
> `headless` setting below.

---

## Browser identity

**Identity** decides who the Agent browses as, and which signed-in session it
carries.

| Identity         | Meaning                                                          | Which browser      |
| ---------------- | ---------------------------------------------------------------- | ------------------ |
| `auto` (default) | `user` when the Chrome extension is connected, otherwise `guest` | Depends            |
| `user`           | Your real Chrome, with your signed-in sessions                   | Your own Chrome    |
| `avatar`         | A persistent alternate identity that keeps its sign-ins          | Standalone browser |
| `guest`          | An incognito visitor, discarded on close                         | Standalone browser |

Identity precedence is: what the Agent requests in code > the
`browser.identity` setting > the `auto` rule.

- If `user` is requested explicitly while the Chrome extension is not
  connected, the Agent gets an explicit message: connect the Chrome extension,
  or choose `avatar` / `guest` instead.
- Under `auto`, the same situation falls back to `guest` and the task
  continues.

> The `user` identity uses your real browser and your real signed-in sessions,
> so what the Agent does there is equivalent to your own clicks. Use it only
> for sites where you are willing to let it act for you.

---

## Where the standalone browser comes from

`browser.backend` only affects the standalone browser used by `avatar` and
`guest`. The `user` identity always goes through the Chrome extension and is
unaffected by this setting.

| Value            | Behaviour                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| `auto` (default) | QwenPaw launches and manages a Chromium                                                           |
| `launch`         | Same as `auto`, stated explicitly                                                                 |
| `managed_cdp`    | Launch a Chromium with a debugging port and control it over CDP; see `cdp_port`, `0` auto-assigns |
| `connect_cdp`    | Connect to an already running CDP endpoint; `cdp_url` must also be set                            |

By default QwenPaw prefers the Chromium-based executable of your system default
browser and falls back to the Chromium bundled with QwenPaw. Use
`use_system_default` and `executable_path` to override this.

---

## Switching between the new and legacy implementation

In the Console open **Agent → Tools**, find the **browser** tool card, and use
the button on the card:

| Button              | Meaning                                                             |
| ------------------- | ------------------------------------------------------------------- |
| **New (Beta)**      | Use the new unified browser capability (default)                    |
| **Legacy (compat)** | Use the original browser implementation when you need old behaviour |

The call style differs: the new track is `browser(code)`, where the Agent
writes async Python, while the legacy track is invoked one action at a time
through an `action` parameter. This switch is written to the global
configuration and applies to every Agent.

> After switching, the card shows a pending notice about the mode that will
> apply next. **You must restart the QwenPaw service** for it to take effect;
> this setting is not hot-reloaded.

---

## Settings

Browser settings live in the `browser` block of the global
`~/.qwenpaw/config.json` and apply to every Agent:

```json
{
  "browser": {
    "experimental": true,
    "backend": "auto",
    "identity": "auto",
    "headless": "auto"
  }
}
```

| Field                      | Type               | Default  | Description                                                                                  |
| -------------------------- | ------------------ | -------- | -------------------------------------------------------------------------------------------- |
| `experimental`             | bool               | `true`   | Use the new unified browser; `false` returns to the legacy one. **Requires a restart**       |
| `backend`                  | string             | `"auto"` | How the standalone browser is obtained: `auto` / `launch` / `managed_cdp` / `connect_cdp`    |
| `identity`                 | string             | `"auto"` | Browser identity: `auto` / `user` / `avatar` / `guest`                                       |
| `cdp_url`                  | string \| null     | `null`   | Required with `connect_cdp`; points at an existing CDP endpoint                              |
| `cdp_port`                 | int                | `0`      | Debugging port for `managed_cdp`; `0` auto-assigns (valid range 0-65535)                     |
| `engine`                   | string             | `"auto"` | Browser engine, only `auto` / `chromium`; legacy `webkit` and `firefox` fall back to `auto`  |
| `channel`                  | string \| null     | `null`   | Chromium release channel (for example `chrome`, `msedge`)                                    |
| `executable_path`          | string \| null     | `null`   | Explicit browser executable path                                                             |
| `headless`                 | string             | `"auto"` | `auto` runs headless in containers or without a display; `"true"` / `"false"` force the mode |
| `user_data_dir`            | string \| null     | `null`   | Custom data directory for the standalone browser; assigned per workspace when unset          |
| `args`                     | string[]           | `[]`     | Extra browser launch arguments                                                               |
| `viewport`                 | [int, int] \| null | `null`   | Viewport size; both dimensions must be positive integers                                     |
| `proxy`                    | string \| null     | `null`   | Proxy address                                                                                |
| `use_system_default`       | bool               | `true`   | Prefer the Chromium executable of the system default browser                                 |
| `idle_ttl_seconds`         | float              | `600`    | Idle seconds before the whole browser is shut down                                           |
| `session_idle_ttl_seconds` | float              | `900`    | Idle seconds before a single session is reclaimed                                            |
| `exec_timeout_seconds`     | float              | `120`    | Execution timeout for one `browser` call, in seconds                                         |

> **Deprecated fields:** use `identity: "user"` instead of
> `backend: "extension"`, and `identity` instead of `context` (`profile` →
> `avatar`, `incognito` → `guest`). Old configurations still load but emit a
> warning in the log.

---

## Where the data lives

Standalone browser data is isolated per Agent workspace and never mixes with
your everyday browsing:

| Directory                                 | Contents                                                              |
| ----------------------------------------- | --------------------------------------------------------------------- |
| `workspaces/{agent_id}/.browser-profile/` | Persistent profile of the standalone browser (`avatar` sign-ins here) |
| `workspaces/{agent_id}/.browser-cdp/`     | Browser data directory used by `managed_cdp`                          |
| `workspaces/{agent_id}/browser/`          | Browser data of the legacy implementation                             |

The `user` identity writes to none of these — it uses your own Chrome profile.
Browser processes are reclaimed according to `idle_ttl_seconds` /
`session_idle_ttl_seconds`, and are closed when the service exits.

---

## Troubleshooting

### I switched the implementation but nothing changed

This setting is not hot-reloaded. Restart the QwenPaw service and try again;
the pending notice on the tool card means the change is saved and waiting for
the restart.

### The Agent says the Chrome extension must be connected

Identity was explicitly set to `user` while the Chrome extension is not
connected. Install and connect the [Chrome extension](./chrome), or change
`browser.identity` to `avatar` / `guest`.

### Can I use it on a server without a display?

Yes. With `headless` set to `auto`, QwenPaw runs headless inside containers and
in environments without a display. Tasks that need you to sign in or solve a
CAPTCHA cannot be handed back in headless mode, so run those where a window is
available.

### `connect_cdp` fails to start

`connect_cdp` requires `browser.cdp_url`; without it configuration validation
fails outright. Confirm that the target browser exposes a debugging port and
that the address is reachable.

### Why do I have to sign in again every task?

The `guest` identity is an incognito visitor and is discarded on close. To keep
sign-ins use `avatar` (the persistent identity of the standalone browser), or
use `user` to reuse the sessions in your own Chrome.

---

## Related pages

- [Chrome extension](./chrome) — connect QwenPaw to your own Chrome
- [MCP & built-in tools](./mcp) — review and manage the tools available to an Agent
- [Skills](./skills) — how the built-in **browser** skill and SDK reference are delivered
- [Configuration & working directory](./config) — global config file and directory layout
