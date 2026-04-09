# Plugin System

CoPaw provides a plugin system that allows users to extend CoPaw's functionality.

## Overview

The plugin system supports the following extension capabilities:

- **Custom Providers**: Add new LLM providers and models
- **Lifecycle Hooks**: Execute custom code during application startup/shutdown
- **Magic Commands**: Register custom `/command` commands

## Plugin Management

### Install Plugin

Install from local directory:

```bash
copaw plugin install /path/to/plugin
```

Install from URL (supports ZIP files):

```bash
copaw plugin install https://example.com/plugin.zip
```

Force reinstall:

```bash
copaw plugin install /path/to/plugin --force
```

**Note**: Plugin operations can only be performed when CoPaw is offline.

### List Installed Plugins

```bash
copaw plugin list
```

Example output:

```
Installed Plugins:
==================

my-provider (v1.0.0)
  Custom LLM provider integration
  Author: Developer Name
  Path: /Users/user/.copaw/plugins/my-provider
```

### View Plugin Details

```bash
copaw plugin info <plugin-id>
```

### Uninstall Plugin

```bash
copaw plugin uninstall <plugin-id>
```

## Plugin Types

### 1. Provider Plugins

Add custom LLM providers to support new model services.

**Use Cases**:

- Connect to enterprise internal LLM services
- Support specific model APIs
- Add custom model configurations

**Core API**:

```python
api.register_provider(
    provider_id="my-provider",
    provider_class=MyProvider,
    label="My Provider",
    base_url="https://api.example.com/v1",
    metadata={},
)
```

### 2. Hook Plugins

Execute custom code at specific moments in the application lifecycle.

**Use Cases**:

- Initialize third-party services (monitoring, logging)
- Load custom configurations
- Perform startup checks

**Core API**:

```python
# Startup hook
api.register_startup_hook(
    hook_name="my_startup",
    callback=startup_callback,
    priority=100,  # Lower = earlier execution
)

# Shutdown hook
api.register_shutdown_hook(
    hook_name="my_shutdown",
    callback=shutdown_callback,
    priority=100,
)
```

### 3. Command Plugins

Register custom magic commands (like `/feedback`).

**Use Cases**:

- Add shortcut commands
- Implement specific workflows
- Integrate external tools

**Implementation**:

Use monkey patching to rewrite user input, converting commands into prompts that the agent can understand.

## Plugin Development

### Basic Structure

Each plugin requires at least two files:

```
my-plugin/
├── plugin.json      # Plugin manifest (required)
├── plugin.py        # Entry point (required)
└── README.md        # Documentation (recommended)
```

### plugin.json

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "Plugin description",
  "author": "Your Name",
  "entry_point": "plugin.py",
  "dependencies": [],
  "min_copaw_version": "0.1.0",
  "meta": {}
}
```

### plugin.py

```python
# -*- coding: utf-8 -*-
"""My Plugin Entry Point."""

from copaw.plugins.api import PluginApi
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
  "entry_point": "plugin.py",
  "dependencies": ["httpx>=0.24.0"],
  "min_copaw_version": "0.1.0",
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

from copaw.providers.provider import ModelInfo, Provider
from typing import List


class MyLLMProvider(Provider):
    """My custom LLM provider."""

    def __init__(self, **kwargs):
        """Initialize provider."""
        super().__init__(**kwargs)

    @classmethod
    def get_default_models(cls) -> List[ModelInfo]:
        """Get default models."""
        return [
            ModelInfo(
                id="my-model",
                name="My Model",
                supports_multimodal=False,
                supports_image=False,
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

from copaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class MyLLMProviderPlugin:
    """My LLM Provider Plugin."""

    def register(self, api: PluginApi):
        """Register the provider.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering My LLM Provider...")

        # Load provider module
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        provider_path = os.path.join(plugin_dir, "provider.py")

        spec = importlib.util.spec_from_file_location(
            "my_provider",
            provider_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load provider from {provider_path}")

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
copaw plugin install my-llm-provider

# Start CoPaw
copaw app

# Configure API Key in Web UI
# Then you can use the new provider
```

### Example 2: Add Startup Hook

Let's say you want to initialize a monitoring service when CoPaw starts.

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
  "entry_point": "plugin.py",
  "dependencies": [],
  "min_copaw_version": "0.1.0"
}
```

#### 3. Create plugin.py

```python
# -*- coding: utf-8 -*-
"""Monitoring Hook Plugin Entry Point."""

from copaw.plugins.api import PluginApi
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
                # init_monitoring(app_name="CoPaw")

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
copaw plugin install monitoring-hook
copaw app
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
  "entry_point": "plugin.py",
  "dependencies": [],
  "min_copaw_version": "0.1.0"
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

from copaw.plugins.api import PluginApi

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
        from copaw.app.runner.runner import AgentRunner
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
copaw plugin install status-command
copaw app

# Use the command
/status
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
   copaw plugin list
   ```

2. View CoPaw logs:

   ```bash
   tail -f ~/.copaw/logs/copaw.log | grep -i plugin
   ```

3. Verify plugin manifest format:
   ```bash
   copaw plugin info <plugin-id>
   ```

### Dependency Installation Failed

1. Check `requirements.txt` format
2. Manually test dependency installation:
   ```bash
   pip install -r /path/to/plugin/requirements.txt
   ```
3. Reinstall plugin with `--force` flag

### Provider Not Showing

1. Confirm plugin is installed and restart CoPaw
2. Check the model management page in Web UI
3. Review provider registration info in logs

### Command Not Responding

1. Confirm plugin is installed
2. Check if startup hook executed successfully
3. Review patch information in logs

## Security Considerations

1. **Only install trusted plugins**: Plugin code executes in the CoPaw process
2. **Check dependencies**: Ensure plugin dependencies come from trusted sources
3. **Review code**: Review plugin source code before installation
4. **Offline operations**: Plugin install/uninstall requires CoPaw to be offline

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

For plugins that need to modify CoPaw behavior (like custom commands), you can use monkey patching:

```python
def _patch_query_handler(self):
    """Patch AgentRunner to intercept queries."""
    from copaw.app.runner.runner import AgentRunner

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
copaw plugin install https://example.com/my-plugin-1.0.0.zip
```

## FAQ

### Q: What CoPaw APIs can plugins access?

A: Plugins access core functionality through `PluginApi`, including:

- Provider registration
- Hook registration
- Runtime helpers (`provider_manager`, etc.)

### Q: Can plugins modify CoPaw's core behavior?

A: Yes, through monkey patching or hook mechanisms. But use with caution to avoid breaking core functionality.

### Q: Will plugins conflict with each other?

A: If multiple plugins register the same `provider_id` or `command_name`, the later one will override the earlier one. Use unique IDs.
