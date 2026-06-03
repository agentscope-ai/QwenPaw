# qwenpaw-extension-demo

Smoke-test plugin for the new QwenPaw frontend extension APIs landed in
`feat/plugin-extensions-all`. Exercises 9 API surfaces in a single bundle so
you can verify the host → loader → registry → renderer chain end-to-end with
one plugin install.

## What it registers

| # | API | Visible at |
|---|---|---|
| 1 | `QwenPaw.menu.add` | Sidebar → Agent group → "Demo" entry |
| 2 | `QwenPaw.route.add` | `/demo` page |
| 3 | `QwenPaw.route.wrap` | Yellow banner above `/chat` |
| 4 | `QwenPaw.slot.fill` | Small "🧪 demo plugin active" footer at sider bottom |
| 5 | `QwenPaw.chat.welcome.set` | Custom greeting on empty chat |
| 6 | `QwenPaw.chat.rightHeader.add` | "🧪 Demo" button in chat header |
| 7 | `QwenPaw.chat.actions.add` | ⭐ star button under every AI message |
| 8 | `QwenPaw.chat.response.append` | Info banner below the **last** AI bubble |
| 9 | `QwenPaw.chat.request.render` | Dashed-border wrap around user bubbles (with fallback) |

Plus a button on the `/demo` page that calls `QwenPaw.audit.overrides()` and
shows the count.

## Build

```bash
cd frontend
npm install
npm run build
# → frontend/dist/index.js (consumed via plugin.json "entry.frontend")
```

For iterating during testing:

```bash
npm run build:watch
```

## Install / link

Put this directory where QwenPaw backend's plugin loader scans, typically via
symlink so source edits → `build:watch` → console reload picks them up
without a copy step.

The plugin is frontend-only (`plugin.py` is a stub). After install, refresh
the console once so `loadAllPlugins()` re-fetches and executes the bundle.

## Removing / iterating

The frontend bundle's registrations are all keyed by `pluginId =
"qwenpaw-extension-demo"`. Calling
`QwenPaw.chat.disposeAll("qwenpaw-extension-demo")` in the browser console
tears down every chat-namespace registration this plugin made; the
console-wide ones (menu / route / slot) don't have a `disposeAll` yet —
those clear naturally on uninstall + page reload.
