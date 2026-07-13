# Plugin System

QwenPaw provides a plugin system that allows users to extend QwenPaw's functionality.

## Overview

The plugin system supports the following extension capabilities:

- **Provider Plugins**: Add new LLM providers and models
- **Middleware Plugins**: Register AgentScope `MiddlewareBase` factories to wrap `on_acting` / `on_reasoning` hooks in the agent reasoning loop
- **Hook Plugins**: Execute custom code during application startup/shutdown (app lifespan level, runs once)
- **Command Plugins**: Register custom `/command` magic commands
- **HTTP API Plugins**: Expose custom REST endpoints under `/api` via a FastAPI `APIRouter`
- **Frontend Extension Plugins**: Browser-side JS plugins that share the host's React / Ant Design runtime and declaratively extend the UI via `window.QwenPaw.*` API — register sidebar menus, page routes, UI slots, chat customizations, and more without modifying host code
- **Channel Plugins**: Register custom messaging channels (e.g. Slack, LINE)

## Plugin Management

### Install Plugin

Install from local directory:

```bash
qwenpaw plugin install /path/to/plugin
```

Install from URL (supports ZIP files):

```bash
qwenpaw plugin install https://example.com/plugin.zip
```

Force reinstall:

```bash
qwenpaw plugin install /path/to/plugin --force
```

**Note**: Plugin operations can only be performed when QwenPaw is offline.

### List Installed Plugins

```bash
qwenpaw plugin list
```

Example output:

```
Installed Plugins:
==================

my-provider (v1.0.0)
  Custom LLM provider integration
  Author: Developer Name
  Path: /Users/user/.qwenpaw/plugins/my-provider
```

### View Plugin Details

```bash
qwenpaw plugin info <plugin-id>
```

### Uninstall Plugin

```bash
qwenpaw plugin uninstall <plugin-id>
```

## Plugin Development

### Backend Plugins

#### Basic Structure

Each plugin requires at least two files:

```
my-plugin/
├── plugin.json      # Plugin manifest (required)
├── plugin.py        # Entry point (required)
└── README.md        # Documentation (recommended)
```

#### plugin.json

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "general",
  "description": "Plugin description",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "qwenpaw_version": {
    "min": "1.0.0",
    "max": "2.1.0"
  },
  "meta": {}
}
```

#### Manifest Field Reference

| Field             | Type               | Required | Description                                                                                                                                                                                          |
| ----------------- | ------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`              | `string`           | yes      | Unique plugin identifier. Used as the install directory name; must not contain path separators.                                                                                                      |
| `version`         | `string`           | yes      | Semantic version of the plugin (e.g. `1.0.0`).                                                                                                                                                       |
| `name`            | `string` \| object | no       | Display name. Defaults to `id`. May also be `{"zh-CN": "...", "en-US": "..."}`; the first non-empty localised value is used (English preferred).                                                     |
| `type`            | `string`           | no       | One of `tool`, `provider`, `hook`, `command`, `frontend`, `general`. When omitted, the type is inferred from `meta` / `entry` (legacy plugins). Prefer setting explicitly.                           |
| `description`     | `string` \| object | no       | Short description shown in the plugin list. Localised form is accepted (see `name`).                                                                                                                 |
| `author`          | `string`           | no       | Author or organisation name.                                                                                                                                                                         |
| `entry.backend`   | `string`           | no\*     | Path (relative to plugin dir) of the Python entry file that exports `plugin`.                                                                                                                        |
| `entry.frontend`  | `string`           | no\*     | Path of the built frontend bundle (e.g. `dist/index.js`).                                                                                                                                            |
| `dependencies`    | `string[]`         | no       | Python package requirements installed via pip/uv at install time.                                                                                                                                    |
| `qwenpaw_version` | `object`           | no       | QwenPaw version constraint (recommended). Contains `min` (inclusive) and `max` (exclusive, optional) sub-fields. Semantics: `>=min, <max`. When `max` is omitted, defaults to `{major}.{minor+1}.0`. |
| `min_version`     | `string`           | no       | **Legacy.** Minimum QwenPaw version required. Ignored when `qwenpaw_version` is present. Retained only for backward compatibility with third-party plugins.                                          |
| `max_version`     | `string`           | no       | **Legacy.** First incompatible QwenPaw version (exclusive). Used with `min_version`; when omitted, derived from `min_version`.                                                                       |
| `meta`            | `object`           | no       | Free-form plugin metadata. Used by the UI and by `type` inference (e.g. `meta.tools[]`, `meta.hook_type`, `meta.provider_id`).                                                                       |
| `entry_point`     | `string`           | no       | **Legacy.** Equivalent to `entry.backend`. Still accepted for backwards compatibility with older plugins; new plugins should use `entry.backend`.                                                    |

\* At least one of `entry.backend` / `entry.frontend` (or legacy `entry_point`) must be provided.

#### `type` values

| Value      | When to use                                                            |
| ---------- | ---------------------------------------------------------------------- |
| `tool`     | Registers one or more agent tools (functions the LLM can call).        |
| `provider` | Registers a custom LLM provider / model endpoint.                      |
| `hook`     | Runs code during application startup or shutdown (app lifespan level). |
| `command`  | Registers one or more `/slash` control commands.                       |
| `channel`  | Registers a custom messaging channel.                                  |
| `frontend` | Ships a frontend JS bundle loaded dynamically by the UI.               |
| `general`  | Fallback for plugins that combine multiple capabilities or don't fit.  |

#### plugin.py

```python
# -*- coding: utf-8 -*-
"""My Plugin Entry Point."""

from qwenpaw.plugins.api import PluginApi
import logging

logger = logging.getLogger(__name__)


class MyPlugin:
    """My Plugin."""

    def register(self, api: PluginApi):
        """Register plugin capabilities.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering my plugin...")

        # Register your capabilities
        # api.register_provider(...)
        # api.register_startup_hook(...)
        # api.register_shutdown_hook(...)

        logger.info("✓ My plugin registered")


# Export plugin instance
plugin = MyPlugin()
```

### Frontend Plugins

Frontend plugins are JavaScript extensions that run in the browser. Unlike backend plugins that register capabilities via the Python `PluginApi`, frontend plugins declaratively extend the Console UI through the global `window.QwenPaw.*` API.

**Loading lifecycle:**

1. Console starts up and mounts the Host SDK (React, antd, and other shared dependencies) and registration APIs (menu, route, slot, chat, and other namespaces) on `window.QwenPaw`
2. Console fetches the enabled frontend plugin list from `/frontend_plugin`
3. Downloads each plugin's JS bundle and executes it via Blob URL dynamic import
4. Plugin code runs and calls `window.QwenPaw.*` to register menus, routes, chat customizations, and other UI extensions
5. Registrations take effect immediately — menus appear in the sidebar, routes become navigable, chat areas show customized content

Plugins don't need to declare which extension points they use; the system automatically tracks all registrations via `pluginId`. When a plugin is uninstalled or disabled, all registrations are cleaned up via `dispose()` or `chat.disposeAll(pluginId)`.

