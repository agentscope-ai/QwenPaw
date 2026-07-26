# 插件系统迁移指南

QwenPaw 新版保留了旧版插件系统的大部分公开 API。旧版公开 API 多数签名保持兼容，可以继续调用；但如果插件依赖 agent 状态、workspace 信息、runtime helper、工具配置结构或前端页面结构，仍需要在新版环境中验证实际行为。

## 适用范围

本文档适用于以下插件：

- 基于旧版官方文档开发的后端插件
- 通过 `PluginApi` 注册 provider、hook、tool、HTTP API 或 command 的插件
- 使用 `window.QwenPaw.*` Host SDK 的前端插件

## 迁移前检查

后端插件入口仍然需要导出 `plugin` 实例：

```python
class MyPlugin:
    def register(self, api):
        ...


plugin = MyPlugin()
```

新版校验逻辑要求入口模块导出 `plugin` 实例。只导出 `Plugin` 类、不创建实例的插件需要补充实例。

## 检查插件清单 `plugin.json`

### 版本兼容声明

旧版插件清单通常使用 `min_version`：

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "general",
  "entry": {
    "backend": "plugin.py"
  },
  "min_version": "1.1.10"
}
```

在旧版中，`min_version` 主要是清单元数据，加载器不会用它阻止插件加载。新版会在导入插件前检查版本兼容性。不兼容的插件会被记录为 `enabled=false`，并且不会执行后端入口的 `register()`。

新版推荐使用 `qwenpaw_version`：

```json
{
  "qwenpaw_version": {
    "min": "2.0.0",
    "max": "2.1.0"
  }
}
```

版本区间使用 `>= min, < max` 语义。省略 `max` 时，新版会从 `min` 推导到下一个 minor 版本。

| 写法              | 等价区间           |
| ----------------- | ------------------ |
| `"min": "2.0.0"`  | `>=2.0.0, <2.1.0`  |
| `"min": "1.1.10"` | `>=1.1.10, <1.2.0` |

因此，把旧版插件原样放到新版时，如果只保留 `"min_version": "1.1.10"`，新版会将它解释为 `>=1.1.10, <1.2.0`，在 QwenPaw 2.0.x 下会被判定为不兼容。

### 清单字段说明

| 字段                                                                                                                | 类型     | 旧版                   | 新版                                                  | 迁移建议                         |
| ------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------- | ----------------------------------------------------- | -------------------------------- |
| `qwenpaw_version`                                                                                                   | `object` | 未定义，会被忽略       | 新增，推荐使用                                        | 新版插件建议增加该字段           |
| `qwenpaw_version.min`                                                                                               | `string` | 未定义                 | 最低兼容 QwenPaw 版本，包含该版本                     | 写为实际验证过的最低新版版本     |
| `qwenpaw_version.max`                                                                                               | `string` | 未定义                 | 最高兼容 QwenPaw 版本，不包含该版本                   | 建议显式填写                     |
| `min_version`                                                                                                       | `string` | 支持，但不用于加载拦截 | 遗留字段，仅在没有 `qwenpaw_version` 时参与兼容性判断 | 需要兼容旧版时可以保留           |
| `max_version`                                                                                                       | `string` | 未定义                 | 遗留字段，配合 `min_version` 使用                     | 仅旧清单兼容场景使用             |
| `id`、`version`、`name`、`type`、`description`、`author`、`entry.backend`、`entry.frontend`、`dependencies`、`meta` | —        | 支持                   | 继续支持                                              | 保持不变                         |
| `entry_point`                                                                                                       | `string` | 遗留字段               | 继续兼容                                              | 新插件仍建议使用 `entry.backend` |

如果同一份插件需要同时兼容旧版和新版，可以同时保留旧字段和新字段：

```json
{
  "min_version": "1.1.10",
  "qwenpaw_version": {
    "min": "2.0.0",
    "max": "2.1.0"
  }
}
```

旧版会忽略未知的 `qwenpaw_version` 字段。新版会优先读取 `qwenpaw_version`，只有该字段不存在时才回退到 `min_version` / `max_version`。

## 检查后端插件代码

### 公开 API 兼容性

以下旧版 API 在新版中签名保持兼容，可以继续调用：

| API                                                                                 | 用途                     | 迁移建议                                              |
| ----------------------------------------------------------------------------------- | ------------------------ | ----------------------------------------------------- |
| `register_provider(provider_id, provider_class, label="", base_url="", **metadata)` | 注册自定义 LLM Provider  | 接口保持兼容，需验证 provider 配置和模型列表展示      |
| `register_startup_hook(hook_name, callback, priority=100)`                          | 注册启动 hook            | 接口保持兼容，需验证启动时机和依赖对象                |
| `register_shutdown_hook(hook_name, callback, priority=100)`                         | 注册关闭 hook            | 接口保持兼容，需验证清理逻辑                          |
| `register_uninstall_hook(hook_name, callback, priority=100)`                        | 注册卸载 hook            | 接口保持兼容，需验证卸载流程                          |
| `register_workspace_created_hook(hook_name, callback, priority=100)`                | 注册 workspace 创建 hook | 接口保持兼容，需验证新版 workspace 信息结构           |
| `register_http_router(router, *, prefix, tags=None)`                                | 注册 FastAPI router      | 接口保持兼容，需验证路由、鉴权和 OpenAPI 展示         |
| `register_control_command(handler, priority_level=10)`                              | 注册控制命令处理器       | 接口保持兼容；新插件可评估 `register_slash_command()` |
| `register_tool(tool_name, tool_func, description="", icon="🔧", enabled=False)`     | 注册 Agent 工具          | 接口保持兼容，需验证工具配置、启用状态和 agent 调用   |
| `register_skill_provider(skills_dir, *, enabled_by_default=True, channels=None)`    | 注册插件技能目录         | 签名保持兼容，默认值写入行为有变化                    |
| `get_tool_config(tool_name, agent_id)`                                              | 读取工具配置             | 接口保持兼容，需验证 agent id 来源                    |
| `set_tool_config(tool_name, agent_id, config)`                                      | 保存工具配置             | 接口保持兼容，需验证配置落盘                          |
| `api.runtime`                                                                       | 访问运行时 helper        | 属性保留，内部 helper 能力需按新版验证                |
| `get_tool_config(tool_name)`                                                        | 模块级工具配置读取       | 接口保持兼容，需验证调用上下文                        |

### `register_prompt_section`

这是新版中唯一发生**参数顺序调整**的 API。如果插件使用了此方法，需要检查调用写法。

旧版签名（`provider` 是第 2 个位置参数，`after` 有默认值）：

```python
def register_prompt_section(
    self,
    name: str,
    provider: Callable,
    *,
    after: str = "workspace",
    agent_id: Optional[str] = None,
) -> None: ...
```

新版签名（`after` 移到第 2 个位置，且为必填参数；新增 `priority` 和 `condition`）：

```python
def register_prompt_section(
    self,
    name: str,
    after: str,
    provider: Callable,
    *,
    priority: int = 100,
    condition: Optional[Callable] = None,
    agent_id: Optional[str] = None,
) -> None: ...
```

参数变化如下：

| 参数        | 旧版                           | 新版                      | 迁移建议                                        |
| ----------- | ------------------------------ | ------------------------- | ----------------------------------------------- |
| `name`      | 第 1 个位置参数                | 第 1 个位置参数           | 保持不变                                        |
| `provider`  | 第 2 个位置参数                | 第 3 个位置参数           | 不要继续作为第 2 个位置参数传入，改为关键字参数 |
| `after`     | 关键字参数，默认 `"workspace"` | 第 2 个必填参数，无默认值 | 显式传入 `after=`                               |
| `priority`  | 不支持                         | 新增，可选，默认 `100`    | 需要控制同一 anchor 内顺序时使用                |
| `condition` | 不支持                         | 新增，可选                | 需要按条件注入提示词时使用                      |
| `agent_id`  | 可选关键字参数                 | 可选关键字参数            | 保持不变                                        |

`after` 的合法值为 `"workspace"`、`"multimodal"`、`"env_context"`。

推荐写法（统一使用关键字参数）：

```python
api.register_prompt_section(
    name="my.section",
    after="workspace",
    provider=build_prompt,
)
```

不要继续使用旧版中常见的位置参数写法：

```python
# 错误：新版第 2 个位置参数是 after，传入 provider 函数会导致运行时报错
api.register_prompt_section("my.section", build_prompt)
```

如果需要按条件注入提示词，可以使用新增的 `condition`：

```python
api.register_prompt_section(
    name="my.section",
    after="workspace",
    provider=build_prompt,
    condition=lambda agent: agent.config.mode == "coding",
    priority=50,
)
```

### 新版新增和重点变更 API

以下是新版新增的 API。旧版插件不需要为了迁移主动改用它们，新插件可以按需选用。`register_prompt_section()` 的签名变化及迁移写法见上文。

#### register_middleware

注册 AgentScope middleware 工厂。工厂函数会在每次构建 agent 时被调用，返回 `MiddlewareBase` 实例或 `None`。

```python
api.register_middleware(
    middleware_factory: Callable,  # (ctx, agent_config) -> MiddlewareBase | None
    *,
    priority: int = 100,          # 优先级，越低越靠外层
)
```

#### register_slash_command

注册 workspace 级 `/command`。命令会被注册到每个已有 workspace，并在新 workspace 创建时继续注册。

```python
api.register_slash_command(
    name: str,                    # 命令名，不包含开头的 "/"
    handler: Callable,            # async (ctx, args) -> Msg | None
    *,
    aliases: tuple = (),          # 命令别名
    category: str = "plugin",     # 命令分类
    help_text: str = "",          # 帮助文案
    metadata: Optional[dict] = None,  # 额外元数据
)
```

#### register_mode

注册插件提供的 `AgentMode`。模式会在启动时注册到已有 workspace，并在新 workspace 创建时注册。

```python
api.register_mode(
    mode_cls: Type,  # AgentMode 子类，需提供唯一的 name
)
```

#### register_runtime_hook

注册运行时阶段 hook。hook 对象需要提供 `phase`、`name` 和 `run()`。

```python
api.register_runtime_hook(
    hook: HookBase,  # runtime hook 实例
)
```

可用阶段包括：

```text
PRE_DISPATCH
POST_DISPATCH
PRE_AGENT_BUILD
POST_AGENT_BUILD
PRE_EXECUTE
POST_RESPONSE
ON_ERROR
FINALLY
```

#### register_agent_stop_handler

注册 agent 停止决策处理器。处理器可以参与判断 agent 是否应该停止，或返回继续执行所需的信息。

```python
api.register_agent_stop_handler(
    handler: Callable,       # async (ctx) -> StopHandlerResult
    *,
    priority: int = 100,     # 优先级，越低越早执行
    name: str = "",         # 调试用名称
)
```

#### unregister_skill_provider

撤销当前插件通过 `register_skill_provider()` 注册的技能提供能力，并清理该插件来源的技能。

```python
api.unregister_skill_provider()
```

## Skill Provider 行为

`register_skill_provider()` 签名不变。新版调整了技能默认值的写入策略：

| 项目                  | 旧版                                   | 新版                             | 影响                                               |
| --------------------- | -------------------------------------- | -------------------------------- | -------------------------------------------------- |
| `enabled` 默认值写入  | 每次安装插件技能时写入插件声明的默认值 | 只在技能第一次被该插件接管时写入 | 用户手动关闭技能后，不会在后续启动中被插件重新打开 |
| `channels` 默认值写入 | 每次安装插件技能时写入插件声明的默认值 | 只在技能第一次被该插件接管时写入 | 用户手动调整频道后，会保留用户设置                 |
| 卸载清理              | 支持按插件来源清理技能                 | 继续支持                         | 需要验证卸载时技能目录和 manifest 清理结果         |

如果插件依赖"每次启动都重置技能开关"的行为，需要重新评估。

## 检查前端插件代码

新版继续支持已有的 `window.QwenPaw.*` 前端 Host SDK。使用旧版已有前端 API 的插件通常可以直接运行。

| API                                                            | 类型 | 用途                                             | 迁移建议                               |
| -------------------------------------------------------------- | ---- | ------------------------------------------------ | -------------------------------------- |
| `window.QwenPaw.host`                                          | 兼容 | 访问 React、Ant Design、API helper、运行时状态等 | 接口保留，需验证 hook 返回值和状态对象 |
| `window.QwenPaw.menu`                                          | 兼容 | 注册侧边栏菜单                                   | 接口保留，需验证菜单位置和路由         |
| `window.QwenPaw.route`                                         | 兼容 | 注册页面路由                                     | 接口保留，需验证页面加载和卸载         |
| `window.QwenPaw.slot`                                          | 兼容 | 注册 UI 插槽                                     | 接口保留，需验证插槽位置               |
| `window.QwenPaw.chat.requestPayload.add(pluginId, fn, opts?)`  | 新增 | 在聊天请求发送前追加或改写请求体字段             | 需要改写请求体时使用                   |
| `window.QwenPaw.chat.response.set(pluginId, { avatar, nick })` | 新增 | 设置默认 AI 回复卡片的头像和昵称                 | 需要统一回复头像或昵称时使用           |

## 检查依赖安装

`requirements.txt` 的写法不变。新版改进了依赖检测和安装流程：

| 项目                    | 旧版                           | 新版                                                   | 迁移建议                       |
| ----------------------- | ------------------------------ | ------------------------------------------------------ | ------------------------------ |
| `requirements.txt` 格式 | 支持 pip requirements 写法     | 继续支持                                               | 保持不变                       |
| 依赖检测                | 主要依赖 distribution metadata | 结合 distribution metadata 和 import 探测              | 保持不变，重新验证安装日志     |
| 包名与 import 名不一致  | 可能误判未安装                 | 内置常见映射，例如 `pillow` / `PIL`、`pyyaml` / `yaml` | 通常不需要调整                 |
| 并发安装                | 可能多个进程同时安装           | 增加跨进程安装锁                                       | 通常不需要调整                 |
| 桌面打包环境            | 依赖系统执行环境               | 使用内置 Python 运行时和用户可写依赖目录               | 需要在桌面安装包中验证依赖加载 |

通常可以保持原有 `requirements.txt` 写法，但仍建议在新版环境中重新验证依赖安装和导入。

## 检查插件加载和卸载

新版在插件加载失败时会清理已经注册的状态，包括 registry 注册项、插件模块和临时加入的 `sys.path`。卸载插件时也会更完整地清理插件目录导入的模块。

| 项目                       | 旧版               | 新版                              |
| -------------------------- | ------------------ | --------------------------------- |
| 加载失败后的 registry 清理 | 可能残留部分注册项 | 自动清理该插件已注册的状态        |
| 加载失败后的模块清理       | 清理较有限         | 按模块名前缀和插件文件路径清理    |
| 卸载后的模块清理           | 清理较有限         | 更完整清理插件目录导入的模块      |
| `sys.path` 清理            | 清理较有限         | 加载失败和卸载时都会移除插件目录  |
| `.disabled` 目录           | 不支持             | 跳过以 `.disabled` 结尾的插件目录 |

以 `.` 开头的隐藏目录和以 `.disabled` 结尾的目录不会被插件发现流程加载，也不会触发依赖安装。手动修改过 `sys.path` 的插件建议测试安装、卸载和重新安装流程。

## 发布到插件市场

新版插件市场目录会按 QwenPaw 版本过滤插件条目。过滤规则与加载器一致。

| 字段                  | 类型     | 读取优先级 | 说明                                      |
| --------------------- | -------- | ---------- | ----------------------------------------- |
| `qwenpaw_version`     | `object` | 1          | 推荐字段，格式与插件清单一致              |
| `qwenpaw_version.min` | `string` | 1          | 最低兼容 QwenPaw 版本，包含该版本         |
| `qwenpaw_version.max` | `string` | 1          | 最高兼容 QwenPaw 版本，不包含该版本       |
| `min_version`         | `string` | 2          | 旧字段，仅在没有 `qwenpaw_version` 时使用 |
| `max_version`         | `string` | 2          | 旧字段，仅在没有 `qwenpaw_version` 时使用 |
| 无版本约束            | -        | 3          | 会被视为兼容，但发布时不建议省略          |

发布新版插件时，建议插件包内的 `plugin.json` 与市场索引条目使用一致的版本约束。如果旧条目只写了 `"min_version": "1.1.10"`，在 QwenPaw 2.0.x 下可能会被过滤。

## 迁移步骤

1. 更新 `plugin.json`，增加 `qwenpaw_version`，并设置明确的 `max`。
2. 确认后端入口导出了 `plugin = MyPlugin()`。
3. 搜索 `register_prompt_section`，将调用改为关键字参数形式，并显式传入 `after`。
4. 如果插件提供 skill，验证用户手动修改开关后的持久化行为。
5. 在新版环境执行插件安装和校验。
6. 启动 QwenPaw，检查日志中是否有 `is incompatible` 或插件注册失败信息。
7. 如果发布到插件市场，同步更新市场索引中的版本约束。

## 常见问题

### 插件在旧版正常，在新版中没有生效

先检查版本兼容声明。旧插件如果只写了 `min_version`，新版可能会推导出过窄的兼容区间，导致插件被标记为不兼容。可以在服务端日志中搜索 `is incompatible`。

### 公开接口保持兼容，为什么仍然需要测试

插件接口保持兼容只说明方法名和参数仍可调用。插件内部如果依赖 agent 状态、workspace 信息、请求上下文、工具配置结构或前端页面结构，这些运行时对象可能已经变化，因此需要在新版环境中做完整功能验证。

### `register_prompt_section()` 报参数错误

把调用改成关键字参数形式，并显式写出 `after`：

```python
api.register_prompt_section(
    name="my.section",
    after="workspace",
    provider=build_prompt,
)
```

### 同一份插件能否同时支持旧版和新版

可以。插件代码只使用两边都存在的 API，或者在调用新版新增 API 前做版本判断。清单中可以同时保留 `min_version` 和 `qwenpaw_version`：

```json
{
  "min_version": "1.1.10",
  "qwenpaw_version": {
    "min": "2.0.0",
    "max": "2.1.0"
  }
}
```

### 是否需要迁移到 `register_slash_command()`

不需要。`register_control_command()` 在新版中继续可用。只有新插件需要 workspace 级命令注册能力时，才建议使用 `register_slash_command()`。

### 能否省略 `qwenpaw_version.max`

可以，但省略后会自动推导到下一个 minor 版本。若插件已经验证可跨多个 minor 版本运行，建议显式写出更宽的 `max`。
