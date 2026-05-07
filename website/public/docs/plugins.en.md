# Plugin System

QwenPaw provides a plugin system that allows users to extend QwenPaw's functionality.

## Overview

The plugin system supports the following extension capabilities:

- **Provider Plugins**: Add new LLM providers and models
- **Hook Plugins**: Execute custom code during application startup/shutdown
- **Command Plugins**: Register custom `/command` magic commands
- **Frontend Page Plugins**: Add custom pages to the sidebar
- **Tool Renderer Plugins**: Customize how Agent tool-call results are displayed
- **Behavior Extension Plugins**: Replace methods in frontend internal modules via the module registry

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
  "description": "Plugin description",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "0.1.0",
  "meta": {}
}
```

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

#### Basic Structure

Each frontend plugin requires at minimum:

```
my-plugin/
├── plugin.json      # Plugin manifest (required)
├── src/
│   └── index.tsx    # Entry point (required)
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
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

#### src/index.tsx

```tsx
const { React, antd } = (window as any).QwenPaw.host;

class MyPlugin {
  readonly id = "my-plugin";

  setup(): void {
    // Register sidebar pages
    // (window as any).QwenPaw.registerRoutes?.(this.id, [...]);
    // Register tool-call renderers
    // (window as any).QwenPaw.registerToolRender?.(this.id, {...});
    // Access and modify application internal modules
    // const mod = (window as any).QwenPaw?.modules?.['xxxx'];
  }
}

new MyPlugin().setup();
```

#### package.json

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

#### tsconfig.json

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

#### vite.config.ts

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

#### Build and Install

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/my-plugin/
qwenpaw app
```

**Notes**: `window.QwenPaw.host` provides the following shared libraries — plugins do not need to bundle them:

| Name              | Type                       | Description                  |
| ----------------- | -------------------------- | ---------------------------- |
| `React`           | `typeof React`             | React runtime                |
| `antd`            | `typeof antd`              | Ant Design component library |
| `getApiUrl(path)` | `(path: string) => string` | Build a full API URL         |
| `getApiToken()`   | `() => string`             | Get the current auth token   |

**Build notes**:

- `jsxRuntime: "classic"` — Compiles JSX to `React.createElement`, using the host-provided `React`; no import needed in the plugin
- `external: ["react", "react-dom"]` — Don't bundle React; use the version already loaded by the application

**`window.QwenPaw.modules`**: At startup, the application auto-registers all modules under `src/pages/` into this object. Plugins can access and replace internal exports by module.

> ⚠️ **Warning**: The module structure inside `modules` is not maintained as a public API and may change across versions. Always verify compatibility before use.

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
  "description": "Custom LLM provider for enterprise",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": ["httpx>=0.24.0"],
  "min_version": "0.1.0",
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
            metadata={},
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
  "description": "Initialize monitoring service at startup",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "0.1.0"
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
  "description": "Custom status command",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "0.1.0"
}
```

#### 3. Create query_rewriter.py

```python
# -*- coding: utf-8 -*-
"""Query rewriter for status command."""


class StatusQueryRewriter:
    """Rewrite /status queries to agent prompts."""

    @staticmethod
    def should_rewrite(query: str) -> bool:
        """Check if query should be rewritten."""
        if not query:
            return False
        return query.strip().lower().startswith("/status")

    @staticmethod
    def rewrite(query: str) -> str:
        """Rewrite /status query to agent prompt."""
        return """Please check the system status, including:

1. Current model and provider
2. Memory usage
3. Recent conversation count
4. Plugin loading status

Please present this information in a clear format."""
```

#### 4. Create plugin.py