**Design characteristics:**

| Feature                      | Description                                                                                                                                              |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Shared runtime**           | React, ReactDOM, and Ant Design are provided by the host — plugins don't bundle them, avoiding version conflicts and bloat                               |
| **Declarative registration** | Three core verbs: `set` (set / merge properties), `render` (replace rendering), `add` (append items)                                                     |
| **pluginId isolation**       | Every registration method takes `pluginId` as the first argument — the system uses it to track origins, detect conflicts, and support per-plugin cleanup |
| **Revocable**                | Every registration returns a `{ dispose() }` object — call it to undo the registration, enabling hot-reload and clean uninstall                          |
| **Internationalization**     | Text fields support the `Localized<T>` type — pass a `(locale) => string` function to return different values per language                               |

**Extension points at a glance:**

| Namespace                         | Capability                                            | Typical use                                                     |
| --------------------------------- | ----------------------------------------------------- | --------------------------------------------------------------- |
| `host`                            | Shared dependencies, React Hooks, authenticated fetch | Access React / antd, read theme and locale, call backend APIs   |
| `menu`                            | Sidebar menu items                                    | Add navigation entries                                          |
| `route`                           | Page routes                                           | Register new pages, wrap existing pages                         |
| `slot`                            | General UI slots                                      | Inject content into Header / Sidebar and other preset positions |
| `chat.welcome`                    | Welcome screen                                        | Customize greeting, suggested prompts                           |
| `chat.theme`                      | Chat theme color                                      | Change the primary color                                        |
| `chat.leftHeader` / `rightHeader` | Chat header                                           | Set brand logo, add action buttons                              |
| `chat.sender`                     | Input box                                             | Custom placeholder, input suggestions                           |
| `chat.actions` / `requestActions` | Message action buttons                                | Add custom actions below messages                               |
| `chat.requestPayload`             | Outgoing chat request payload                         | Add custom fields before the request is sent to the backend     |
| `chat.request` / `response`       | Message bubbles                                       | Prepend/append content or fully replace rendering               |
| `chat.toolRender`                 | Tool-call rendering                                   | Custom tool result display (e.g. weather card)                  |
| `chat.card`                       | Custom cards                                          | Register new card types                                         |
| `audit`                           | Audit & debugging                                     | View all extension registration records                         |

#### Basic Structure

```
my-plugin/
├── plugin.json      # Plugin manifest (required)
├── src/
│   └── index.tsx    # Entry point, calls window.QwenPaw.* APIs
├── package.json     # Dependencies
├── tsconfig.json    # TypeScript config
└── vite.config.ts   # Build config
```

#### plugin.json

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "frontend",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

#### src/index.tsx

The plugin entry file executes on load and registers extensions via `window.QwenPaw.*` API:

```tsx
const { React, antd } = window.QwenPaw.host;
const pluginId = "my-plugin";

// Call window.QwenPaw.* APIs to register menus, routes, chat customizations, etc.
// See "Frontend Extension API" below for details
```

#### Build Toolchain

**package.json**:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "scripts": { "build": "vite build" },
  "devDependencies": {
    "vite": "^5.0.0",
    "typescript": "^5.0.0",
    "@vitejs/plugin-react": "^4.0.0"
  }
}
```

**tsconfig.json**:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react",
    "strict": false,
    "skipLibCheck": true
  }
}
```

**vite.config.ts**:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react({ jsxRuntime: "classic" })],
  build: {
    lib: {
      entry: "src/index.tsx",
      formats: ["es"],
      fileName: () => "index.js",
    },
    rollupOptions: { external: ["react", "react-dom"] },
  },
});
```

`jsxRuntime: "classic"` compiles JSX to `React.createElement`, using the host-provided `React`; `external` avoids bundling React, using the version already loaded by the application.

#### Build and Install

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/my-plugin/
qwenpaw app
```

You can copy `console/src/plugins/types/qwenpaw.d.ts` into your plugin project as `qwenpaw-host.d.ts` for full type hints.

## Frontend Extension API

Frontend plugins extend the Console UI through the `window.QwenPaw.*` API without modifying host code. All registration methods take `pluginId` as the first argument, and every registration returns a `{ dispose() }` object for revocation.

### Host SDK — `window.QwenPaw.host`

Shared dependencies — plugins do not need to bundle these libraries:

```ts
host.React                        // React library
host.ReactDOM                     // ReactDOM library
host.antd                         // Ant Design component library
host.antdIcons                    // Ant Design icons library
host.apiBaseUrl                   // API base URL
host.getApiUrl(path: string)      // Build full API URL
host.getApiToken(): string | null // Get current auth token
```

**React Hooks (use inside React components):**

```ts
const theme = window.QwenPaw.host.useTheme(); // "light" | "dark"
const locale = window.QwenPaw.host.useLocale(); // "zh" | "en"
const agent = window.QwenPaw.host.useSelectedAgent(); // { id: string }
const session = window.QwenPaw.host.useCurrentSession(); // { id: string } | null
```

**Imperative getters (can be called anywhere):**

```ts
const agentId = window.QwenPaw.host.getSelectedAgentId();
const sessionId = window.QwenPaw.host.getCurrentSessionId();
```

**Authenticated fetch (automatically injects Authorization and X-Agent-Id headers):**

```ts
const resp = await window.QwenPaw.host.fetch("/api/v1/my-endpoint", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "test" }),
});
const data = await resp.json();
```

### Sidebar Menu — `window.QwenPaw.menu`

| Method     | Signature                                | Description                          |
| ---------- | ---------------------------------------- | ------------------------------------ |
| `add`      | `(pluginId, item \| item[]): Disposable` | Add menu items                       |
| `replace`  | `(pluginId, targetId, item): Disposable` | Replace an existing menu item        |
| `remove`   | `(targetId): void`                       | Remove a menu item                   |
| `snapshot` | `(location?): MenuItem[]`                | Get a snapshot of current menu items |

**MenuItem Parameters:**

```ts
{
  id: string;                    // Globally unique, e.g. "my-plugin.foo"
  label: string | (() => ReactNode);
  icon?: ReactComponent | ReactNode;
  route?: string;                // Route id to navigate to on click
  parentId?: string;             // Parent group to attach to
  location?: "primary.agentScoped" | "primary.settings" | "userMenu";
  before?: string;               // Position before a specific id
  after?: string;                // Position after a specific id
  order?: number;                // Lower values appear first
  visible?: () => boolean;       // Dynamic visibility control
  isGroup?: boolean;             // Render as group header
  divider?: boolean;             // Render as horizontal divider
}
```

### Page Routes — `window.QwenPaw.route`

| Method    | Signature                                     | Description                            |
| --------- | --------------------------------------------- | -------------------------------------- |
| `add`     | `(pluginId, route \| route[]): Disposable`    | Register new routes                    |
| `replace` | `(pluginId, targetId, component): Disposable` | Replace an existing route's component  |
| `wrap`    | `(pluginId, targetId, wrapper): Disposable`   | Wrap an existing route (onion pattern) |
| `remove`  | `(targetId): void`                            | Remove a route                         |

