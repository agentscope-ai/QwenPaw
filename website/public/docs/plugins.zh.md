# 插件系统

CoPaw 提供了插件系统，允许用户扩展 CoPaw 的功能。

## 概述

插件系统支持以下扩展能力：

- **自定义 Provider**：添加新的 LLM Provider 和模型
- **生命周期钩子**：在应用启动/关闭时执行自定义代码
- **魔法命令**：注册自定义的 `/command` 命令

## 插件管理

### 安装插件

从本地目录安装：

```bash
copaw plugin install /path/to/plugin
```

从 URL 安装（支持 ZIP 文件）：

```bash
copaw plugin install https://example.com/plugin.zip
```

强制重新安装：

```bash
copaw plugin install /path/to/plugin --force
```

**注意**：插件操作只能在 CoPaw 离线时执行。

### 列出已安装插件

```bash
copaw plugin list
```

输出示例：

```
Installed Plugins:
==================

my-provider (v1.0.0)
  Custom LLM provider integration
  Author: Developer Name
  Path: /Users/user/.copaw/plugins/my-provider
```

### 查看插件详情

```bash
copaw plugin info <plugin-id>
```

### 卸载插件

```bash
copaw plugin uninstall <plugin-id>
```

## 插件类型

### 1. Provider 插件

添加自定义 LLM Provider，支持新的模型服务。

**示例场景**：

- 接入企业内部的 LLM 服务
- 支持特定的模型 API
- 添加自定义的模型配置

**核心 API**：

```python
api.register_provider(
    provider_id="my-provider",
    provider_class=MyProvider,
    label="My Provider",
    base_url="https://api.example.com/v1",
    metadata={},
)
```

### 2. Hook 插件

在应用生命周期的特定时刻执行自定义代码。

**示例场景**：

- 初始化第三方服务（如监控、日志）
- 加载自定义配置
- 执行启动检查

**核心 API**：

```python
# 启动钩子
api.register_startup_hook(
    hook_name="my_startup",
    callback=startup_callback,
    priority=100,  # 越低越先执行
)

# 关闭钩子
api.register_shutdown_hook(
    hook_name="my_shutdown",
    callback=shutdown_callback,
    priority=100,
)
```

### 3. Command 插件

注册自定义的魔法命令（如 `/feedback`）。

**示例场景**：

- 添加快捷命令
- 实现特定工作流
- 集成外部工具

**实现方式**：

通过 monkey patch 改写用户输入，将命令转换为 Agent 可理解的 prompt。

## 插件开发

### 基本结构

每个插件至少需要两个文件：

```
my-plugin/
├── plugin.json      # 插件清单（必需）
├── plugin.py        # 入口点（必需）
└── README.md        # 文档（推荐）
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

        # 注册你的功能
        # api.register_provider(...)
        # api.register_startup_hook(...)
        # api.register_shutdown_hook(...)

        logger.info("✓ My plugin registered")


# Export plugin instance
plugin = MyPlugin()
```

## 使用示例

### 示例 1：添加自定义 Provider

假设你想接入一个企业内部的 LLM 服务。

#### 1. 创建插件目录

```bash
mkdir my-llm-provider
cd my-llm-provider
```

#### 2. 创建 plugin.json

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

#### 3. 创建 provider.py

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

#### 4. 创建 plugin.py

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

#### 5. 安装和使用

```bash
# 安装插件
copaw plugin install my-llm-provider

# 启动 CoPaw
copaw app

# 在 Web UI 中配置 API Key
# 然后就可以使用新的 Provider 了
```

### 示例 2：添加启动钩子

假设你想在 CoPaw 启动时初始化一个监控服务。

#### 1. 创建插件

```bash
mkdir monitoring-hook
cd monitoring-hook
```

#### 2. 创建 plugin.json

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

#### 3. 创建 plugin.py

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

                # 初始化你的监控服务
                # from my_monitoring import init_monitoring
                # init_monitoring(app_name="CoPaw")

                logger.info("✓ Monitoring initialized successfully")

            except Exception as e:
                logger.error(
                    f"Failed to initialize monitoring: {e}",
                    exc_info=True,
                )

        # 注册启动钩子（priority=0 表示最高优先级）
        api.register_startup_hook(
            hook_name="monitoring_init",
            callback=startup_hook,
            priority=0,
        )

        logger.info("✓ Monitoring hook registered")


# Export plugin instance
plugin = MonitoringHookPlugin()
```

#### 4. 安装

```bash
copaw plugin install monitoring-hook
copaw app
```

### 示例 3：添加自定义命令

假设你想添加一个 `/status` 命令来查看系统状态。

#### 1. 创建插件

```bash
mkdir status-command
cd status-command
```

#### 2. 创建 plugin.json

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

#### 3. 创建 query_rewriter.py

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
        return """请帮我检查系统状态，包括：

1. 当前使用的模型和 Provider
2. 内存使用情况
3. 最近的对话数量
4. 插件加载情况

请用清晰的格式展示这些信息。"""
```

#### 4. 创建 plugin.py

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

#### 5. 安装和使用