```python
# -*- coding: utf-8 -*-
"""Status Command Plugin Entry Point."""

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class StatusCommandPlugin:
    """Status Command Plugin."""

    def register(self, api: PluginApi):
        """Register the status command.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering status command...")

        # Register startup hook to patch query handler
        api.register_startup_hook(
            hook_name="status_query_rewriter",
            callback=self._patch_query_handler,
            priority=50,
        )

        logger.info("✓ Status command registered: /status")

    def _patch_query_handler(self):
        """Patch AgentRunner.query_handler to rewrite /status queries."""
        from qwenpaw.app.runner.runner import AgentRunner
        from .query_rewriter import StatusQueryRewriter

        original_query_handler = AgentRunner.query_handler

        async def patched_query_handler(self, msgs, request=None, **kwargs):
            """Patched query handler."""
            if msgs and len(msgs) > 0:
                last_msg = msgs[-1]
                if hasattr(last_msg, 'content'):
                    content_list = (
                        last_msg.content
                        if isinstance(last_msg.content, list)
                        else [last_msg.content]
                    )
                    for content_item in content_list:
                        if (
                            isinstance(content_item, dict)
                            and content_item.get('type') == 'text'
                        ):
                            text = content_item.get('text', '')
                            if StatusQueryRewriter.should_rewrite(text):
                                rewritten = StatusQueryRewriter.rewrite(text)
                                logger.info("Rewriting /status query")
                                content_item['text'] = rewritten
                                break

            async for result in original_query_handler(
                self,
                msgs,
                request,
                **kwargs,
            ):
                yield result

        AgentRunner.query_handler = patched_query_handler
        logger.info("✓ Patched AgentRunner.query_handler for /status")


# Export plugin instance
plugin = StatusCommandPlugin()
```

#### 5. Install and Use

```bash
qwenpaw plugin install status-command
qwenpaw app

# Use the command
/status
```

### Example 4: Add a Custom Frontend Page

Add a welcome page to the sidebar.

#### 1. Create plugin directory

```bash
mkdir welcome-plugin && cd welcome-plugin
```

#### 2. Create plugin.json

```json
{
  "id": "welcome-plugin",
  "name": "Welcome Plugin",
  "version": "1.0.0",
  "description": "Welcome page plugin",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

#### 3. Create src/index.tsx

```tsx
const { React, antd } = (window as any).QwenPaw.host;
const { Typography, Card } = antd;
const { Title, Paragraph } = Typography;

function WelcomePage() {
  return (
    <Card style={{ maxWidth: 480, margin: "40px auto" }}>
      <Title level={2}>Welcome to QwenPaw 👋</Title>
      <Paragraph>Plugin system is working!</Paragraph>
    </Card>
  );
}

class WelcomePlugin {
  readonly id = "welcome-plugin";

  setup(): void {
    (window as any).QwenPaw.registerRoutes?.(this.id, [
      {
        path: "/plugin/welcome-plugin/home",
        component: WelcomePage,
        label: "Welcome",
        icon: "👋",
        priority: 5,
      },
    ]);
  }
}

new WelcomePlugin().setup();
```

#### 4. Create package.json

```json
{
  "name": "welcome-plugin",
  "version": "1.0.0",
  "scripts": { "build": "vite build" },
  "devDependencies": {
    "vite": "^5.0.0",
    "typescript": "^5.0.0",
    "@vitejs/plugin-react": "^4.0.0"
  }
}
```

#### 5. Create tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react",
    "strict": false,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

#### 6. Create vite.config.ts

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

#### 7. Build and install

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/welcome-plugin/
qwenpaw app
```

### Example 5: Custom Tool-Call Renderer

Customize how Agent tool-call results are displayed.

#### 1. Create plugin directory

```bash
mkdir tool-render-plugin && cd tool-render-plugin
```

#### 2. Create plugin.json

```json
{
  "id": "tool-render-plugin",
  "name": "Tool Render Plugin",
  "version": "1.0.0",
  "description": "Custom tool result renderer",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

#### 3. Create src/index.tsx

```tsx
const { React, antd } = (window as any).QwenPaw.host;
const { Card, Descriptions } = antd;