**Route parameters:**

```ts
{
  id: string; // Globally unique, e.g. "my-plugin.home"
  path: string; // URL path, supports react-router patterns
  component: React.ComponentType; // Page component
}
```

**Wrap example (add a top banner to an existing page):**

```tsx
window.QwenPaw.route.wrap("my-plugin", "core.chat", (Inner) => {
  return () => (
    <div>
      <div style={{ background: "#fff3cd", padding: 8, textAlign: "center" }}>
        Beta Feature
      </div>
      <Inner />
    </div>
  );
});
```

### General UI Slots — `window.QwenPaw.slot`

| Method     | Signature                                     | Description                                             |
| ---------- | --------------------------------------------- | ------------------------------------------------------- |
| `fill`     | `(pluginId, name, render, opts?): Disposable` | Append content to a slot (multiple can coexist)         |
| `replace`  | `(pluginId, name, render, opts?): Disposable` | Replace slot content (latest wins, overrides all fills) |
| `snapshot` | `(): SlotInfo[]`                              | Get all registered slot information                     |

**Built-in Slots:**

| Slot Name           | Type    | UI Location                               |
| ------------------- | ------- | ----------------------------------------- |
| `header.logo`       | replace | Top navbar, leftmost                      |
| `header.left`       | fill    | Top navbar, left area (right of logo)     |
| `header.right`      | fill    | Top navbar, right area (left of settings) |
| `sider.top`         | fill    | Sidebar top (below agent selector)        |
| `sider.bottom`      | fill    | Sidebar bottom (below menu)               |
| `content.statusBar` | fill    | Main content area top                     |
| `overlay.global`    | fill    | Global overlay                            |

**Example:**

```tsx
// Replace Header Logo
window.QwenPaw.slot.replace("my-plugin", "header.logo", (defaultLogo) => {
  return <img src="https://example.com/logo.svg" style={{ height: 24 }} />;
});
```

### Chat Welcome Screen — `chat.welcome`

```tsx
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => (locale.startsWith("zh") ? "Hello!" : "Hello!"),
  description: "I specialize in data analysis.",
  avatar: "https://example.com/avatar.png",
  nick: "My Bot",
  prompts: [
    { label: "Analyze data", value: "Please analyze the uploaded dataset" },
    { label: "Create chart", value: "Create a bar chart from the data" },
  ],
});

// Or fully replace the welcome screen
window.QwenPaw.chat.welcome.render("my-plugin", (props) => {
  return <div>Custom Welcome</div>;
});
```

### Chat Theme — `chat.theme`

```ts
window.QwenPaw.chat.theme.set("my-plugin", {
  colorPrimary: "#1890ff",
});
```

### Chat Header — `chat.leftHeader` / `chat.rightHeader`

```tsx
// Set the left header title
window.QwenPaw.chat.leftHeader.set("my-plugin", {
  title: "My Brand",
  logo: <img src="logo.svg" style={{ height: 20 }} />,
});

// Add a button to the right header
window.QwenPaw.chat.rightHeader.add(
  "my-plugin",
  <button
    onClick={() => alert("Plugin action!")}
    style={{ border: "none", background: "none", cursor: "pointer" }}
  >
    My Button
  </button>,
  { id: "my-plugin.btn", order: 10 },
);
```

### Input Box — `chat.sender`

```ts
// Custom placeholder
window.QwenPaw.chat.sender.set("my-plugin", {
  placeholder: "Ask me anything...",
  disclaimer: "Responses may not be accurate.",
});

// Add input suggestions
window.QwenPaw.chat.sender.addSuggestion("my-plugin", {
  id: "my-plugin.suggestions",
  items: [
    { label: "/analyze", value: "analyze" },
    { label: "/visualize", value: "visualize" },
  ],
});
```

### Message Action Buttons — `chat.actions` / `chat.requestActions`

```tsx
// Add action button below AI responses
window.QwenPaw.chat.actions.add("my-plugin", {
  id: "my-plugin.star",
  icon: <span>⭐</span>,
  onClick: ({ data }) => console.log("Starred:", data),
});

// Add action button below user messages
window.QwenPaw.chat.requestActions.add("my-plugin", {
  id: "my-plugin.edit",
  icon: <span>✏️</span>,
  onClick: ({ data }) => console.log("Edit:", data),
});
```

### Request Payload Transform — `chat.requestPayload`

Use `chat.requestPayload.add` to modify the outgoing chat request body before the Console sends it to the backend. Transforms run in ascending `order` and receive the current payload plus the resolved `sessionId` and `selectedAgent`.

```ts
window.QwenPaw.chat.requestPayload.add(
  "my-plugin",
  ({ payload, sessionId, selectedAgent }) => ({
    ...payload,
    request_context: {
      session_id: sessionId,
      agent_id: selectedAgent,
      datasource_id: "ds-123",
    },
  }),
  { id: "my-plugin.request-context", order: 10 },
);
```

The transform may return a new object to replace the payload. Returning `undefined` leaves the payload unchanged. Use a globally unique `id` so the registration can be audited and disposed cleanly.

### Message Bubble Customization — `chat.request` / `chat.response`

```tsx
// Set the default assistant response avatar and nickname
// This currently reuses welcome.avatar / welcome.nick because the default ResponseCard reads those fields
window.QwenPaw.chat.response.set("my-plugin", {
  avatar: "https://example.com/bot-avatar.png",
  nick: "My Bot",
});

// Prepend content before user messages
window.QwenPaw.chat.request.prepend("my-plugin", ({ data }) => {
  return <div style={{ fontSize: 10, color: "#999" }}>User</div>;
});

// Append an info bar below the latest AI response
window.QwenPaw.chat.response.append("my-plugin", ({ data, isLast }) => {
  if (!isLast) return null;
  return (
    <div
      style={{
        background: "#e3f2fd",
        padding: "4px 8px",
        borderRadius: 4,
        fontSize: 12,
      }}
    >
      Powered by My Plugin
    </div>
  );
});

// Fully replace user message rendering (call fallback() to keep defaults)
window.QwenPaw.chat.request.render("my-plugin", ({ data, fallback }) => {
  return (
    <div style={{ border: "1px dashed #ccc", borderRadius: 8, padding: 4 }}>
      {fallback()}
    </div>
  );
});
```

### Tool-Call Rendering — `chat.toolRender`

```tsx
// Register a custom tool result renderer (props include result, sessionId, messageId)
window.QwenPaw.chat.toolRender("my-plugin", "get_weather", ({ result }) => {
  const data = typeof result === "string" ? JSON.parse(result) : result;
  return (
    <div style={{ padding: 12, border: "1px solid #e8e8e8", borderRadius: 8 }}>
      {data.city}: {data.temperature}°C
    </div>
  );
});
```

### Custom Cards — `chat.card`

```ts
window.QwenPaw.chat.card("my-plugin", "my-card", MyCardComponent);
```

### Audit & Debugging