```bash
copaw plugin install status-command
copaw app

# 使用命令
/status
```

## 依赖管理

### 使用 requirements.txt

如果插件需要额外的 Python 包，创建 `requirements.txt`：

```
httpx>=0.24.0
pydantic>=2.0.0
```

插件安装时会自动安装依赖。

### 使用自定义 PyPI 源

```
--index-url https://custom-pypi.example.com/simple
my-package>=1.0.0
```

## 最佳实践

### 1. 命名规范

- **插件 ID**：使用小写字母和连字符，如 `my-plugin`
- **版本号**：遵循语义化版本（1.0.0, 1.1.0, 2.0.0）

### 2. 错误处理

钩子回调应该优雅处理错误，避免阻塞应用启动：

```python
def startup_hook():
    try:
        # 你的初始化代码
        pass
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        # 不要 raise，让应用继续启动
```

### 3. 日志记录

使用 Python logging 记录插件行为：

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Plugin loaded")
logger.debug("Debug information")
logger.error("Error occurred", exc_info=True)
```

### 4. 文档

提供清晰的 README.md 文档，包括：

- 功能说明
- 安装步骤
- 使用示例
- 配置说明
- 故障排查

## 优先级系统

### Hook 优先级

钩子按优先级顺序执行：

- **优先级值越低，执行越早**
- Priority 0 = 最高优先级（最先执行）
- Priority 100 = 默认优先级
- Priority 200 = 低优先级（最后执行）

**示例**：

```python
# 最先执行
api.register_startup_hook("early", callback, priority=0)

# 默认顺序
api.register_startup_hook("normal", callback, priority=100)

# 最后执行
api.register_startup_hook("late", callback, priority=200)
```

## 故障排查

### 插件未加载

1. 检查插件是否已安装：

   ```bash
   copaw plugin list
   ```

2. 查看 CoPaw 日志：

   ```bash
   tail -f ~/.copaw/logs/copaw.log | grep -i plugin
   ```

3. 验证插件清单格式：
   ```bash
   copaw plugin info <plugin-id>
   ```

### 依赖安装失败

1. 检查 `requirements.txt` 格式
2. 手动安装依赖测试：
   ```bash
   pip install -r /path/to/plugin/requirements.txt
   ```
3. 使用 `--force` 重新安装插件

### Provider 未显示

1. 确认插件已安装并重启 CoPaw
2. 检查 Web UI 的模型管理页面
3. 查看日志中的 provider 注册信息

### 命令未响应

1. 确认插件已安装
2. 检查 startup hook 是否成功执行
3. 查看日志中的 patch 信息

## 安全注意事项

1. **只安装可信插件**：插件代码会在 CoPaw 进程中执行
2. **检查依赖**：确保插件依赖来自可信源
3. **审查代码**：安装前审查插件源代码
4. **离线操作**：插件安装/卸载需要 CoPaw 离线

## PluginApi 参考

### register_provider

注册自定义 LLM Provider。

```python
api.register_provider(
    provider_id: str,          # Provider 唯一标识符
    provider_class: Type,      # Provider 类
    label: str,                # 显示名称
    base_url: str,             # API base URL
    metadata: Dict[str, Any],  # 额外元数据
)
```

### register_startup_hook

注册启动钩子。

```python
api.register_startup_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

### register_shutdown_hook

注册关闭钩子。

```python
api.register_shutdown_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

## 高级功能

### Monkey Patch

对于需要修改 CoPaw 行为的插件（如自定义命令），可以使用 monkey patch：

```python
def _patch_query_handler(self):
    """Patch AgentRunner to intercept queries."""
    from copaw.app.runner.runner import AgentRunner

    original_handler = AgentRunner.query_handler

    async def patched_handler(self, msgs, request=None, **kwargs):
        # 你的自定义逻辑
        # 修改 msgs 或添加额外处理

        # 调用原始 handler
        async for result in original_handler(self, msgs, request, **kwargs):
            yield result

    AgentRunner.query_handler = patched_handler
```

### 访问运行时信息

通过 `api.runtime` 访问运行时信息：

```python
def my_hook():
    # 访问 provider manager
    provider_manager = api.runtime.provider_manager

    # 获取所有 providers
    providers = provider_manager.list_provider_info()
```

## 插件打包

将插件打包为 ZIP 文件以便分发：

```bash
cd /path/to/plugins
zip -r my-plugin-1.0.0.zip my-plugin/
```

用户可以通过 URL 安装：

```bash
copaw plugin install https://example.com/my-plugin-1.0.0.zip
```

## 常见问题

### Q: 插件可以访问哪些 CoPaw API？

A: 插件通过 `PluginApi` 访问核心功能，包括：

- Provider 注册
- Hook 注册
- Runtime helpers（`provider_manager` 等）

### Q: 插件可以修改 CoPaw 的核心行为吗？

A: 可以，通过 monkey patch 或 hook 机制。但请谨慎使用，确保不会破坏核心功能。

### Q: 插件之间会冲突吗？

A: 如果多个插件注册相同的 `provider_id` 或 `command_name`，后注册的会覆盖先注册的。建议使用唯一的 ID。