function WeatherToolCard({ result }) {
  try {
    const data = typeof result === "string" ? JSON.parse(result) : result;
    return (
      <Card
        title="Weather Information"
        size="small"
        style={{ marginTop: 8, maxWidth: 400 }}
      >
        <Descriptions column={1} size="small">
          <Descriptions.Item label="City">{data.city}</Descriptions.Item>
          <Descriptions.Item label="Temperature">
            {data.temperature}°C
          </Descriptions.Item>
          <Descriptions.Item label="Weather">{data.weather}</Descriptions.Item>
          <Descriptions.Item label="Humidity">
            {data.humidity}%
          </Descriptions.Item>
        </Descriptions>
      </Card>
    );
  } catch (e) {
    return <pre>{JSON.stringify(result, null, 2)}</pre>;
  }
}

class ToolRenderPlugin {
  readonly id = "tool-render-plugin";

  setup(): void {
    (window as any).QwenPaw.registerToolRender?.(this.id, {
      get_weather: WeatherToolCard, // Tool name must match Agent's return
    });
  }
}

new ToolRenderPlugin().setup();
```

#### 4. Reuse other files

Reuse `package.json`, `tsconfig.json`, `vite.config.ts` from Example 4, changing `name` to `tool-render-plugin`.

#### 5. Build and install

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/tool-render-plugin/
qwenpaw app
```

### Example 6: Modify Component Behavior

Customize the chat page greeting.

#### 1. Create plugin directory

```bash
mkdir custom-greeting-plugin && cd custom-greeting-plugin
```

#### 2. Create plugin.json

```json
{
  "id": "custom-greeting-plugin",
  "name": "Custom Greeting",
  "version": "1.0.0",
  "description": "Customize chat greeting",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

#### 3. Create src/index.tsx

```tsx
class CustomGreetingPlugin {
  readonly id = "custom-greeting-plugin";

  setup(): void {
    const mod = (window as any).QwenPaw?.modules?.[
      "Chat/OptionsPanel/defaultConfig"
    ];
    if (!mod?.configProvider) {
      console.warn("configProvider not found");
      return;
    }

    // Replace chat greeting
    mod.configProvider.getGreeting = () => "Hello! I'm customized QwenPaw 👋";

    // Replace chat description
    mod.configProvider.getDescription = () =>
      "This is a customized chat assistant";

    // Replace prompt list
    mod.configProvider.getPrompts = (t: any) => [
      { value: "Help me analyze this code" },
      { value: "Write a unit test" },
      { value: "Optimize this logic" },
    ];
  }
}

new CustomGreetingPlugin().setup();
```

#### 4. Reuse other files

Reuse `package.json`, `tsconfig.json`, `vite.config.ts` from Example 4, changing `name` to `custom-greeting-plugin`.

#### 5. Build and install

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/custom-greeting-plugin/
qwenpaw app
```

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
2. Check if startup hook executed successfully
3. Review patch information in logs

## Security Considerations

1. **Only install trusted plugins**: Plugin code executes in the QwenPaw process
2. **Check dependencies**: Ensure plugin dependencies come from trusted sources
3. **Review code**: Review plugin source code before installation
4. **Offline operations**: Plugin install/uninstall requires QwenPaw to be offline

## PluginApi Reference

### register_provider

Register a custom LLM provider.

```python
api.register_provider(
    provider_id: str,          # Unique provider identifier
    provider_class: Type,      # Provider class
    label: str,                # Display name
    base_url: str,             # API base URL
    metadata: Dict[str, Any],  # Additional metadata
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

## Advanced Features

### Monkey Patching

For plugins that need to modify QwenPaw behavior (like custom commands), you can use monkey patching:

```python
def _patch_query_handler(self):
    """Patch AgentRunner to intercept queries."""
    from qwenpaw.app.runner.runner import AgentRunner

    original_handler = AgentRunner.query_handler

    async def patched_handler(self, msgs, request=None, **kwargs):
        # Your custom logic
        # Modify msgs or add extra processing

        # Call original handler
        async for result in original_handler(self, msgs, request, **kwargs):
            yield result

    AgentRunner.query_handler = patched_handler
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
- Hook registration
- Runtime helpers (provider_manager, etc.)

### Q: Can plugins modify QwenPaw's core behavior?

A: Yes, through monkey patching or hook mechanisms. But use with caution to avoid breaking core functionality.

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