```ts
// View extension registration records
console.table(window.QwenPaw.audit.overrides());

// Remove all Chat extension registrations for a plugin
window.QwenPaw.chat.disposeAll("my-plugin");
```

### Internationalization

All fields that support the `Localized<T>` type accept a function that returns different values per locale:

```ts
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => (locale.startsWith("zh") ? "Hello!" : "Hello!"),
});
```

### Common Errors

| Error                             | Cause                                         | Solution                                                            |
| --------------------------------- | --------------------------------------------- | ------------------------------------------------------------------- |
| `e.item.render is not a function` | render/prepend/append received a non-function | Ensure you pass a React component or a function returning ReactNode |
| `duplicate id`                    | Two `add` calls used the same id              | Use globally unique ids (recommended format: `pluginId.xxx`)        |
| Hook called outside component     | `useTheme()` etc. used outside React context  | Use imperative APIs like `getSelectedAgentId()` instead             |

## Usage Examples

### Example 1: Add Custom Provider

Let's say you want to connect to an enterprise internal LLM service.

#### 1. Create Plugin Directory

```bash
mkdir my-llm-provider
cd my-llm-provider
```

#### 2. Create plugin.json

```json
{
  "id": "my-llm-provider",
  "name": "My LLM Provider",
  "version": "1.0.0",
  "type": "provider",
  "description": "Custom LLM provider for enterprise",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": ["httpx>=0.24.0"],
  "qwenpaw_version": {
    "min": "1.0.0",
    "max": "2.1.0"
  },
  "meta": {
    "api_key_url": "https://example.com/get-api-key",
    "api_key_hint": "Get your API key from example.com"
  }
}
```

#### 3. Create provider.py

```python
# -*- coding: utf-8 -*-
"""My LLM Provider Implementation."""

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo
from typing import List


class MyLLMProvider(OpenAIProvider):
    """My custom LLM provider (OpenAI-compatible)."""

    def __init__(self, **kwargs):
        """Initialize provider."""
        super().__init__(**kwargs)

    @classmethod
    def get_default_models(cls) -> List[ModelInfo]:
        """Get default models."""
        return [
            ModelInfo(
                id="my-model-v1",
                name="My Model V1",
                supports_multimodal=False,
                supports_image=False,
                supports_video=False,
            ),
            ModelInfo(
                id="my-model-v2",
                name="My Model V2",
                supports_multimodal=True,
                supports_image=True,
                supports_video=False,
            ),
        ]
```

#### 4. Create plugin.py

```python
# -*- coding: utf-8 -*-
"""My LLM Provider Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class MyLLMProviderPlugin:
    """My LLM Provider Plugin."""

    def register(self, api: PluginApi):
        """Register the provider.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering My LLM Provider...")

        # Load provider module from same directory
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        provider_path = os.path.join(plugin_dir, "provider.py")

        spec = importlib.util.spec_from_file_location(
            "my_provider", provider_path
        )
        provider_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provider_module)

        MyLLMProvider = provider_module.MyLLMProvider

        # Register provider
        api.register_provider(
            provider_id="my-llm",
            provider_class=MyLLMProvider,
            label="My LLM",
            base_url="https://api.example.com/v1",
        )

        logger.info("✓ My LLM Provider registered")


# Export plugin instance
plugin = MyLLMProviderPlugin()
```

#### 5. Install and Use

```bash
# Install plugin
qwenpaw plugin install my-llm-provider

# Start QwenPaw
qwenpaw app
```

### Example 2: Add Startup Hook

Let's say you want to initialize a monitoring service when QwenPaw starts.

#### 1. Create Plugin

```bash
mkdir monitoring-hook
cd monitoring-hook
```

#### 2. Create plugin.json

```json
{
  "id": "monitoring-hook",
  "name": "Monitoring Hook",
  "version": "1.0.0",
  "type": "hook",
  "description": "Initialize monitoring service at startup",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "qwenpaw_version": {
    "min": "1.0.0",
    "max": "2.1.0"
  }
}
```

#### 3. Create plugin.py

```python
# -*- coding: utf-8 -*-
"""Monitoring Hook Plugin Entry Point."""

from qwenpaw.plugins.api import PluginApi
import logging

logger = logging.getLogger(__name__)


class MonitoringHookPlugin:
    """Monitoring Hook Plugin."""

    def register(self, api: PluginApi):
        """Register the monitoring hook.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering monitoring hook...")

        def startup_hook():
            """Startup hook to initialize monitoring."""
            try:
                logger.info("=== Monitoring Service Initialization ===")

                # Initialize your monitoring service
                # from my_monitoring import init_monitoring
                # init_monitoring(app_name="QwenPaw")

                logger.info("✓ Monitoring initialized successfully")

            except Exception as e:
                logger.error(
                    f"Failed to initialize monitoring: {e}",
                    exc_info=True,
                )

        # Register startup hook (priority=0 means highest priority)
        api.register_startup_hook(
            hook_name="monitoring_init",
            callback=startup_hook,
            priority=0,
        )

        logger.info("✓ Monitoring hook registered")


# Export plugin instance
plugin = MonitoringHookPlugin()
```

#### 4. Install

```bash
qwenpaw plugin install monitoring-hook
qwenpaw app
```

### Example 3: Add Custom Command

Let's say you want to add a `/status` command to check system status.

#### 1. Create Plugin

```bash
mkdir status-command
cd status-command
```

#### 2. Create plugin.json

```json
{
  "id": "status-command",
  "name": "Status Command",
  "version": "1.0.0",
  "type": "command",
  "description": "Custom status command",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "qwenpaw_version": {
    "min": "1.0.0",
    "max": "2.1.0"
  }
}
```

#### 3. Create plugin.py

```python
# -*- coding: utf-8 -*-
"""Status Command Plugin Entry Point."""

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class StatusCommandPlugin:
    """Status Command Plugin."""

    def register(self, api: PluginApi):
        """Register the status command."""
        from qwenpaw.runtime.commands.control.base import (
            BaseControlCommandHandler,
        )

        class StatusCommandHandler(BaseControlCommandHandler):
            command_name = "status"
            help_text = "Check system status"

            async def handle(self, ctx, args: str):
                from agentscope.message import Msg
                return Msg(
                    name="system",
                    role="assistant",
                    content="System is running normally.",
                )

        api.register_control_command(
            handler=StatusCommandHandler(),
            priority_level=10,
        )
        logger.info("✓ Status command registered: /status")


# Export plugin instance
plugin = StatusCommandPlugin()
```

#### 4. Install and Use

```bash
qwenpaw plugin install status-command
qwenpaw app

# Use the command
/status
```

### Example 4: Add a Custom Frontend Page

Add a welcome page to the sidebar. Build toolchain files (`package.json`, `tsconfig.json`, `vite.config.ts`) follow the "Frontend Plugins > Build Toolchain" section above.

**plugin.json**:

```json
{
  "id": "welcome-plugin",
  "name": "Welcome Plugin",
  "version": "1.0.0",
  "type": "frontend",
  "description": "Welcome page plugin",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

**src/index.tsx**:

```tsx
const { React, antd } = window.QwenPaw.host;
const { Typography, Card } = antd;
const pluginId = "welcome-plugin";

const WelcomePage = () => {
  const theme = window.QwenPaw.host.useTheme();
  return (
    <Card
      style={{
        maxWidth: 480,
        margin: "40px auto",
        background: theme === "dark" ? "#1f1f1f" : "#fff",
      }}
    >
      <Typography.Title level={2}>Welcome to QwenPaw</Typography.Title>
      <Typography.Paragraph>Plugin system is working!</Typography.Paragraph>
    </Card>
  );
};

window.QwenPaw.menu.add(pluginId, {
  id: "welcome-plugin.home",
  label: "Welcome",
  icon: "spark-home-line",
  route: "welcome-plugin.home",
});

window.QwenPaw.route.add(pluginId, {
  id: "welcome-plugin.home",
  path: "/welcome-plugin/home",
  component: WelcomePage,
});
```

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/welcome-plugin/
qwenpaw app
```

### Example 5: Custom Tool-Call Renderer

Customize how Agent tool-call results are displayed. Project structure follows Example 4, only `src/index.tsx` differs.

**src/index.tsx**:

```tsx
const { React, antd } = window.QwenPaw.host;
const { Card, Descriptions } = antd;
const pluginId = "tool-render-plugin";

window.QwenPaw.chat.toolRender(pluginId, "get_weather", ({ result }) => {
  const data = typeof result === "string" ? JSON.parse(result) : result;
  return (
    <Card
      title="Weather Info"
      size="small"
      style={{ marginTop: 8, maxWidth: 400 }}
    >
      <Descriptions column={1} size="small">
        <Descriptions.Item label="City">{data.city}</Descriptions.Item>
        <Descriptions.Item label="Temperature">
          {data.temperature}°C
        </Descriptions.Item>
        <Descriptions.Item label="Weather">{data.weather}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
});
```

### Example 6: Customize Chat Welcome

Customize the chat page greeting, description, and suggested prompts. Project structure follows Example 4, only `src/index.tsx` differs.

**src/index.tsx**:

```tsx
const pluginId = "custom-greeting-plugin";

window.QwenPaw.chat.welcome.set(pluginId, {
  greeting: (locale) =>
    locale.startsWith("zh")
      ? "Hello! I'm customized QwenPaw"
      : "Hello! I'm customized QwenPaw",
  description: "This is a customized chat assistant",
  prompts: [
    { label: "Analyze code", value: "Help me analyze this code" },
    { label: "Unit test", value: "Write a unit test" },
    { label: "Optimize", value: "Optimize this logic" },
  ],
});
```

### Example 7: Expose a FastAPI Endpoint

Backend plugins can expose their own HTTP endpoints by registering a
`fastapi.APIRouter`. The router is mounted under `/api` + your prefix
and is served by the same FastAPI app as QwenPaw's core API, so it
shares CORS settings, the auth layer, and is included in
`/openapi.json` / `/docs`.

In this example we add a small `/api/pets` endpoint that returns a
list of pets and lets the user add new ones.

#### 1. Create plugin directory

```bash
mkdir pet-api-plugin && cd pet-api-plugin
```

#### 2. Create plugin.json

```json
{
  "id": "pet-api-plugin",
  "name": "Pet API Plugin",
  "version": "1.0.0",
  "type": "general",
  "description": "Expose a small REST API under /api/pets",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "qwenpaw_version": {
    "min": "1.1.5",
    "max": "2.1.0"
  }
}
```

#### 3. Create plugin.py

```python
# -*- coding: utf-8 -*-
"""Pet API Plugin Entry Point."""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class Pet(BaseModel):
    """Pet model."""

    id: int
    name: str
    species: str


class PetCreate(BaseModel):
    """Pet creation payload."""

    name: str
    species: str


_PETS: List[Pet] = [
    Pet(id=1, name="Mochi", species="cat"),
    Pet(id=2, name="Bao", species="dog"),
]


def build_router() -> APIRouter:
    """Build the plugin's APIRouter.

    Routes are mounted under ``/api`` + the prefix passed to
    ``register_http_router``. With ``prefix="/pets"`` the handlers
    below are served at ``/api/pets`` and ``/api/pets/{pet_id}``.
    """
    router = APIRouter()

    @router.get("", response_model=List[Pet])
    def list_pets() -> List[Pet]:
        """Return all pets."""
        return list(_PETS)

    @router.get("/{pet_id}", response_model=Pet)
    def get_pet(pet_id: int) -> Pet:
        """Return a single pet by id."""
        for pet in _PETS:
            if pet.id == pet_id:
                return pet
        raise HTTPException(status_code=404, detail="Pet not found")

    @router.post("", response_model=Pet, status_code=201)
    def create_pet(payload: PetCreate) -> Pet:
        """Create a new pet."""
        new_id = (max((p.id for p in _PETS), default=0)) + 1
        pet = Pet(id=new_id, name=payload.name, species=payload.species)
        _PETS.append(pet)
        return pet

    return router


class PetApiPlugin:
    """Pet API Plugin."""

    def register(self, api: PluginApi):
        """Register the HTTP router.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering Pet API plugin...")

        api.register_http_router(
            build_router(),
            prefix="/pets",
            tags=["pets"],
        )

        logger.info("✓ Pet API registered at /api/pets")


# Export plugin instance
plugin = PetApiPlugin()
```

#### 4. Install and try it out

```bash
qwenpaw plugin install pet-api-plugin
```

Once QwenPaw is running:

```bash
# List pets
curl http://127.0.0.1:8088/api/pets

# Get one pet
curl http://127.0.0.1:8088/api/pets/1

# Create a pet
curl -X POST http://127.0.0.1:8088/api/pets \
  -H "Content-Type: application/json" \
  -d '{"name": "Luna", "species": "rabbit"}'
```

**Notes:**

- `prefix` must start with `/` and must not be just `/` — use a
  descriptive segment such as `/pets`. The full URL is always
  `/api` + your prefix.
- Each prefix can only be claimed by one plugin. Registering the
  same prefix twice raises `ValueError`.
- `tags` is optional; when omitted, routes are tagged
  `plugin:<plugin_id>` automatically for OpenAPI grouping.
- Routes are unmounted automatically when the plugin is uninstalled
  or disabled.

### Example 8: Tracing Middleware (Tool Call Tracing)

This example demonstrates how to register an `on_acting` middleware that logs every tool call with timing information when the `QWENPAW_TRACE` environment variable is set.

**plugin.json:**

```json
{
  "id": "middleware-demo-tracing",
  "name": "Tracing Middleware Demo",
  "version": "1.0.0",
  "description": "Demo: logs tool calls with execution timing to a trace file",
  "author": "QwenPaw Team",
  "type": "general",
  "entry": {
    "backend": "tracing_plugin.py"
  },
  "dependencies": [],
  "qwenpaw_version": {
    "min": "1.0.0",
    "max": "2.1.0"
  }
}
```

**tracing_plugin.py:**

```python
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase
from qwenpaw.plugins.api import PluginApi


class TracingMiddleware(MiddlewareBase):
    """Logs tool call name, input, and execution duration."""

    def __init__(self, trace_file: Path) -> None:
        self._trace_file = trace_file
        self._trace_file.parent.mkdir(parents=True, exist_ok=True)

    async def on_acting(
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs["tool_call"]
        tool_name = getattr(tool_call, "name", str(tool_call))
        tool_input = getattr(tool_call, "input", "")

        start = time.perf_counter()
        try:
            async for item in next_handler():
                yield item
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            line = f"[{time.strftime('%H:%M:%S')}] {tool_name}({tool_input[:100]}) — {elapsed_ms:.1f}ms\n"
            with open(self._trace_file, "a", encoding="utf-8") as f:
                f.write(line)


def _tracing_factory(ctx: Any, agent_config: Any) -> TracingMiddleware | None:
    """Create TracingMiddleware when QWENPAW_TRACE env var is set."""
    if not os.environ.get("QWENPAW_TRACE"):
        return None
    workspace_dir = getattr(ctx, "workspace_dir", None)
    if workspace_dir is None:
        return None
    trace_file = Path(workspace_dir) / ".qwenpaw" / "trace.log"
    return TracingMiddleware(trace_file=trace_file)


class TracingPlugin:
    def register(self, api: PluginApi) -> None:
        api.register_middleware(_tracing_factory, priority=50)


plugin = TracingPlugin()
```

**Key points:**

- **Conditional activation**: The factory checks the `QWENPAW_TRACE` environment variable and only activates when set
- **`priority=50`**: Higher priority (lower number = outermost in onion), ensuring tracing wraps other middlewares
- **`on_acting` hook**: Measures execution time before/after tool calls
- Full source: `plugins/middleware-demo/tracing-middleware/tracing_plugin.py`

---

### Example 9: Thinking Log Middleware (Reasoning Process Logger)

This example demonstrates how to register an `on_reasoning` middleware that captures and prints the model's chain-of-thought.

**plugin.json:**

```json
{
  "id": "middleware-demo-thinking-log",
  "name": "Thinking Log Middleware Demo",
  "version": "1.0.0",
  "description": "Demo: prints model reasoning steps to stdout",
  "author": "QwenPaw Team",
  "type": "general",
  "entry": {
    "backend": "thinking_log_plugin.py"
  },
  "dependencies": [],
  "qwenpaw_version": {
    "min": "1.0.0",
    "max": "2.1.0"
  }
}
```

**thinking_log_plugin.py:**

```python
import sys
from typing import Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase
from agentscope.event import ThinkingBlockDeltaEvent, TextBlockDeltaEvent
from qwenpaw.plugins.api import PluginApi


class ThinkingLogMiddleware(MiddlewareBase):
    """Prints reasoning stream events to stdout."""

    async def on_reasoning(
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        async for item in next_handler():
            if isinstance(item, ThinkingBlockDeltaEvent):
                print(f"[THINKING] {item.delta}", end="", file=sys.stdout, flush=True)
            elif isinstance(item, TextBlockDeltaEvent):
                print(f"[TEXT] {item.delta}", end="", file=sys.stdout, flush=True)
            yield item


def _thinking_log_factory(ctx: Any, agent_config: Any) -> ThinkingLogMiddleware:
    """Always create the middleware (unconditional activation)."""
    return ThinkingLogMiddleware()


class ThinkingLogPlugin:
    def register(self, api: PluginApi) -> None:
        api.register_middleware(_thinking_log_factory, priority=80)


plugin = ThinkingLogPlugin()
```

**Key points:**

- **Unconditional activation**: The factory always returns an instance, applied to every request
- **`on_reasoning` hook**: Captures streaming events during the model's reasoning phase (`ThinkingBlockDeltaEvent` for chain-of-thought, `TextBlockDeltaEvent` for text responses)
- **Real-time printing**: Each delta event is printed immediately while being yielded downstream — does not block streaming
- Full source: `plugins/middleware-demo/thinking-log-middleware/thinking_log_plugin.py`

---

### Example 10: Register a Custom Channel

Channel plugins let you add new messaging platforms to QwenPaw. The channel
appears in the Console UI alongside built-in channels (DingTalk, Telegram,
etc.) and can be configured, enabled, and disabled the same way.

#### 1. Create Plugin Directory

```bash
mkdir sample-channel-plugin && cd sample-channel-plugin
```

#### 2. Create plugin.json

```json
{
  "id": "sample-channel",
  "name": "Sample Channel",
  "version": "1.0.0",
  "type": "channel",
  "description": "Sample messaging channel integration for QwenPaw",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": ["sample-sdk>=1.0.0"],
  "qwenpaw_version": {
    "min": "1.1.5",
    "max": "2.1.0"
  }
}
```

#### 3. Create channel.py — BaseChannel subclass

Your channel class must implement the `BaseChannel` contract. The key
methods are:

- **`from_config(cls, process, config, ...)`** — classmethod that creates
  an instance from saved configuration. This is how `ChannelManager`
  instantiates your channel at startup.
- **`start()` / `stop()`** — lifecycle hooks called when the channel is
  enabled/disabled.
- **`send(to_handle, text, meta)`** — send a message to a user/session.

```python
# -*- coding: utf-8 -*-
"""Sample channel implementation."""

import logging
from pathlib import Path
from typing import Optional

from qwenpaw.app.channels.base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
)

logger = logging.getLogger(__name__)


class SampleChannel(BaseChannel):
    """Sample messaging channel."""

    channel = "sample"  # unique key, must match config key

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool = True,
        bot_token: str = "",
        signing_secret: str = "",
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        **kwargs,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self.bot_token = bot_token
        self.signing_secret = signing_secret

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Optional[Path] = None,
    ) -> "SampleChannel":
        """Create from config.

        Note: for plugin channels, ``config`` is a
        ``types.SimpleNamespace`` object (not a dict). Use
        ``getattr(config, "field", default)`` to read fields safely.
        """
        return cls(
            process=process,
            enabled=getattr(config, "enabled", False),
            bot_token=getattr(config, "bot_token", ""),
            signing_secret=getattr(config, "signing_secret", ""),
            bot_prefix=getattr(config, "bot_prefix", ""),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )

    async def start(self):
        """Start the sample event listener."""
        logger.info("Sample channel starting (token=%s...)", self.bot_token[:8])
        # Start your platform's API client here

    async def stop(self):
        """Stop the sample event listener."""
        logger.info("Sample channel stopping")

    async def send(self, to_handle: str, text: str, meta=None):
        """Send a message to a sample user or channel."""
        logger.info("Sending to sample %s: %s", to_handle, text[:50])
        # Use sample-sdk to post messages
```

> **Important: `config` parameter type** — For plugin channels, the
> `config` passed to `from_config()` is a `types.SimpleNamespace` object
> (not a dict or Pydantic model). The framework merges
> `BaseChannelConfig` defaults with the user's saved config before
> passing it. Always use `getattr(config, "field", default)` to read
> fields safely.

#### 4. Create plugin.py — Plugin entry point

```python
# -*- coding: utf-8 -*-
"""Sample Channel Plugin Entry Point."""

import logging
from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class SampleChannelPlugin:
    """Sample Channel Plugin."""

    def register(self, api: PluginApi):
        """Register the sample channel."""
        from .channel import SampleChannel

        api.register_channel(
            channel_class=SampleChannel,
            label="Sample",
            description="Sample messaging channel integration",
            icon="https://example.com/sample-icon.png",  # optional card icon (http/https only)
            doc_url={  # optional doc link, plain string or localized dict (http/https only)
                "zh": "https://example.com/docs?lang=zh",
                "en": "https://example.com/docs?lang=en",
            },
            config_fields=[
                {
                    "name": "bot_token",
                    "label": "Bot Token",
                    "type": "password",
                    "required": True,
                    "placeholder": "your-bot-token-here",
                    "help": "Bot access token",
                },
                {
                    "name": "signing_secret",
                    "label": "Signing Secret",
                    "type": "password",
                    "required": True,
                    "help": "Signing secret for request verification",
                },
                {
                    "name": "streaming_enabled",
                    "label": {
                        "zh-CN": "流式输出",
                        "en-US": "Streaming Output",
                    },
                    "type": "switch",
                    "required": False,
                    "default": False,
                },
            ],
        )
        logger.info("✓ Sample channel registered")


plugin = SampleChannelPlugin()
```

#### 5. Install and Use

```bash
qwenpaw plugin install sample-channel-plugin
qwenpaw app
```

After starting, go to **Control → Channels** in the Console. The sample
channel card will appear alongside built-in channels. Click it to fill in
credentials and enable it.

#### 6. Adding Webhook Endpoints (Optional)

If your channel needs to receive HTTP callbacks (e.g. your platform's
events API), register a FastAPI router in the same plugin:

```python
from fastapi import APIRouter

def register(self, api: PluginApi):
    from .channel import SampleChannel

    api.register_channel(channel_class=SampleChannel, ...)

    # Mount webhook endpoint at /api/sample/events
    router = APIRouter()

    @router.post("/events")
    async def sample_events(request):
        body = await request.json()
        # Handle event verification and messages
        return {"ok": True}

    api.register_http_router(router, prefix="/sample", tags=["sample"])
```

**Key points:**

- The `channel_class` must be a `BaseChannel` subclass with a `channel`
  class attribute (the unique key).
- **You must implement `from_config`** — this is how `ChannelManager`
  creates your channel at startup. The `config` parameter is a
  `SimpleNamespace`, not a dict.
- `config_fields` defines the form fields shown in the Console settings
  drawer. Supported types: `text`, `password`, `number`, `switch`, `select`.
- The `label`, `help`, and `placeholder` of each field accept either a
  plain string or a localized dict. Dict keys support **both long codes
  (e.g. `zh-CN`, `en-US`) and short codes (e.g. `zh`, `en`), which can be
  mixed freely**. The value is resolved with fallback in order (exact locale
  → short code → short-code prefix match → English → Chinese → first
  non-empty value) so a missing locale never renders blank.
- `icon` (optional) is a custom icon URL for the channel card. Only
  `http`/`https` URLs are supported; other values are ignored and fall back
  to the default icon.
- `doc_url` (optional) is a documentation link for the channel. It can be a
  plain string or a localized dict (e.g. `{"zh": "...", "en": "..."}`, same
  long/short code rules as `label`). Only `http`/`https` URLs are supported;
  the Console shows a "Doc" button in the settings drawer header that opens
  the link for the current language, and hides it when the value is invalid
  or missing.
- Plugin channels share the same enable/disable, access control, and
  `bot_prefix` features as built-in channels.
- If a plugin channel key conflicts with a built-in key, the built-in
  takes precedence and the plugin channel is skipped with a warning.
- For webhook-based channels, combine `register_channel` with
  `register_http_router` in the same plugin.

## Dependency Management

### Using requirements.txt

If your plugin requires additional Python packages, create `requirements.txt`:

```
httpx>=0.24.0
pydantic>=2.0.0
```

Dependencies will be automatically installed when the plugin is installed.

### Using Custom PyPI Index

```
--index-url https://custom-pypi.example.com/simple
my-package>=1.0.0
```

## Best Practices

### 1. Naming Conventions

- **Plugin ID**: Use lowercase letters and hyphens, e.g., `my-plugin`
- **Version**: Follow semantic versioning (1.0.0, 1.1.0, 2.0.0)

### 2. Error Handling

Hook callbacks should handle errors gracefully to avoid blocking application startup:

```python
def startup_hook():
    try:
        # Your initialization code
        pass
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        # Don't raise, let the application continue
```

### 3. Logging

Use Python logging to record plugin behavior:

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Plugin loaded")
logger.debug("Debug information")
logger.error("Error occurred", exc_info=True)
```

### 4. Documentation

Provide clear README.md documentation including:

- Feature description
- Installation steps
- Usage examples
- Configuration instructions
- Troubleshooting

## Priority System

### Hook Priority

Hooks are executed in priority order:

- **Lower priority values execute earlier**
- Priority 0 = Highest priority (executes first)
- Priority 100 = Default priority
- Priority 200 = Low priority (executes last)

**Example**:

```python
# Executes first
api.register_startup_hook("early", callback, priority=0)

# Default order
api.register_startup_hook("normal", callback, priority=100)

# Executes last
api.register_startup_hook("late", callback, priority=200)
```

## Troubleshooting

### Plugin Not Loading

1. Check if plugin is installed:

   ```bash
   qwenpaw plugin list
   ```

2. View QwenPaw logs:

   ```bash
   tail -f ~/.qwenpaw/logs/qwenpaw.log | grep -i plugin
   ```

3. Verify plugin manifest format:
   ```bash
   qwenpaw plugin info <plugin-id>
   ```

### Dependency Installation Failed

1. Check `requirements.txt` format
2. Manually test dependency installation:
   ```bash
   pip install -r /path/to/plugin/requirements.txt
   ```
3. Reinstall plugin with `--force` flag

### Provider Not Showing

1. Confirm plugin is installed and restart QwenPaw
2. Check the model management page in Web UI
3. Review provider registration info in logs

### Command Not Responding

1. Confirm plugin is installed
2. Check if the command handler was registered successfully in logs
3. Verify the command name matches (e.g. `/status`)

## Security Considerations

1. **Only install trusted plugins**: Plugin code executes in the QwenPaw process
2. **Check dependencies**: Ensure plugin dependencies come from trusted sources
3. **Review code**: Review plugin source code before installation
4. **Hot-loading awareness**: The current version supports hot-installing/uninstalling plugins via API while the app is running. Be mindful of state consistency during hot-loading

## PluginApi Reference

### register_provider

Register a custom LLM provider.

```python
api.register_provider(
    provider_id: str,              # Unique provider identifier (required)
    provider_class: Type,          # Provider class (required)
    label: str = "",               # Display name (optional, defaults to provider_id)
    base_url: str = "",            # API base URL (optional)
    **metadata,                    # Additional keyword args (chat_model, require_api_key, etc.)
)
```

### register_startup_hook

Register a startup hook.

```python
api.register_startup_hook(
    hook_name: str,      # Hook name
    callback: Callable,  # Callback function
    priority: int = 100, # Priority (lower = earlier)
)
```

### register_shutdown_hook

Register a shutdown hook.

```python
api.register_shutdown_hook(
    hook_name: str,      # Hook name
    callback: Callable,  # Callback function
    priority: int = 100, # Priority (lower = earlier)
)
```

### register_http_router

Mount a `fastapi.APIRouter` under `/api` + _prefix_.

```python
api.register_http_router(
    router: APIRouter,             # fastapi.APIRouter instance
    *,
    prefix: str,                   # Path under /api, e.g. "/pets"
    tags: Optional[List[str]] = None,  # OpenAPI tags (optional)
)
```

See [Example 7](#example-7-expose-a-fastapi-endpoint) for a full
walkthrough.

### register_control_command

Register a custom `/slash` control command.

```python
api.register_control_command(
    handler: BaseControlCommandHandler,  # Command handler instance
    priority_level: int = 10,            # Command priority (default: 10)
)
```

The handler must inherit from `qwenpaw.runtime.commands.control.base.BaseControlCommandHandler` and implement `command_name`, `help_text`, and `async handle(self, ctx, args)`.

### register_tool

Register a tool function into the Agent's toolkit.

```python
api.register_tool(
    tool_name: str,          # Unique tool function name
    tool_func: Callable,     # The tool callable to register
    description: str = "",   # Human-readable description shown in the UI
    icon: str = "🔧",        # Display icon (emoji string)
    enabled: bool = False,   # Whether the tool is enabled by default
)
```

### register_uninstall_hook

Register a hook that runs only when the plugin is explicitly uninstalled.

```python
api.register_uninstall_hook(
    hook_name: str,      # Hook name
    callback: Callable,  # Callback function
    priority: int = 100, # Priority (lower = earlier)
)
```

### register_workspace_created_hook

Register a hook that fires when a new workspace is created.

```python
api.register_workspace_created_hook(
    hook_name: str,      # Hook name
    callback: Callable,  # Callback: (workspace_info: dict) -> None
    priority: int = 100, # Priority (lower = earlier)
)
```

### get_tool_config / set_tool_config

Get or save per-agent tool configuration.

```python
config = api.get_tool_config(tool_name: str, agent_id: str)  # Returns dict
api.set_tool_config(tool_name: str, agent_id: str, config: dict)
```

### register_middleware

Register an AgentScope `MiddlewareBase` factory.

```python
api.register_middleware(
    middleware_factory: Callable,   # Factory function
    *,
    priority: int = 100,           # Priority (lower = outermost)
)
```

Factory signature: `(ctx: HookContext, agent_config: AgentProfileConfig) -> MiddlewareBase | None`

- `ctx` contains request-level context such as `session_id`, `agent_id`, `workspace_dir`
- Returning `None` means this middleware is skipped for the current request
- Lower `priority` values place the middleware further out in the onion model (executed first)

The factory is called during `AgentBuilder.build()` for each request. The returned middleware instance is inserted into the agent's middleware chain.

See [Example 8](#example-8-tracing-middleware) and [Example 9](#example-9-thinking-log-middleware) above for full walkthroughs.

## Advanced Features

### Modifying Agent Behavior

To intercept or enhance agent request processing, use one of these approaches:

- **Enhance the agent reasoning loop**: use `register_middleware` to inject AgentScope middlewares (`on_acting` / `on_reasoning` hooks)
- **Intercept specific commands**: use `register_control_command` to register a custom command handler
- **Inject logic into the request lifecycle**: use `HookRegistry` (8-phase hooks)

The current request flow is `Runtime.run()` → `AgentBuilder.build()` → `AgentExecutor.run()`.

### Custom Commands

In 2.0, the recommended way to add custom `/slash` commands is via `api.register_control_command()`. This replaces the old monkey patching approach:

```python
from qwenpaw.runtime.commands.control.base import BaseControlCommandHandler

class MyCommandHandler(BaseControlCommandHandler):
    command_name = "mycommand"
    help_text = "Description of my command"

    async def handle(self, ctx, args: str):
        from agentscope.message import Msg
        return Msg(
            name="system",
            role="assistant",
            content="Command result here.",
        )

api.register_control_command(
    handler=MyCommandHandler(),
    priority_level=10,
)
```

### Access Runtime Information

Access runtime information through `api.runtime`:

```python
def my_hook():
    # Access provider manager
    provider_manager = api.runtime.provider_manager

    # Get all providers
    providers = provider_manager.list_provider_info()
```

## Plugin Packaging

Package your plugin as a ZIP file for distribution:

```bash
cd /path/to/plugins
zip -r my-plugin-1.0.0.zip my-plugin/
```

Users can install via URL:

```bash
qwenpaw plugin install https://example.com/my-plugin-1.0.0.zip
```

## FAQ

### Q: What QwenPaw APIs can plugins access?

A: Plugins access core functionality through `PluginApi`, including:

- Provider registration
- Middleware registration (`register_middleware`)
- Hook registration
- Custom command registration (`register_control_command`)
- HTTP router registration (`register_http_router`)
- Runtime helpers (provider_manager, etc.)

### Q: Can plugins modify QwenPaw's core behavior?

A: Yes, through `register_middleware` (inject AgentScope middlewares), `register_control_command`, `register_tool`, runtime hooks, and other PluginApi methods. Use with caution to avoid breaking core functionality.

### Q: Will plugins conflict with each other?

A: If multiple plugins register the same provider_id or command_name, the later one will override the earlier one. Use unique IDs.

## Example Plugins

### GPT Image 2 Tool Plugin

A tool plugin that adds OpenAI's GPT Image 2 image generation capability to QwenPaw agents.

**Requirements:**

- Minimum QwenPaw version: `1.1.5`

**Installation:**

```bash
# Clone the QwenPaw repository (if not already cloned)
git clone https://github.com/agentscope-ai/QwenPaw.git
cd QwenPaw

# Install the plugin
qwenpaw plugin install plugins/tool/gpt-image2
```

**Configuration:**

1. After installation, restart QwenPaw
2. Go to Agent Settings → Tools
3. Find "generate_image_gpt" tool
4. Click "Configure" and enter your OpenAI API Key
5. Enable the tool

**Usage:**

Once configured, agents can generate images by calling the tool:

```
User: Please generate an image of a cute cat playing in a garden
Agent: [Calls generate_image_gpt tool]
       [Returns generated image]
```

**Features:**

- Supports multiple image sizes: 1024x1024, 1024x1792, 1792x1024
- Quality options: low, medium, high, auto
- Automatic API key validation
- Per-agent configuration (each agent can have its own API key)

For more details, see `plugins/tool/gpt-image2/README.md`.
