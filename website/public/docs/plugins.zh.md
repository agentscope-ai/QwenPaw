# 插件开发与公开 SDK

新插件使用 `qwenpaw.plugins` 公共 SDK。宿主通过上下文提供能力，作者无需导入
`qwenpaw.app.*`、内部 Registry 或 Manager。已有 `PluginApi` 插件继续兼容；
本页后半部分单列旧版参考，不把旧接口示例当作新 SDK 的稳定契约。

## 从模板开始

先在独立 Python 环境安装包含 SDK 的 QwenPaw，再导出模板：

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install qwenpaw
```

```bash
python -m qwenpaw.plugins.check --template ./hello-sdk
python -m qwenpaw.plugins.check ./hello-sdk
python -m qwenpaw.plugins.check ./hello-sdk --runtime
```

`--template` 导出与已安装 SDK 配套的可运行插件。默认检查只读源码；
`--runtime` 会执行插件的加载、激活和清理，仅用于可信插件。它不自动调用所有业务
handler，报告中的未覆盖项仍需测试；检查器不是安全沙箱或完整权限审计。

## 声明版本与能力

`hello-sdk/plugin.json`：

```json
{
  "id": "hello-sdk",
  "name": "Hello SDK",
  "version": "1.0.0",
  "entry": { "backend": "main.py" },
  "sdk": { "version": "1.0.0", "capabilities": ["tools", "storage"] }
}
```

`plugin.json.version` 是插件版本，`sdk.version` 是所需的最低 SDK 版本。
宿主仅接受相同主版本且不高于自身版本的声明；未知能力在导入插件前拒绝。
SDK 使用语义版本策略：同主版本保持公开契约兼容，新增接口要求对应的最低版本，
破坏性变化使用新主版本。完整模块与符号清单由 `qwenpaw.plugins.compliance.PUBLIC_API`
给出；`API_EXPORTS` 标明版本和稳定性。能被 Python 导入不等于属于稳定 SDK。

没有 `sdk` 声明的插件仍使用旧 `PluginApi`，不会因为升级宿主自动迁移。
`PluginApi`、`PluginLoader`、`PluginRegistry`、`PluginLifecycle` 的历史导出保留兼容，
新插件不能把它们或下划线属性作为公开 SDK 使用。

## 编写工具

将下面代码保存为 `hello-sdk/main.py`：

```python
from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.tools import ToolContext, ToolResult, ToolSpec

async def greet(call: ToolContext, arguments: dict) -> ToolResult:
    await call.storage.awrite_json("last-greeting.json", arguments["name"])
    return ToolResult.text(f"Hello {arguments['name']}")

class Plugin:
    def register(self, context: PluginContext) -> None:
        context.register_tool(ToolSpec(
            name="hello_sdk",
            description="Greet someone",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            handler=greet,
            enabled=True,
        ))

plugin = Plugin()
```

`register()` 只声明贡献；连接和后台任务放在 `context.on_activate(callback)`，
通过 `context.resources` 管理。调用上下文的配置、日志、模型、存储均由宿主提供。

## 异步存储与资源归属

异步 handler 使用 `await storage.aread_bytes/awrite_bytes/aread_json/awrite_json/adelete`
以及 `await media.awrite(...)`。同步 `read_json/write_json` 等方法保留，适用于同步
handler 或明确在线程中执行的代码；在异步函数中直接调用同步文件操作仍会阻塞事件循环。

SDK 将完整文件操作交给工作线程。取消等待不代表线程已经退出；重载必须等待真实操作
结束，超时则报忙并保留归属，不会在旧线程仍写入时宣布换代成功。单次写入使用临时文件
和原子替换，但分开的“读→修改→写”不构成原子事务。并发计数需要用同一工作区共享的
`asyncio.Lock` 保护完整流程，不能只锁写入，也不能在每次调用时新建锁。下方最小工具
展示了这种写法；锁随插件实例重新创建，持久数据则在重载后保留。

`PluginContext.storage/media` 是插件共享数据；工具等调用上下文默认按工作区隔离，
App 和 Channel 还包含相应调用身份。工作区使用真实 ID，不根据目录名推断。
媒体写入返回公开 `Attachment`；路径不能越出当前插件的数据目录。正常重载保留持久数据。

任务、连接、线程和进程应交给 `context.resources` 托管。SDK 只能保证受管资源的生命周期，
不能替作者停止未登记的全局线程、第三方服务或任意外部资源。

## 只用 SDK 开发 Channel 和 PawApp

渠道清单声明 `channels` 能力。以下后端仅记录发送事件，用于展示协议，实际平台发送和
连接由插件实现；无需继承宿主的 `BaseChannel`：

```python
from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.channels import ChannelContext, ChannelSpec, OutgoingMessage

class LogChannel:
    async def start(self, context: ChannelContext) -> None:
        context.logger.info("Channel started")

    async def send(self, context: ChannelContext, message: OutgoingMessage) -> None:
        context.logger.info("Outgoing message", fields={"target": message.target})

    async def stop(self, context: ChannelContext) -> bool:
        return True

class Plugin:
    def register(self, context: PluginContext) -> None:
        context.register_channel(ChannelSpec("log_channel", "Log channel", LogChannel))

plugin = Plugin()
```

平台回调通过 `context.receive(ChannelMessage(...))` 投递入站消息。宿主管理工作区
队列、访问检查与模型调用；平台线程应将回调转交给启动时的事件循环。连接、任务交给
资源作用域，`stop()` 只有确实停止才返回 `True`。流式渠道声明 `streaming=True` 并实现
`on_stream`；需要任务结束通知时实现 `on_run`，中断重载仍等待已有请求的结束通知。

应用清单声明 `apps` 能力，可以直接使用公开路由和上下文：

```python
from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.apps import PawApp, AppContext, HttpRequest

app = PawApp("Notes", app_id="notes")

@app.route("/status")
async def status(context: AppContext, request: HttpRequest):
    return {"workspace_id": context.workspace_id, "ready": True}

class Plugin:
    def register(self, context: PluginContext) -> None:
        app.register(context)

plugin = Plugin()
```

处理器只接收公开 `AppContext/HttpRequest`；模型、聊天、任务、审批和跨工作区委托使用
上下文方法。需要宿主标准前端能力时调用 `app.enable_standard_capabilities()`，再注册应用。

## 独立测试与安全重载

测试宿主运行真实加载和生命周期路径，不需要作者手工构造内部 Registry：

```python
import asyncio
import tempfile
from pathlib import Path
from qwenpaw.plugins import StaleContextError
from qwenpaw.plugins.testing import PluginTestHost

async def main():
    with tempfile.TemporaryDirectory() as directory:
        async with PluginTestHost(Path(directory)) as host:
            old = await host.load(Path("hello-sdk"))
            result = await host.call_tool("hello_sdk", {"name": "SDK"})
            assert not result.is_error
            assert (await host.reload(old.plugin_id)).ok
            try:
                await old.storage.awrite_json("stale.json", True)
            except StaleContextError:
                pass
            else:
                raise AssertionError("Old context remained writable")
            result = await host.unload(old.plugin_id)
            assert result.clean and result.quiescent

asyncio.run(main())
```

`PluginTestHost.load()` 加载作者目录；需要验证安装、更新和卸载事务时，使用
`install/update_config/set_enabled/uninstall`，并检查返回结果的 `ok/clean/quiescent/errors`。
`inject_failure("before_commit")` 与 `inject_failure("post_commit_cleanup")` 可测试失败恢复。
测试渠道还需 `start_channel`；未配置模型或测试模型时，不要假定渠道自动产生 AI 回复。

普通重载遇到在途调用会抛 `PluginBusyError`。明确需要停止任务时使用
`reload(plugin_id, interrupt_tasks=True)`；超时或资源未释放仍拒绝换代。
故障解除后可通过公开生命周期操作重试。旧上下文不能写入或注册新一代资源。

## 能力与公开模块

| 能力                         | 公开入口                                                             |
| ---------------------------- | -------------------------------------------------------------------- |
| 声明与版本                   | `PluginContext`、`SDK_VERSION`、`SDK_CAPABILITIES`                   |
| 工具与配置字段               | `qwenpaw.plugins.tools`                                              |
| 配置、持久数据、媒体         | `qwenpaw.plugins.storage`，实例由上下文提供                          |
| 日志、已配置模型调用         | `qwenpaw.plugins.logging`、`qwenpaw.plugins.models`                  |
| 消息、附件、运行与审批观察   | `qwenpaw.plugins.messages`、`qwenpaw.plugins.events`                 |
| 命令、钩子、模式、提示词     | `commands`、`hooks`、`modes`、`prompts`                              |
| 渠道、应用                   | `channels`、`apps`                                                   |
| 模型提供方、记忆、市场、技能 | `providers`、`memory`、`markets`、`skills`                           |
| 资源、结果、测试             | `resources`、`results`、`testing`                                    |
| 异常                         | 从 `qwenpaw.plugins` 导入 `SDKError`、`StaleContextError` 等公开异常 |

后六行模块均位于 `qwenpaw.plugins` 下，具体公开符号以白名单为准。

前端 SDK 随 QwenPaw 分发，使用 `python -m qwenpaw.plugins.check --frontend ./frontend-sdk`
导出，再从该目录安装 npm 包 `@qwenpaw/plugin-sdk`。包提供运行入口和类型声明；
不要复制宿主内部类型。使用后端任务等可选能力前先查询能力，不能仅凭前端包版本假定宿主支持。

## 安装与验收范围

```bash
qwenpaw plugin install ./hello-sdk
qwenpaw plugin list
qwenpaw plugin info hello-sdk
qwenpaw plugin uninstall hello-sdk
```

作者应验证首次安装、保留数据的更新、失败恢复和卸载，并在声明支持的平台运行这些流程。
路径单测或 Mac 上的通过不等于 Windows 原生验收；没有对应环境时应记录未验证。
SDK 检查与测试宿主也不代替真实 IM 平台、桌面窗口或外部模型的集成验证。

## SDK 1.x 详细契约

以下是公开能力、身份和生命周期的完整补充说明。

新插件显式声明 `plugin.json.sdk` 后，Loader 才传入 `PluginContext`。
未声明的插件仍传原 `PluginApi`，包括今后新安装的旧格式插件。
SDK 检查不收紧旧 manifest 的宿主版本规则，也不自动迁移或禁用旧插件。

```json
{
  "id": "hello-sdk",
  "name": "Hello SDK",
  "version": "1.0.0",
  "entry": { "backend": "plugin.py" },
  "sdk": { "version": "1.0.0", "capabilities": ["tools", "storage"] }
}
```

请沿用宿主原 manifest 的其余必需字段与入口结构。SDK 版本采用语义版本；
同 major 且不高于宿主版本才兼容，未知能力在执行模块代码前拒绝。
显式 SDK 的 ID 只能含字母、数字、下划线或连字符，首字符须为字母或数字。

### 最小工具

```python
import asyncio
from collections import defaultdict

from qwenpaw.plugins.tools import ToolSpec, ToolResult

class Plugin:
    def register(self, ctx):
        locks = defaultdict(asyncio.Lock)

        async def hello(call, arguments):
            async with locks[call.workspace_id]:
                count = await call.storage.aread_json("count.json", 0) + 1
                await call.storage.awrite_json("count.json", count)
            return ToolResult.text(f"Hello {arguments['name']} ({count})")

        ctx.register_tool(ToolSpec(
            name="hello_sdk", description="Greet someone", handler=hello,
            input_schema={"type": "object", "properties": {
                "name": {"type": "string"}}, "required": ["name"],
                "additionalProperties": False},
            enabled=True,
        ))

plugin = Plugin()
```

`register()` 只声明贡献。连接、线程和后台任务放在 `ctx.on_activate(callback)`
或 Channel/Memory 的 `start(context)`，并使用 `context.resources` 托管。
工具、命令等支持同步函数的业务处理器由宿主在线程执行；取消 coroutine 不代表线程已退出。
`register/on_activate` 不保证线程卸载，不应直接执行阻塞工作；异步激活使用可等待的存储接口和受管资源。

### 公共接口与稳定性

`qwenpaw.plugins.compliance.PUBLIC_API` 是 **模块和符号** 的精确清单。
`API_EXPORTS` 为每个符号列出 `module/symbol/since/stability`；兼容入口单独标注。
以下模块的列出类型属于 SDK 1.x 稳定契约；以下表格不能解释为允许模块所有属性。

| 能力       | 公开声明                                                                          | 实际接入                                                          |
| ---------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 插件       | `Plugin`, `PluginContext`                                                         | Loader / Lifecycle                                                |
| 工具       | `tools.ToolSpec`, `ToolContext`, `ToolResult`, `ToolEvent`                        | 原工具注册、JSON schema、治理、真实 FunctionTool                  |
| 消息       | `messages.Message`, `ContentBlock`, `Attachment`                                  | AgentScope 转换，未知块明确拒绝                                   |
| 命令       | `commands.CommandSpec`, `CommandContext`, `CommandResult`                         | Workspace SlashCommandRegistry                                    |
| 钩子       | `hooks.HookSpec`, `HookPhase`, `HookResult`, `ContextInjection`                   | 原 Runtime 各阶段                                                 |
| 模式       | `modes.ModeSpec`, `ModeContext`                                                   | 每工作区 AgentMode 与工具模式过滤                                 |
| 日志       | `logging.PluginLogger`                                                            | 宿主日志，固定插件及调用身份与独立作者字段                        |
| 模型调用   | `models.ModelService`                                                             | 当前工作区已配置模型，一次请求，沿原 factory/formatter/重试与计量 |
| 模型提供方 | `providers.ProviderSpec`, `ModelInfo`, `ModelRequest`, `ModelChunk`, `ModelUsage` | ProviderManager / model_factory、formatter、token 计量与重试      |
| 记忆       | `memory.MemorySpec`, `MemoryBackend`, `MemoryContext`, `MemoryTask`               | 原 BaseMemoryManager / ServiceManager / shared worker             |
| 市场       | `markets.MarketSpec`, `SearchPage`, `MarketResult`, `SkillBundle`, `Availability` | 原 Market 搜索及 Hub 安装/扫描                                    |
| 技能       | `skills.SkillSpec`                                                                | 原技能投影、inventory、三方合并                                   |
| 提示词     | `prompts.PromptSpec`                                                              | PromptManager，真实 priority 排序                                 |
| 渠道       | `channels.ChannelSpec`, `ChannelBackend`, `ChannelMessage`, `OutgoingMessage`     | 原 ChannelManager 队列、ACL、TaskTracker、Runtime                 |
| 应用       | `apps.PawApp`, `AppContext`, HTTP/流/WS DTO                                       | 原 PawApp 聚合、身份与标准能力路由                                |
| 观察       | `events.EventSubscription`, `RunEvent`, `ApprovalEvent`, `SubscriptionGap`        | 真实 Workspace.stream_query 和审批状态变更                        |
| 资源       | `resources.ResourceScope`, `Registration`, `ResourceOwner`                        | 原 custody 及生命周期清理账本                                     |
| 数据       | `storage.PluginConfig`, `PluginStorage`, `MediaStore`                             | 所有权限定的持久配置/数据/实际文件预览                            |
| 测试       | `testing.PluginTestHost`、公开测试结果类型                                        | 真实 Loader / Lifecycle / Workspace / 治理与服务                  |

根模块原有 `PluginApi/PluginLoader/PluginRegistry/PluginLifecycle` 导出仍保留，
但属于 **legacy 兼容**，不进入新 SDK 白名单。`qwenpaw.pawapp.PawApp.sdk(...)`
是明确的新契约工厂，返回与 `qwenpaw.plugins.apps.PawApp` 相同的构建器；原
`PawApp(...)` 构造、`get_ctx` 和旧 `PawAppContext` 保持兼容行为，后两者不属于新 SDK。
下划线模块/属性、Workspace、Agent、Registry 以及随意替换宿主方法均不属于公开契约。

### 上下文日志与已配置模型

`PluginContext.logger` 可用于注册、激活和清理；Tool、Command、Hook 及派生的
App、Channel、Memory 等调用上下文同时提供 `logger` 和 `models`。两个类型从
`qwenpaw.plugins.logging`、`qwenpaw.plugins.models` 导入，由宿主提供实例。
manifest 可声明 `logging`、`models` 能力，以便旧宿主在加载前报告不支持。

```python
from qwenpaw.plugins.messages import Message, ContentBlock

async def summarize(call, text):
    call.logger.info("开始摘要", fields={"characters": len(text)})
    answer = await call.models.complete(
        (Message("user", (ContentBlock(text=text),)),),
        options={"temperature": 0.2}, timeout=20,
    )
    return "".join(block.text for block in answer.content if block.type == "text")
```

日志提供 `debug/info/warning/error/exception(message, *, fields=None)`；
`exception` 附带当前异常。`LogRecord.sdk_context` 的插件 ID、代次、工作区、
会话以及 `invocation_id` 由宿主绑定；后者是资源作用域身份，不冒充业务请求 ID。
App 另含 `app_id/user_id/channel`，Channel 另含 `channel_name`。
作者 JSON 字段放在独立的 `sdk_fields`，同名字段不能覆盖归属。没有真实身份的
字段不捏造。清理中仍可记日志；代次被替代后拒绝旧日志对象。
终端与日志文件同时输出这两组 JSON 字段；普通宿主日志格式不变。

`models.complete(messages, *, provider_id=None, model_id=None, tools=(),
tool_choice=None, options=None, timeout=None)` 返回完整的 `ModelChunk`，
`is_last=True`。`models.stream(...)` 返回可 `aclose()` 的异步生成器；每块正文
都是增量，最终块带 usage、完成原因及元数据，不重复宿主的累计正文。
`complete` 使用生产模型的块合并规则，保留文本、thinking、工具调用及支持的媒体；
块元数据和媒体预览引用沿同一消息编码保留；同一块 ID 的元数据或预览引用冲突
会报 `SDKError`，不会让合并静默覆盖作者字段。
工具调用仅作为数据返回，不自动执行工具，也不启动一轮 Agent 对话。

默认模型沿绑定工作区的宿主选择规则；显式选择须同时给出已配置且启用的
`provider_id/model_id`。没有任意工作区参数，顶层 `PluginContext` 不提供 models。
同步回调可记日志；模型是异步接口，应在异步回调中 `await`，不提供另起事件循环的
同步捷径。消息、工具声明和 `ModelToolChoice` 沿宿主 formatter 处理；工具选择支持
`auto/none/required/具体工具名`。生成选项只接受 `temperature/top_p/max_tokens/
max_completion_tokens/stop/seed/frequency_penalty/presence_penalty/parallel_tool_calls/
reasoning_effort/thinking_budget/enable_thinking`；实际模型仍可拒绝不支持的选项。
未知选项及试图覆盖模型、输入、地址或凭据的选项报 `SDKError`，不静默忽略。

模型请求的截止时间取调用上下文 deadline 与本次 timeout 的较早者，超时报
`SDKError`；取消仍传播取消。提前停止消费时使用 `try/finally: await stream.aclose()`。
回调退出也会关闭其模型生产任务；作用域已结束、取消或代次失效后不能开始新请求。
本次创建的模型客户端、原生源流、Retry 延后清理和 SDK Provider 后代都归请求所有；
尚未停止的线程/流或失败清理保持账本与忙碌状态，不能以外层返回代表已排空。
支持原生 OpenAI Chat/Responses、Anthropic、Gemini、DashScope（含沿这些模型实现的
服务）及 SDK Provider，复用现有 TokenRecording/Retry/Fallback 包装。其他自定义
旧 Provider 工厂没有已知资源归属适配时在创建模型前明确拒绝；不会擅自关闭共享
Provider/Manager。备用槽仍遵循宿主规则：不可用的槽被跳过，健康主模型继续工作。
已知工厂返回模型后立即登记请求归属，因此后续 formatter 或备用槽构造失败也会
关闭已创建的客户端。普通 Agent 构建不启用这条请求级资源登记。

### 消息、错误和流

`Message.role` 为 `user/assistant/system`。工具调用/结果是 assistant 消息中的
`tool_call/tool_result` 块。内容块支持文本、附件、thinking、hint 和工具调用/结果；
额外 JSON 属性保留在 `attributes`，元数据保留在 `metadata`。未知块报 `SDKError`。
媒体 `Attachment.preview_url` 随消息和工具结果保留；内部转换封套返回公开类型时
会解开。作者元数据中即使存在同名字段，其原值也会保留并恢复。
各类 `ContentBlock.metadata` 也随 JSON 历史保存和恢复。多个附件复用同一个 ID
却提供不同预览地址，或同类型同 ID 的块提供冲突元数据，会报 `SDKError`；
工具调用和工具结果共用关联 ID 不受影响。
宿主会合并工具结果中相邻的文本块；这些块（包括流式分片）的元数据必须一致，
否则 SDK 明确报错，避免合并后丢字段。普通空元数据文本分片不受影响。
工具的 `ToolResult` 只接收文本和图像/音频/视频/文件附件，不能无声丢弃其它块。

模型每个 `ModelChunk.content` 都是新增内容，包含最后一块的内容；最后一块可为空，
但必须有且仅有一个 `is_last=True`。SDK 为宿主生成正文 delta 和完整累计终态，
`PluginTestHost.create_model().stream()` 再归一为公开增量，避免作者收到重复内容。
App 的聊天/任务流、TestHost 的聊天/工具流和 TestModel 流均返回
`AsyncGenerator[T, None]`；提前退出时应在 `finally` 中 `await stream.aclose()`。
终态后继续产出和无终态结束均报错；`usage` 和 finish reason 保留。
模型发现与连接检查执行传入的 timeout，并向回调提供真实 `deadline`；超时
抛 Python 标准 `TimeoutError`，同步工作仍按实际退出状态保留归属。

工具 async generator 可产出 `ToolEvent`，流从开始到明确耗尽或 `aclose()`
一直算在途调用，即使每次 `anext()` 来自不同 asyncio Task。关闭外层真实
FunctionTool 流也会关闭内部 SDK handler。工具 `timeout` 使用真实单调时钟
deadline，`call.cancelled/check_cancelled()` 可供同步线程协作退出。

显式 SDK 插件只能在当前进程中新增 Python 分发包；需要变更任何已安装分发的版本时，
必须重启并先准备对应依赖环境，不先卸载旧插件或修改当前依赖。此规则同样覆盖传递依赖，
以及版本相同但来源不同的重新安装。SDK 用全部已安装分发的精确版本约束执行只读解析，
检查 pip JSON 报告或 uv dry-run 计划，再使用相同约束安装。无法识别的计划、不可审计的
安装元数据会明确拒绝热安装。uv 计划格式当前验证于 0.8.15；未知格式不会猜测放行。
`test` extra 固定该 uv 版本，作者验证使用目标虚拟环境的工具路径，不依赖本机全局 uv。
满足版本约束或当前平台 marker 不适用的依赖不受此限制；旧插件门禁不变。
安装锁内复核当前分发快照；固定全部已安装包也避免解析期间首次 import 的窗口，
但不承诺能阻止管理员或其他进程同时修改共享环境。解析与安装也不是共享环境的原子事务。
桌面冻结环境的 `--target` 解析可能计划重新复制已有依赖，此时同样拒绝热安装，
需在停止进程后准备依赖；不能把这项保守保护理解为已验证所有桌面安装组合。

公开异常为 `SDKError`、`SDKAccessError`、`SDKCompatibilityError`、`SDKRestartRequiredError`、`StaleContextError`、
`ResourceError`、`ToolInputError` 和兼容导出的 `PluginBusyError`。
`reload/unload/update_config` 的非抛出失败须检查 `results` 中公开 DTO 的
`ok/clean/quiescent/needs_restart/errors`，不能把返回结果对象当作成功。

### 归属、配置和持久化

异步处理器使用 `aread_bytes/awrite_bytes/aread_json/awrite_json/adelete` 和
`media.awrite`，均须 `await`。同步方法保持兼容，只适用于同步回调或明确在线程
中执行的代码。完整文件操作在线程中运行；取消仍等待实际操作停止，未停止前保留
资源归属并拒绝冲突重载。单次原子写入不把多个读写调用变成一个事务，计数等
并发读改写须由作者串行化。

资源归属含 `plugin_id/generation/workspace_id/instance_id`。配置重注册即使复用
旧宿主 instance，也会更新 SDK context identity；旧 context 和旧注册句柄不能
写入新代或删除新代同名贡献。注册句柄 `await handle.close()` 可重复调用。
释放开始即关闭贡献入口；清理失败保留句柄以便重试。

`PluginContext.storage/media` 显式为插件共享。调用上下文的 storage/media 默认
限定当前 workspace；App 再限定 app/user/channel；Channel 再限定渠道名。
工作区身份来自宿主绑定的 ID，不取目录末段；仅有目录的旧调用必须精确匹配唯一
已配置工作区，未知或歧义目录会报错。因此不同工作区可使用同名目录而不共享数据。
路径越界和软链接越界拒绝。媒体返回真实可访问文件 URI，并附宿主现有
`/api/files/preview/...` 的 `preview_url`，正常 reload 不删除持久媒体。
失败/停止但仍由原代持有时可以写清理状态；新代接管即撤销旧代写权限。

`PluginConfig` 为快照，使用 `.get()`；声明的凭据只通过 `.secret()` 访问。
`ToolSpec.config_fields` 进入原 UI 工具设置，按当前 workspace 从真实持久配置读取，
只能读取本工具已声明字段。`type=password` 作为 secret，不能读取其它工具配置。
Provider 沿原 ProviderManager 加密配置，Channel 沿工作区渠道配置。

Scope 支持任务、线程、进程、连接和清理回调。结束的短任务从账本移除；异常
保留诊断。关闭采用有界等待；无法停止的线程/进程或失败的 close 必须保留归属，
不能报告静止。后端 `Memory.close/Channel.stop` 只有显式 `True` 才算停完。
模型、App 和 Channel 调用的失败清理保留原归属；解除故障后可再次请求 reload/unload 重试。
若只剩已中断调用的失败清理，缺省重试也可唤醒它，不会自动取消其它活跃业务。
声明 `ChannelSpec.streaming=True` 时，实现 `StreamingChannelBackend.on_stream`
接收 start/delta/end；入站消息在合并前按渠道实例筛选，旧实例排队消息不会转交新代。

`ChannelMessage.session_scope` 缺省 `default` 保留已有路由；`sender` 按会话与发送者
隔离队列，`group` 只适用于群消息，并将共享历史身份固定为 `group`。
实际访问检查使用 `acl_sender_id`（缺省 `sender_id`），共享历史不会共享授权。
这两种显式作用域在真实消费处逐条检查 ACL，再合并允许的内容；拒绝者的内容
不会因为同批第一人获准而进入模型。队列仍归当前渠道及工作区，不接受全局队列名。

可选 `RunAwareChannelBackend.on_run(context, ChannelRunEvent)` 在模型调用前收到
`start/running`，实际消费收尾收到 `end/completed|failed|cancelled`，无正文也会通知。
ACL 拒绝只产生 `end/rejected`。事件包含本次独立 `run_id`、目标、会话、发送者、
ACL 身份及合并的 `message_ids`；与 `on_stream` 共用会话和平台 metadata。
`OutgoingMessage.run_id`、`ChannelStreamEvent.run_id` 与该通知使用同一标识，
迟到的旧运行回调不得以目标地址作为键清理新运行。主动发送的 `run_id` 为空。
通知依序运行在托管任务内，每次最多等待 5 秒；异常或自取消不覆盖模型结果，
超时仍未停的回调保留归属并阻断冲突替换。它是平台收尾通知，不是运行拦截器。
停止渠道时，已经排队或执行的 `end` 通知只等待完成，不主动取消；连接保持可用。
若等待超过 5 秒，停止明确失败并保留任务和连接，调用方可在回调结束后重试。
只有这些终态通知与普通调用都已退出，才调用后端 `stop` 并关闭其资源作用域。
中断重载/卸载也等待已开始消息流的 `on_stream(end)` 和请求的 `on_run(end)`；
消息流先完成或明确失败，再执行运行终态保底。收尾特例不允许通知再调用模型等新业务。
可选 `health(context) -> ChannelHealth` 提供真实连接探测，未实现返回 `unsupported`。
`PluginTestHost.start_channel(name, settings=None)` 从该工作区已保存的渠道配置恢复并启用；
显式 `{}` 则替换为空设置后启用。`load()` 本身不启动真实渠道消费者。
`PluginTestHost.set_channel_access` 修改真实工作区 ACL；`send_channel` 走实际主动发送
路径，`health_channel` 通过原 ChannelManager 查询健康状态。
要求确认投递的原 API 请求会映射到 `OutgoingMessage.require_delivery=True`；
后端应在平台投递失败时抛公开错误。`send_channel` 缺省要求投递，可显式设为
`require_delivery=False` 测试普通尽力发送。公共配置 `boolean` 由 SDK 转为渠道 UI 的
开关字段，作者声明和值均不改变。

### 回调和观察

Command handler 为 `handler(context, arguments: str)`，返回 `CommandResult`。
SDK Command 与 Hook 的 reply 在真实 Runtime 中保留文本和附件的顺序、预览引用、
块元数据及消息元数据。thinking/hint/tool_call/tool_result 以 `StreamContent(type="data")`
的 `data` 承载完整公开块（含嵌套内容）；这是结构保留，不代表每个渠道会渲染这些块。
消息的原 `name/role/attributes` 保存在公开流消息的
`attributes["sdk_message"]`（`format="qwenpaw-sdk-message/1", version=1`）中；
块原 attributes 完整保存在 `StreamContent.attributes["sdk_attributes"]`。
这些来源字段可 JSON 往返，宿主仍生成真正的事件 ID、状态、序号与内容 index，
作者同名属性不会覆盖传输协议。普通旧插件 Msg 回复仍沿原文本封装路径。
Hook handler 为 `handler(context)`，允许字段随 phase 限定：

| 改动               | 允许阶段                                                     |
| ------------------ | ------------------------------------------------------------ |
| replace_input      | PRE_DISPATCH / POST_DISPATCH / PRE_AGENT_BUILD               |
| injections         | 以上加 POST_AGENT_BUILD / PRE_EXECUTE                        |
| reply / skip_agent | PRE_DISPATCH / POST_DISPATCH / PRE_AGENT_BUILD / PRE_EXECUTE |

结果先完整校验再一次应用；无效结果不留下半截输入修改。错误被原 HookRegistry
隔离，后续 hook 继续；超时不允许晚回调修改已继续的请求。Mode predicate 只接受
不可变消息/身份快照，工具沿同一治理路径，只有活动模式才能进入实际工具集合。
Prompt 使用 `priority`，没有虚假的 `after` 锚点承诺。

事件是观察，不是审批/运行拦截器。无订阅者走原路径；生产任务仅入队，不等待
插件代码。订阅队列有界，优先保留终态；丢失会发 `SubscriptionGap`，终态过载
会断开并标记 `disconnected`。不能据此假设每个 token 必达；应用应重查任务/审批
状态。订阅错误、取消和同步阻塞不改变原业务输出或审批结果。

### 应用与前端

`PawApp.route` handler 为 `(AppContext, HttpRequest)`，返回 JSON、`HttpResponse`
或 `StreamingResponse`；WebSocket handler 为 `(AppContext, WebSocket)`。
HTTP body/SSE/WS 整个生命周期受托管。身份来自真实认证 principal；WebSocket
在 accept 前同样校验。AppContext 提供聊天/流、会话目录/历史、任务、取消、审批。

`await context.workspaces()` 返回有限的 `WorkspaceSummary(id, name, enabled)`，
不返回宿主目录或配置。`async with context.for_workspace(id) as target` 为所选的
已配置、启用工作区创建新调用作用域；app、认证用户和 channel 保持不变。
每次进入重新验证插件代次和目标可用性，未知或停用目标抛 `SDKAccessError`。
Console 的既有授权允许认证用户访问已配置工作区；此接口不接受用户身份参数。
普通请求中进入时仍随该请求取消。需要跨请求持续运行时，显式用
`PluginContext.resources.task(...)` 托管后台协程，在该协程中进入
`for_workspace`；新上下文的取消状态、资源和存储属于后台调用及目标工作区，
不能继续使用已经结束的 HTTP 请求的 `resources`。
退出或取消后的 `AppContext` 不能直接写数据、开始聊天/任务或处理审批，
会抛 `StaleContextError`；只有同身份的 `for_workspace` 委托可留存并重新进入。
已经由 `start_task` 接受的任务独立归属 TaskTracker 和当前插件代次，不随
启动它的 HTTP 请求结束而失效。
任务使用真实 TaskTracker 的 run ID（ChatSpec.id），不是 session_id。
`cancel_task` 只有本次运行的模型/工具等 SDK 流实际结束才返回 `stopped=True`。
若下游不响应取消，超时返回 `stopped=False`，任务仍保留运行归属并阻止冲突替换；
不会仅因外层 Runtime 已返回而写入终态。 SDK 运行还会持有实际模型恢复流，在消费结束后显式关闭外层流，再清理子作用域；关闭失败保留归属，等待公开生命周期操作重试，不依赖垃圾回收。清理开始后禁止该调用链再启动新 SDK 流，
不同运行互不等待；显式 `start_task` 建立独立的新运行归属。
调用作用域中的线程、连接等关闭失败时，同一运行继续保持 `running` 与原归属，
不会因为处理函数已退出就允许同会话后继执行。解除外部阻塞后再次调用
`cancel_task` 重试原有清理；失败期间不自动循环重试，也不清理其他运行的资源。
SDK 会话 ID 加入 user/channel scope，避免同一 app 两个用户取消相互的工具调用。
越权服务操作抛 `SDKAccessError`；标准任务/审批 HTTP 入口返回 403，流在发送
成功响应头之前检查归属。
`task_stream(run_id)` 与 `/tasks/{run_id}/stream` 订阅状态快照，不是 token 流：
先返回当前状态，只在状态变化时再返回，终态后关闭。断开页面不取消任务；
重连重查实际状态。`result` 是最多 65,536 字符的结果摘要，截断由
`result_truncated` 明示；完整输出使用 `chat_stream` 或持久 `history`。
终态保存于插件持久数据，正常 reload/重启后可查；进程消失前未写终态的
running 记录会标为 `interrupted`，不会假称任务仍在执行。
首次任务状态保存失败时不启动业务；启动中途失败会停止已创建的运行，停不完
则保留托管归属。终态保存失败明确返回 `failed` 和保存错误；若磁盘持续不可写，
失败快照仅能在当前进程查询，不能承诺重启后恢复尚未写入的数据。

标准聊天/会话/存储/toast/notify 复用原 PawApp 路由。新任务路径是 `/tasks`，
新审批路径是 `/approvals`；旧 `paw.api.task(customPath)` 协议保持独立。
新 app 提供 `/.sdk` 能力查询。公开 npm 包在 `qwenpaw/plugins/frontend`，
不需要作者复制 Console 内部文件，使用方式见该包 README。
`registerRoutes` 的 `label` 和可选 `title` 接受字符串或纯函数
`(locale: string) => string`，由宿主按当前 Console 语言解析。旧字符串标签不变，
未传 `title` 时仍使用路径生成标题；注册时无需读取浏览器语言或调用 React hook。

### 作者测试与依赖检查

```python
from qwenpaw.plugins.testing import PluginTestHost

async with PluginTestHost(tmp_path / "host", tool_policy={"hello_sdk": "allow"}) as host:
    ctx = await host.load(plugin_directory)
    result = await host.call_tool("hello_sdk", {"name": "SDK"})
    assert (await host.reload(ctx.plugin_id)).ok
    report = await host.unload(ctx.plugin_id)
    assert report.clean and report.quiescent
```

TestHost 使用隔离根目录并恢复宿主路径/单例；同时只允许一个活动 Host。
可传 `workspace_dirs={"sales": "sales/shared", "support": "support/shared"}`
验证 ID 与目录名称不一致的隔离；路径相对 `root/workspaces`，越界和重复目录拒绝。
缺省仍使用工作区 ID 作为目录名。
`close()` 也等待原生工作区任务保存完成状态；5 秒未结束则保留环境并抛 `SDKError`，
不取消正在执行的持久化，可在完成后重试关闭。
`call_tool()` 返回完整工具结果，复用生产端的分片合并规则，保留正文、附件、
累计错误状态和元数据；结束事件的汇总元数据只用于还原结果，不重复追加正文。
需要逐事件观察或测试中途取消时使用 `stream_tool()`。
`load(path)` 或 `load(path, config=None)` 读取该插件已持久保存的配置，
显式 `config={}` 则以空配置加载；可用新进程和相同隔离根目录验证冷启动恢复。
`TestModel/TestConnection` 从 Host 工厂取得，不直接用宿主对象构造；
`PluginContext/AppContext` 与资源作用域由宿主注入，不手动拼装身份。
默认显式测试 ALLOW，`tool_policy` 可逐工具设置 allow/deny/ask；规则持久化到
隔离治理策略，真实 Runtime 与直接工具入口均读取。ASK 使用真实审批服务。
`request/open_http/websocket` 通过 ASGI 路由，流测试不先缓存整个响应。
完整 HTTP 响应读完后会等待服务端真实清理，提前断开才请求取消；清理超过
5 秒会抛 `SDKError` 并保留连接归属，可在资源停止后重试 `close()`。
`configure_chat_model` 为真实 Runtime 选择已注册模型。Channel 测试使用
`start_channel/receive_channel/stop_channel`，仍经过原队列和 Runtime。
`install/set_enabled/uninstall` 走原安装事务与启停入口。
`uninstall` 只删除本 Host 的 `root/plugins` 内安装副本；用 `load` 引用外部源码后
应调用 `unload`，直接 `uninstall` 会抛 `SDKError`，不会删除作者源码。
`inject_failure` 支持 `before_commit/post_commit_cleanup` 两个有限故障点，
`hits` 可确认是否命中。
提交前失败走原回滚，提交后清理失败保留新版本并在结果 `errors` 记录。
依赖变化需要重启时抛公开 `SDKRestartRequiredError`，不热替换依赖。

```sh
python -m qwenpaw.plugins.check ./my-plugin
python -m qwenpaw.plugins.check ./my-plugin --runtime
python -m qwenpaw.plugins.check --template ./hello-sdk
python -m qwenpaw.plugins.check --frontend ./frontend-sdk
```

默认只解析 AST，不执行插件。报告包含精确非法导入/符号、第三方依赖和动态
未验证路径。`--runtime` 明确执行受信插件的加载/激活/清理，观察作者直接进入
内部宿主函数，SDK 转换层的合法内部调用不归责作者。未调用 handler、动态属性
和预先存在的线程/原生调用仍明确未覆盖；SDK 新建工作线程内的同步清理也会观察。
报告绑定包 hash、SDK/规则版本、时间及实际执行阶段。权限原始声明保留路径和
JSON，`permission_review=not-run` 明示未证明权限合规。软链接需人工审查，
文件 hash 与源码扫描共用排除规则。检查器不是恶意代码沙箱，也不是旧插件安装门禁。

正式通用测试位于 `tests/unit/plugins/test_sdk_*`，与原插件 suite 同跑；真实平台
实验属于独立本地验收，不能当作普通离线单元测试，也不进入 SDK 构建包。

## 旧版插件兼容参考

以下保留已有 PluginApi 开发与管理说明，供维护旧插件使用；其中宿主内部类型不属于新 SDK。原有前端 Host API 说明仍适用，新作者优先使用上面的公开类型包。

QwenPaw 提供了插件系统，允许用户扩展 QwenPaw 的功能。

### 概述

插件系统支持以下扩展能力：

- **Provider 插件**：添加新的 LLM Provider 和模型
- **Middleware 插件**：注册 AgentScope `MiddlewareBase` 工厂，在 agent 推理循环中包裹 `on_acting` / `on_reasoning` 等钩子
- **Hook 插件**：在应用启动/关闭时执行自定义代码（app 生命周期级别，仅执行一次）
- **Command 插件**：注册自定义的 `/command` 魔法命令
- **HTTP API 插件**：通过 FastAPI `APIRouter` 在 `/api` 下暴露自定义 REST 接口
- **前端扩展插件**：在浏览器中运行的 JS 插件，共享宿主的 React / Ant Design 运行时，通过声明式 `window.QwenPaw.*` API 扩展界面——注册侧边栏菜单、页面路由、UI 插槽、聊天定制等，无需修改宿主代码
- **Channel 插件**：注册自定义消息频道（如 Slack、LINE）
- **Memory 插件**：注册长期记忆后端、每 Agent 配置 schema、受治理工具和可选的 Console 配置界面

### 插件管理

#### 安装插件

从本地目录安装：

```bash
qwenpaw plugin install /path/to/plugin
```

从 URL 安装（支持 ZIP 文件）：

```bash
qwenpaw plugin install https://example.com/plugin.zip
```

强制重新安装：

```bash
qwenpaw plugin install /path/to/plugin --force
```

QwenPaw 运行时，CLI 会将安装请求交给热安装 API；QwenPaw 停止时，文件会被安装并在下次
启动时加载。

#### 列出已安装插件

```bash
qwenpaw plugin list
```

输出示例：

```
Installed Plugins:
==================

my-provider (v1.0.0)
  Custom LLM provider integration
  Author: Developer Name
  Path: /Users/user/.qwenpaw/plugins/my-provider
```

#### 查看插件详情

```bash
qwenpaw plugin info <plugin-id>
```

#### 卸载插件

```bash
qwenpaw plugin uninstall <plugin-id>
```

### 插件开发

#### 后端插件

##### 基本结构

每个插件至少需要两个文件：

```
my-plugin/
├── plugin.json      # 插件清单（必需）
├── plugin.py        # 入口点（后端必需）
└── README.md        # 文档（推荐）
```

##### plugin.json

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

##### 清单字段说明

| 字段              | 类型            | 必填 | 说明                                                                                                                                                                  |
| ----------------- | --------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`              | `string`        | 是   | 插件唯一标识，同时作为安装目录名，不能包含路径分隔符。                                                                                                                |
| `version`         | `string`        | 是   | 插件语义化版本号（例如 `1.0.0`）。                                                                                                                                    |
| `name`            | `string` 或对象 | 否   | 显示名称，缺省取 `id`。也可写成 `{"zh-CN": "...", "en-US": "..."}`，运行时按"英文优先"的顺序取第一个非空值。                                                          |
| `type`            | `string`        | 否   | 取值之一：`tool`、`provider`、`hook`、`command`、`channel`、`memory`、`frontend`、`general`。省略时会按 `meta` / `entry` 推断（仅为兼容旧插件），新插件建议显式声明。 |
| `description`     | `string` 或对象 | 否   | 插件列表里的简短描述，支持本地化对象形式（同 `name`）。                                                                                                               |
| `author`          | `string`        | 否   | 作者或组织名称。                                                                                                                                                      |
| `entry.backend`   | `string`        | 否\* | 相对插件目录的 Python 入口文件路径，需在其中导出 `plugin`。                                                                                                           |
| `entry.frontend`  | `string`        | 否\* | 已构建的前端 bundle 路径（如 `dist/index.js`）。                                                                                                                      |
| `dependencies`    | `string[]`      | 否   | Python 包依赖，与 `requirements.txt` 合并检查；显式安装、更新或修复时安装缺失项，启动时只检查。                                                                       |
| `qwenpaw_version` | `object`        | 否   | QwenPaw 版本约束（推荐）。包含 `min`（包含）和 `max`（不包含，可选）两个子字段，语义为 `>=min, <max`。省略 `max` 时默认取 `{major}.{minor+1}.0`。                     |
| `min_version`     | `string`        | 否   | **遗留字段。** 需要的最低 QwenPaw 版本。当 `qwenpaw_version` 存在时被忽略，仅为兼容第三方旧插件保留。                                                                 |
| `max_version`     | `string`        | 否   | **遗留字段。** 不兼容的第一个 QwenPaw 版本（不包含）。配合 `min_version` 使用；省略时从 `min_version` 推导。                                                          |
| `meta`            | `object`        | 否   | 自由元数据。前端 UI 与 `type` 推断都会读取（如 `meta.tools[]`、`meta.hook_type`、`meta.provider_id`）。                                                               |
| `entry_point`     | `string`        | 否   | **遗留字段。** 等价于 `entry.backend`，仅为兼容老插件保留，新插件请使用 `entry.backend`。                                                                             |

\* `entry.backend`、`entry.frontend`（或遗留 `entry_point`）至少需要提供其中之一。

##### `type` 取值

| 取值       | 适用场景                                             |
| ---------- | ---------------------------------------------------- |
| `tool`     | 注册一个或多个 Agent 工具（LLM 可调用的函数）。      |
| `provider` | 注册自定义 LLM 提供商 / 模型端点。                   |
| `hook`     | 在应用启动 / 关闭时执行代码（app 生命周期级别）。    |
| `command`  | 注册 `/slash` 控制命令。                             |
| `channel`  | 注册自定义消息频道。                                 |
| `memory`   | 在配置的 Agent 启动前注册记忆后端。                  |
| `frontend` | 提供前端 JS bundle，由 UI 动态加载。                 |
| `general`  | 兜底类型，用于组合型插件或不属于以上任何类别的插件。 |

##### plugin.py

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

        # 注册你的功能
        # api.register_provider(...)
        # api.register_startup_hook(...)
        # api.register_shutdown_hook(...)

        logger.info("✓ My plugin registered")


# Export plugin instance
plugin = MyPlugin()
```

##### 注册与资源清理约定

- `register(api)` 必须是同步方法。异步初始化放在 startup hook 中。
- 后台任务使用 `api.spawn_task()`；进程内副作用使用 `api.effect()` 登记清理。
  teardown 必须幂等，并能处理 setup 只完成一部分的情况。
- 注册时推荐用 `api.declare_provision_files(src, dest, version)` 声明文件置备；
  此时不复制文件，也不返回创建结果。激活时框架在工作线程完成置备，再执行 startup。
  因此不能在 register 中立即读取这些文件。
- startup 中需要立即使用文件时，使用
  `await api.provision_files_async(src, dest, version)`，返回 `create`、`keep` 等实际结果。
  两个入口沿用原有归属和失败回滚规则。旧 `api.provision_files()` 保留同步语义，
  在事件循环中调用仍可能阻塞，建议迁移到上述入口。
- 自定义持久资源使用 `api.provision()`，并提供 `teardown_ref="模块:函数"`，
  让无活实例时仍能执行清理。setup 必须是同步函数。
- 不直接修改宿主登记表。使用 `api.register_*()`，由框架管理撤销。

#### Memory Backend 插件

Memory 插件拥有远程 client、配置模型、prompt、工具和后端特有的检索行为。QwenPaw 核心负责
公共生命周期、auto-memory 队列、backend registry 和每 Agent 的不透明配置容器。

Memory 插件属于启动关键插件：`type: "memory"` 的插件会在 Agent 和 workspace 创建前加载，
确保 `agent.json` 选中的 backend 在 manager 构造前已经注册。未知或不可用的 backend 会明确
失败；QwenPaw 不会将记忆隐式重定向到其他后端。

##### Manifest

```json
{
  "id": "memory-example",
  "name": "Example Memory",
  "version": "1.0.0",
  "type": "memory",
  "entry": {
    "backend": "plugin.py",
    "frontend": "frontend/dist/index.js"
  },
  "meta": {
    "memory_backends": [{ "id": "example", "label": "Example Memory" }]
  }
}
```

##### Python Backend 注册

应从稳定的 `qwenpaw.memory` 导入协议，而不是依赖内部的 `qwenpaw.agents.memory` 包。Backend
factory 接收一个 `MemoryBackendContext`，其中包含 Agent ID、workspace 路径、宿主规范工作
目录、插件配置、语言和 token 估算除数。安装级插件状态必须基于
`context.host_working_dir` 保存，不能从 Agent workspace 路径反推。

```python
from pydantic import BaseModel

from qwenpaw.memory import BaseMemoryManager, MemoryBackendContext
from qwenpaw.plugins.api import PluginApi


class ExampleMemoryConfig(BaseModel):
    endpoint: str
    api_key: str = ""


class ExampleMemoryManager(BaseMemoryManager):
    def __init__(self, context: MemoryBackendContext) -> None:
        super().__init__(context=context)
        self.config = ExampleMemoryConfig.model_validate(
            context.backend_config,
        )

    async def start(self) -> None:
        ...

    async def memory_search(self, query: str, max_results: int = 5, **kwargs):
        ...

    async def auto_memory(self, messages, **kwargs) -> str:
        ...


class ExampleMemoryPlugin:
    def register(self, api: PluginApi) -> None:
        api.register_memory_backend(
            backend_id="example",
            factory=ExampleMemoryManager,
            label="Example Memory",
            config_schema=ExampleMemoryConfig,
            metadata={
                "description": "Example remote memory service",
                "network_access": True,
                "secret_fields": ["api_key"],
            },
        )


plugin = ExampleMemoryPlugin()
```

`BaseMemoryManager` 提供公共 `close()` 实现和自动召回编排。Backend 必须实现 `start()`、
`memory_search()` 和 `auto_memory()`，也可以覆盖 `get_memory_prompt()`、
`list_memory_tools()`、`get_auto_memory_search_options()`、`_search_for_auto_memory()`、
`list_cron_jobs()`、`build_middlewares()` 等可选 hook。

Backend ID 会去除首尾空白并转换为小写。同一插件用同一 factory 重复注册是幂等操作；其他
owner 注册相同 ID 会报错。提供 `config_schema` 时，保存配置会校验并规范化
`running.memory_backend_configs.<backend_id>` 下的内容。`metadata.secret_fields` 控制运行
配置 API 的遮罩行为：保存的 secret 返回为 `"***"`，提交相同遮罩会保留已有值。插件还可
在 `metadata.tools` 中声明各工具的治理元数据。

##### Console 配置注册

如果插件提供自定义配置界面，应通过前端 memory namespace 注册。Form path 应指向通用的
每 Agent 配置容器：

```tsx
const React = window.QwenPaw.host.React;
const { Form, Input } = window.QwenPaw.host.antd;

function ExampleMemoryConfig() {
  return (
    <>
      <Form.Item
        name={["memory_backend_configs", "example", "endpoint"]}
        label="Endpoint"
      >
        <Input />
      </Form.Item>
    </>
  );
}

window.QwenPaw.memoryBackends.register("memory-example", {
  id: "example",
  label: "Example Memory",
  configPath: ["memory_backend_configs", "example"],
  tabKey: "exampleMemory",
  ConfigComponent: ExampleMemoryConfig,
});
```

Console 会将前端注册信息与 `GET /api/agents/memory/backends` 返回的 backend 描述合并。
下拉框展示已注册后端、标记不可用的选项，并渲染当前插件的配置组件。插件清理时会自动移除
对应的前端注册。

##### 运行与卸载规则

- 切换 backend 或修改 backend 配置时会重建 workspace manager，不会原地修改已有远程 client。
- `GET /api/agents/memory/backends` 返回各 backend 的 `id`、`label`、`source`、
  `available` 和公开 `metadata`。
- 如果某个 memory 插件的 backend 正被 live Agent workspace 使用，该插件不能卸载。请先将
  这些 Agent 切换到其他 backend 并重建或停止 workspace。
- 插件清理会注销 backend ownership 和插件拥有的治理条目。

#### 前端插件

前端插件是运行在浏览器端的 JavaScript 扩展。与后端插件通过 Python `PluginApi` 注册能力不同，前端插件通过全局 `window.QwenPaw.*` API 声明式地扩展 Console 界面。

**加载生命周期：**

1. Console 启动，在 `window.QwenPaw` 上挂载 Host SDK（React、antd 等共享依赖）和注册 API（menu、route、slot、chat、memory backends 等命名空间）
2. Console 请求 `/frontend_plugin` 获取已启用的前端插件列表
3. 逐一下载各插件的 JS bundle，通过 Blob URL 动态导入执行
4. 插件代码执行，调用 `window.QwenPaw.*` 注册菜单、路由、聊天定制、memory 配置表单等 UI 扩展
5. 注册立即生效——菜单出现在侧边栏、路由可导航、聊天区域呈现定制内容

插件无需声明使用了哪些前端扩展点；系统通过 `pluginId` 追踪注册。卸载或禁用插件时，包括
memory backend 表单在内的前端注册会在插件清理阶段移除。

**设计特点：**

| 特点              | 说明                                                                             |
| ----------------- | -------------------------------------------------------------------------------- |
| **共享运行时**    | React、ReactDOM、Ant Design 由宿主提供，插件无需打包，避免版本冲突和体积膨胀     |
| **声明式注册**    | 三个核心动词：`set`（设置 / 合并属性）、`render`（替换渲染）、`add`（追加项目）  |
| **pluginId 隔离** | 所有注册方法以 `pluginId` 为第一参数，系统据此追踪来源、检测冲突、支持按插件清理 |
| **可撤销**        | 每个注册返回 `{ dispose() }` 对象，调用即撤销，支持热重载和插件卸载              |
| **国际化**        | 文本字段支持 `Localized<T>` 类型——传入 `(locale) => string` 函数按语言返回不同值 |

**扩展点一览：**

| 命名空间                          | 能力                            | 典型用途                                        |
| --------------------------------- | ------------------------------- | ----------------------------------------------- |
| `host`                            | 共享依赖、React Hooks、认证请求 | 获取 React / antd、读取主题和语言、调用后端 API |
| `menu`                            | 侧边栏菜单项                    | 添加导航入口                                    |
| `route`                           | 页面路由                        | 注册新页面、包装已有页面                        |
| `slot`                            | 通用 UI 插槽                    | 向 Header / Sidebar 等预设位置注入内容          |
| `chat.welcome`                    | 欢迎界面                        | 自定义问候语、推荐提示词                        |
| `chat.theme`                      | 聊天主题色                      | 更换主色调                                      |
| `chat.leftHeader` / `rightHeader` | 聊天头部                        | 设置品牌 Logo、添加操作按钮                     |
| `chat.sender`                     | 输入框                          | 自定义 placeholder、输入建议                    |
| `chat.actions` / `requestActions` | 消息操作按钮                    | 在消息下方添加自定义操作                        |
| `chat.requestPayload`             | 外发聊天请求体                  | 请求发送到后端前追加或改写自定义字段            |
| `chat.request` / `response`       | 消息气泡                        | 在消息前后追加内容或完全替换渲染                |
| `chat.toolRender`                 | 工具调用渲染                    | 自定义工具结果展示（如天气卡片）                |
| `chat.card`                       | 自定义卡片                      | 注册新的卡片类型                                |
| `memoryBackends`                  | 记忆后端配置界面                | 注册 backend 标签、Tab 和 React 配置表单        |
| `audit`                           | 审计与调试                      | 查看所有扩展注册记录                            |

##### 基本结构

```
my-plugin/
├── plugin.json      # 插件清单（必需）
├── src/
│   └── index.tsx    # 入口点，调用 window.QwenPaw.* API
├── package.json     # 依赖声明
├── tsconfig.json    # TypeScript 配置
└── vite.config.ts   # 构建配置
```

##### plugin.json

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

##### src/index.tsx

插件入口文件在加载时执行，通过 `window.QwenPaw.*` API 注册扩展：

```tsx
const { React, antd } = window.QwenPaw.host;
const pluginId = "my-plugin";

// 调用 window.QwenPaw.* API 注册菜单、路由、聊天定制等
// 详见下方「前端扩展 API」
```

##### 构建工具链

**package.json**：

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

**tsconfig.json**：

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

**vite.config.ts**：

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

`jsxRuntime: "classic"` 将 JSX 编译为 `React.createElement`，使用宿主提供的 `React`；`external` 避免打包 React，使用应用已加载的版本。

##### 构建和安装

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/my-plugin/
qwenpaw app
```

可将 `console/src/plugins/types/qwenpaw.d.ts` 复制到插件项目中作为 `qwenpaw-host.d.ts`，获得完整的类型提示。

### 前端扩展 API

前端插件通过 `window.QwenPaw.*` API 扩展 Console 界面，无需修改宿主代码。所有注册方法第一个参数是 `pluginId`，每个注册返回 `{ dispose() }` 对象用于撤销。

#### Host SDK — `window.QwenPaw.host`

宿主共享依赖，插件无需打包这些库：

```ts
host.React                        // React 库
host.ReactDOM                     // ReactDOM 库
host.antd                         // Ant Design 组件库
host.antdIcons                    // Ant Design 图标库
host.apiBaseUrl                   // API 基础 URL
host.getApiUrl(path: string)      // 拼接完整 API URL
host.getApiToken(): string | null // 获取当前认证 Token
```

**React Hooks（在 React 组件内使用）：**

```ts
const theme = window.QwenPaw.host.useTheme(); // "light" | "dark"
const locale = window.QwenPaw.host.useLocale(); // "zh" | "en"
const agent = window.QwenPaw.host.useSelectedAgent(); // { id: string }
const session = window.QwenPaw.host.useCurrentSession(); // { id: string } | null
```

**命令式获取（可在任意位置调用）：**

```ts
const agentId = window.QwenPaw.host.getSelectedAgentId();
const sessionId = window.QwenPaw.host.getCurrentSessionId();
```

**认证代理请求（自动注入 Authorization 和 X-Agent-Id 请求头）：**

```ts
const resp = await window.QwenPaw.host.fetch("/api/v1/my-endpoint", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "test" }),
});
const data = await resp.json();
```

#### 侧边栏菜单 — `window.QwenPaw.menu`

| 方法       | 签名                                     | 说明             |
| ---------- | ---------------------------------------- | ---------------- |
| `add`      | `(pluginId, item \| item[]): Disposable` | 添加菜单项       |
| `replace`  | `(pluginId, targetId, item): Disposable` | 替换已有菜单项   |
| `remove`   | `(targetId): void`                       | 移除菜单项       |
| `snapshot` | `(location?): MenuItem[]`                | 获取当前菜单快照 |

**MenuItem 参数：**

```ts
{
  id: string;                    // 全局唯一，如 "my-plugin.foo"
  label: string | (() => ReactNode);
  icon?: ReactComponent | ReactNode;
  route?: string;                // 点击时导航到的路由 id
  parentId?: string;             // 挂在哪个分组下
  location?: "primary.agentScoped" | "primary.settings" | "userMenu";
  before?: string;               // 排在某个 id 之前
  after?: string;                // 排在某个 id 之后
  order?: number;                // 数值越小越靠前
  visible?: () => boolean;       // 动态控制显隐
  isGroup?: boolean;             // 作为分组标题
  divider?: boolean;             // 渲染为水平分割线
}
```

#### 页面路由 — `window.QwenPaw.route`

| 方法      | 签名                                          | 说明                     |
| --------- | --------------------------------------------- | ------------------------ |
| `add`     | `(pluginId, route \| route[]): Disposable`    | 注册新路由               |
| `replace` | `(pluginId, targetId, component): Disposable` | 替换已有路由的组件       |
| `wrap`    | `(pluginId, targetId, wrapper): Disposable`   | 包装已有路由（洋葱模式） |
| `remove`  | `(targetId): void`                            | 移除路由                 |

**Route 参数：**

```ts
{
  id: string; // 全局唯一，如 "my-plugin.home"
  path: string; // URL 路径，支持 react-router 模式
  component: React.ComponentType; // 页面组件
}
```

**wrap 示例（为已有页面加顶部 banner）：**

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

#### 通用 UI 插槽 — `window.QwenPaw.slot`

| 方法       | 签名                                          | 说明                                          |
| ---------- | --------------------------------------------- | --------------------------------------------- |
| `fill`     | `(pluginId, name, render, opts?): Disposable` | 向插槽追加内容（可多个共存）                  |
| `replace`  | `(pluginId, name, render, opts?): Disposable` | 替换插槽内容（最后注册的生效，屏蔽所有 fill） |
| `snapshot` | `(): SlotInfo[]`                              | 获取所有已注册的插槽信息                      |

**内置插槽：**

| 插槽名              | 类型    | UI 位置                        |
| ------------------- | ------- | ------------------------------ |
| `header.logo`       | replace | 顶部导航栏最左侧               |
| `header.left`       | fill    | 顶部导航栏左区（Logo 右边）    |
| `header.right`      | fill    | 顶部导航栏右区（设置按钮左边） |
| `sider.top`         | fill    | 侧边栏顶部（Agent 选择器下方） |
| `sider.bottom`      | fill    | 侧边栏底部（菜单下方）         |
| `content.statusBar` | fill    | 主内容区顶部                   |
| `overlay.global`    | fill    | 全局覆盖层                     |

**示例：**

```tsx
// 替换 Header Logo
window.QwenPaw.slot.replace("my-plugin", "header.logo", (defaultLogo) => {
  return <img src="https://example.com/logo.svg" style={{ height: 24 }} />;
});
```

#### 聊天欢迎界面 — `chat.welcome`

```tsx
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => (locale.startsWith("zh") ? "你好！" : "Hello!"),
  description: "I specialize in data analysis.",
  avatar: "https://example.com/avatar.png",
  nick: "My Bot",
  prompts: [
    { label: "分析数据", value: "请分析上传的数据集" },
    { label: "生成图表", value: "根据数据创建柱状图" },
  ],
});

// 或完全替换欢迎界面
window.QwenPaw.chat.welcome.render("my-plugin", (props) => {
  return <div>Custom Welcome</div>;
});
```

#### 聊天主题 — `chat.theme`

```ts
window.QwenPaw.chat.theme.set("my-plugin", {
  colorPrimary: "#1890ff",
});
```

#### 聊天头部 — `chat.leftHeader` / `chat.rightHeader`

```tsx
// 设置左上角标题
window.QwenPaw.chat.leftHeader.set("my-plugin", {
  title: "My Brand",
  logo: <img src="logo.svg" style={{ height: 20 }} />,
});

// 在右上角添加按钮
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

#### 输入框 — `chat.sender`

```ts
// 自定义 placeholder
window.QwenPaw.chat.sender.set("my-plugin", {
  placeholder: "Ask me anything...",
  disclaimer: "Responses may not be accurate.",
});

// 添加输入建议
window.QwenPaw.chat.sender.addSuggestion("my-plugin", {
  id: "my-plugin.suggestions",
  items: [
    { label: "/analyze", value: "analyze" },
    { label: "/visualize", value: "visualize" },
  ],
});
```

#### 消息操作按钮 — `chat.actions` / `chat.requestActions`

```tsx
// AI 回复消息下方添加操作按钮
window.QwenPaw.chat.actions.add("my-plugin", {
  id: "my-plugin.star",
  icon: <span>⭐</span>,
  onClick: ({ data }) => console.log("Starred:", data),
});

// 用户消息下方添加操作按钮
window.QwenPaw.chat.requestActions.add("my-plugin", {
  id: "my-plugin.edit",
  icon: <span>✏️</span>,
  onClick: ({ data }) => console.log("Edit:", data),
});
```

#### 请求体转换 — `chat.requestPayload`

使用 `chat.requestPayload.add` 可以在 Console 将聊天请求发送到后端前改写 `requestBody`。多个转换函数会按 `order` 从小到大执行，入参包含当前 `payload`、解析后的 `sessionId` 和 `selectedAgent`。

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

转换函数返回新对象时会替换当前请求体；返回 `undefined` 时保持请求体不变。建议使用全局唯一的 `id`，方便审计和卸载时清理。

#### 消息气泡自定义 — `chat.request` / `chat.response`

```tsx
// 设置默认 AI 回复的头像和昵称
// 当前会复用 welcome.avatar / welcome.nick，因为默认 ResponseCard 读取这两个字段
window.QwenPaw.chat.response.set("my-plugin", {
  avatar: "https://example.com/bot-avatar.png",
  nick: "My Bot",
});

// 在用户消息前方追加内容
window.QwenPaw.chat.request.prepend("my-plugin", ({ data }) => {
  return <div style={{ fontSize: 10, color: "#999" }}>User</div>;
});

// 在最新 AI 回复下方追加信息条
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

// 完全替换用户消息渲染（可调用 fallback() 保留默认渲染）
window.QwenPaw.chat.request.render("my-plugin", ({ data, fallback }) => {
  return (
    <div style={{ border: "1px dashed #ccc", borderRadius: 8, padding: 4 }}>
      {fallback()}
    </div>
  );
});
```

#### Assistant 代码块与消息提交

`chat.codeBlock(pluginId, language, Component)` 可以将回答中的代码块显示为交互组件。例如，注册 `openui-lang` 后，回答中标记为该语言的代码块就会交给你的组件渲染。

组件通过 `source` 获取截至当前收到的源码，通过 `isStreaming` 判断代码块是否仍在生成。宿主在流式更新时保留组件的局部状态；请使用固定的组件类型，并在组件中处理尚未生成完整的内容。组件还会收到 `language`、`messageId`、`blockId`、`agentId`、`sessionId` 和默认代码展示函数 `fallback()`。

同一语言以最后注册的组件为准，调用返回值的 `dispose()` 可恢复前一个注册。`chat.disposeAll(pluginId)` 可清理该插件的全部聊天扩展。

`await chat.submit(pluginId, { query, agentId, sessionId })` 可将用户在组件中的选择作为新消息提交。请传入组件收到的 `agentId` 和 `sessionId`。消息会加入原会话的发送队列，输入框中的草稿和附件会保留。Promise 在入队成功后完成；对话尚未就绪、用户已切换会话或 Agent、队列已满时会返回错误。

`host.openExternalLink(url)` 可在浏览器或桌面端打开外部链接。

#### 工具调用渲染 — `chat.toolRender`

```tsx
// 注册自定义工具结果渲染组件（props 包含 result, sessionId, messageId）
window.QwenPaw.chat.toolRender("my-plugin", "get_weather", ({ result }) => {
  const data = typeof result === "string" ? JSON.parse(result) : result;
  return (
    <div style={{ padding: 12, border: "1px solid #e8e8e8", borderRadius: 8 }}>
      {data.city}: {data.temperature}°C
    </div>
  );
});
```

#### 自定义卡片 — `chat.card`

```ts
window.QwenPaw.chat.card("my-plugin", "my-card", MyCardComponent);
```

#### 记忆后端界面 — `window.QwenPaw.memoryBackends`

```ts
const registration = window.QwenPaw.memoryBackends.register("my-plugin", {
  id: "example",
  label: "Example Memory",
  configPath: ["memory_backend_configs", "example"],
  tabKey: "exampleMemory",
  ConfigComponent: ExampleMemoryConfig,
});

registration.dispose();
```

`id` 必须与 Python backend 注册一致。`ConfigComponent` 是可选的；不提供时 backend 仍可
出现在选择器中，但不会显示自定义配置 Tab。

#### 审计与调试

```ts
// 查看扩展注册记录
console.table(window.QwenPaw.audit.overrides());

// 清理插件的所有 Chat 扩展注册
window.QwenPaw.chat.disposeAll("my-plugin");
```

#### 国际化支持

所有支持 `Localized<T>` 类型的字段可传入函数，按语言返回不同值：

```ts
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => (locale.startsWith("zh") ? "你好！" : "Hello!"),
});
```

#### 常见错误

| 错误                              | 原因                                 | 解决                                        |
| --------------------------------- | ------------------------------------ | ------------------------------------------- |
| `e.item.render is not a function` | render/prepend/append 传了非函数     | 确保传入 React 组件或返回 ReactNode 的函数  |
| `duplicate id`                    | 两次 `add` 使用了相同 id             | 使用全局唯一 id（推荐 `pluginId.xxx` 格式） |
| Hook 在组件外调用                 | `useTheme()` 等在非 React 上下文使用 | 改用 `getSelectedAgentId()` 等命令式 API    |

### 使用示例

#### 示例 1：添加自定义 Provider

假设你想接入一个企业内部的 LLM 服务。

##### 1. 创建插件目录

```bash
mkdir my-llm-provider
cd my-llm-provider
```

##### 2. 创建 plugin.json

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

##### 3. 创建 provider.py

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
        """获取默认模型列表。"""
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

##### 4. 创建 plugin.py

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

        # 从同一目录加载 provider 模块
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

##### 5. 安装和使用

```bash
# 安装插件
qwenpaw plugin install my-llm-provider

# 启动 QwenPaw
qwenpaw app

# 在 Web UI 中配置 API Key
# 然后就可以使用新的 Provider 了
```

#### 示例 2：添加启动钩子

假设你想在 QwenPaw 启动时初始化一个监控服务。

##### 1. 创建插件

```bash
mkdir monitoring-hook
cd monitoring-hook
```

##### 2. 创建 plugin.json

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

##### 3. 创建 plugin.py

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

                # 初始化你的监控服务
                # from my_monitoring import init_monitoring
                # init_monitoring(app_name="QwenPaw")

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

##### 4. 安装

```bash
qwenpaw plugin install monitoring-hook
qwenpaw app
```

#### 示例 3：添加自定义命令

假设你想添加一个 `/status` 命令来查看系统状态。

##### 1. 创建插件

```bash
mkdir status-command
cd status-command
```

##### 2. 创建 plugin.json

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

##### 3. 创建 plugin.py

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

##### 4. 安装和使用

```bash
qwenpaw plugin install status-command
qwenpaw app

# 使用命令
/status
```

#### 示例 4：添加自定义前端页面

向侧边栏添加一个欢迎页面。构建工具链文件（`package.json`、`tsconfig.json`、`vite.config.ts`）参考上方「前端插件 > 构建工具链」。

**plugin.json**：

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

**src/index.tsx**：

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
      <Typography.Paragraph>插件系统运行正常！</Typography.Paragraph>
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

#### 示例 5：自定义工具调用渲染

自定义 Agent 工具调用结果的展示方式。项目结构同示例 4，仅 `src/index.tsx` 不同。

**src/index.tsx**：

```tsx
const { React, antd } = window.QwenPaw.host;
const { Card, Descriptions } = antd;
const pluginId = "tool-render-plugin";

window.QwenPaw.chat.toolRender(pluginId, "get_weather", ({ result }) => {
  const data = typeof result === "string" ? JSON.parse(result) : result;
  return (
    <Card title="天气信息" size="small" style={{ marginTop: 8, maxWidth: 400 }}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label="城市">{data.city}</Descriptions.Item>
        <Descriptions.Item label="温度">{data.temperature}°C</Descriptions.Item>
        <Descriptions.Item label="天气">{data.weather}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
});
```

#### 示例 6：自定义聊天欢迎界面

定制对话页面的欢迎语、描述和推荐提示词。项目结构同示例 4，仅 `src/index.tsx` 不同。

**src/index.tsx**：

```tsx
const pluginId = "custom-greeting-plugin";

window.QwenPaw.chat.welcome.set(pluginId, {
  greeting: (locale) =>
    locale.startsWith("zh")
      ? "你好！我是定制版 QwenPaw"
      : "Hello! I'm customized QwenPaw",
  description: "这是一个定制化的聊天助手",
  prompts: [
    { label: "分析代码", value: "帮我分析这段代码" },
    { label: "单元测试", value: "写一个单元测试" },
    { label: "优化逻辑", value: "优化这段逻辑" },
  ],
});
```

#### 示例 7：暴露 FastAPI 接口

后端插件可以通过注册 `fastapi.APIRouter` 暴露自己的 HTTP 接口。路由会挂载在
`/api` 加上你指定的前缀下，与 QwenPaw 核心 API 使用同一个 FastAPI 应用，因此
共享 CORS、鉴权等设置，并会出现在 `/openapi.json` 与 `/docs` 中。

下面示例增加一个简单的 `/api/pets` 接口：列出宠物，并支持新增。

##### 1. 创建插件目录

```bash
mkdir pet-api-plugin && cd pet-api-plugin
```

##### 2. 创建 plugin.json

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

##### 3. 创建 plugin.py

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

##### 4. 安装并试用

```bash
qwenpaw plugin install pet-api-plugin
```

启动 QwenPaw 后，可在终端用 `curl` 测试（端口请按你本地实际为准，例如 `8088`）：

```bash
# 列出全部宠物
curl http://127.0.0.1:8088/api/pets

# 按 id 查询
curl http://127.0.0.1:8088/api/pets/1

# 新增宠物（POST 到集合路径 /api/pets）
curl -X POST http://127.0.0.1:8088/api/pets \
  -H "Content-Type: application/json" \
  -d '{"name": "Luna", "species": "rabbit"}'
```

**说明：**

- `prefix` 必须以 `/` 开头，且不能仅为 `/`，应使用有语义的片段（如 `/pets`）。完整路径恒为 `/api` + 你的 `prefix`。
- 每个前缀只能被一个插件占用；重复注册相同前缀会抛出 `ValueError`。
- `tags` 可选；省略时路由在 OpenAPI 中会默认打上 `plugin:<插件 id>` 标签。
- 插件卸载或禁用时会自动卸载对应路由。

#### 示例 8：Tracing Middleware（工具调用追踪）

本示例展示如何注册一个 `on_acting` middleware，当设置环境变量 `QWENPAW_TRACE` 时记录每次 tool call 的名称、参数和执行耗时。

**plugin.json：**

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

**tracing_plugin.py：**

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

**要点：**

- **条件激活**：工厂函数检测环境变量 `QWENPAW_TRACE`，仅设置时启用
- **`priority=50`**：比默认优先级更高（数值更小 = 更靠外层），确保 tracing 包裹其他 middleware
- **`on_acting` 钩子**：在 tool call 执行前/后测量耗时
- 完整源码参见 `plugins/middleware-demo/tracing-middleware/tracing_plugin.py`

---

#### 示例 9：Thinking Log Middleware（推理过程日志）

本示例展示如何注册一个 `on_reasoning` middleware，捕获并打印模型的思维链。

**plugin.json：**

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

**thinking_log_plugin.py：**

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

**要点：**

- **无条件激活**：工厂始终返回实例，适用于所有请求
- **`on_reasoning` 钩子**：在模型推理阶段捕获流式事件（`ThinkingBlockDeltaEvent` 为思维链，`TextBlockDeltaEvent` 为文本响应）
- **实时打印**：每收到一个 delta 事件即打印，同时 yield 给下游，不阻塞流式响应
- 完整源码参见 `plugins/middleware-demo/thinking-log-middleware/thinking_log_plugin.py`

---

#### 示例 10：注册自定义消息频道

Channel 插件可以为 QwenPaw 添加新的消息平台。注册后的频道会在控制台 UI 中与内置
频道（钉钉、Telegram 等）一起显示，支持同样的启用/禁用和配置方式。

##### 1. 创建插件目录

```bash
mkdir sample-channel-plugin && cd sample-channel-plugin
```

##### 2. 创建 plugin.json

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

##### 3. 创建 channel.py — BaseChannel 子类

Channel 类必须实现 `BaseChannel` 的契约，核心方法包括：

- **`from_config(cls, process, config, ...)`** — 类方法，从保存的配置创建实例。
  `ChannelManager` 启动时通过它实例化你的频道。
- **`start()` / `stop()`** — 生命周期钩子，频道启用/禁用时调用。
- **`send(to_handle, text, meta)`** — 向用户/会话发送消息。

```python
# -*- coding: utf-8 -*-
"""Sample 频道实现。"""

import logging
from pathlib import Path
from typing import Optional

from qwenpaw.app.channels.base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
)
from qwenpaw.app.channels.renderer import ChannelDisplayConfig

logger = logging.getLogger(__name__)


class SampleChannel(BaseChannel):
    """Sample 消息频道。"""

    channel = "sample"  # 唯一 key，必须与 config key 一致

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool = True,
        bot_token: str = "",
        signing_secret: str = "",
        bot_prefix: str = "",
        on_reply_sent: OnReplySent = None,
        display_config: ChannelDisplayConfig | None = None,
        **kwargs,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            display_config=display_config,
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
        display_config: ChannelDisplayConfig | None = None,
        workspace_dir: Optional[Path] = None,
    ) -> "SampleChannel":
        """从配置创建实例。

        注意：插件频道的 ``config`` 是 ``types.SimpleNamespace`` 对象
        （不是 dict），请使用 ``getattr(config, "field", default)``
        安全读取字段。
        """
        return cls(
            process=process,
            enabled=getattr(config, "enabled", False),
            bot_token=getattr(config, "bot_token", ""),
            signing_secret=getattr(config, "signing_secret", ""),
            bot_prefix=getattr(config, "bot_prefix", ""),
            on_reply_sent=on_reply_sent,
            display_config=display_config
            or ChannelDisplayConfig.from_config(config),
        )

    async def start(self):
        """启动 Sample 事件监听。"""
        logger.info("Sample channel starting (token=%s...)", self.bot_token[:8])
        # 在此启动你的平台 API 客户端

    async def stop(self):
        """停止 Sample 事件监听。"""
        logger.info("Sample channel stopping")

    async def send(self, to_handle: str, text: str, meta=None):
        """向 Sample 用户或频道发送消息。"""
        logger.info("Sending to sample %s: %s", to_handle, text[:50])
        # 使用 sample-sdk 发送消息
```

> **重要：`config` 参数类型** — 插件频道的 `from_config()` 收到的 `config`
> 是 `types.SimpleNamespace` 对象（不是 dict 或 Pydantic model）。框架会将
> `BaseChannelConfig` 的默认值与用户保存的配置合并后传入。请始终使用
> `getattr(config, "field", default)` 安全读取字段。

##### 4. 创建 plugin.py — 插件入口

```python
# -*- coding: utf-8 -*-
"""Sample Channel 插件入口。"""

import logging
from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class SampleChannelPlugin:
    """Sample Channel 插件。"""

    def register(self, api: PluginApi):
        """注册 Sample 频道。"""
        from .channel import SampleChannel

        api.register_channel(
            channel_class=SampleChannel,
            label="Sample",
            description="Sample messaging channel integration",
            icon="https://example.com/sample-icon.png",  # 可选：卡片图标（仅 http/https）
            doc_url={  # 可选：文档链接，支持纯字符串或本地化字典（仅 http/https）
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

##### 5. 安装和使用

```bash
qwenpaw plugin install sample-channel-plugin
qwenpaw app
```

启动后，在控制台的 **Control → Channels** 中可以看到 Sample 频道卡片，点击即可
填写凭证并启用。

##### 6. 添加 Webhook 端点（可选）

如果你的频道需要接收 HTTP 回调（如你的平台事件 API），可以在同一个插件中
注册 FastAPI 路由：

```python
from fastapi import APIRouter

def register(self, api: PluginApi):
    from .channel import SampleChannel

    api.register_channel(channel_class=SampleChannel, ...)

    # 在 /api/sample/events 挂载 webhook 端点
    router = APIRouter()

    @router.post("/events")
    async def sample_events(request):
        body = await request.json()
        # 处理事件验证和消息
        return {"ok": True}

    api.register_http_router(router, prefix="/sample", tags=["sample"])
```

**要点：**

- `channel_class` 必须是 `BaseChannel` 的子类，且需要有 `channel` 类属性（唯一
  key）。
- **必须实现 `from_config`** — `ChannelManager` 启动时通过它创建频道实例。
  `config` 参数是 `SimpleNamespace`，不是 dict。
- `config_fields` 定义控制台设置面板中显示的表单字段，支持类型：`text`、
  `password`、`number`、`switch`、`select`。
- 每个字段的 `label`、`help`、`placeholder` 既可以是纯字符串，也可以是
  本地化字典。字典的键**同时支持长编码（如 `zh-CN`、`en-US`）和短编码
  （如 `zh`、`en`），两者可混用**。取值按优先级回退（当前语言精确码 →
  短码 → 短码前缀匹配 → 英文 → 中文 → 字典首个非空值），确保缺失某语言
  时不会显示为空白。
- `icon`（可选）为频道卡片自定义图标 URL，仅支持 `http`/`https` 链接；其他值
  会被忽略并回退到默认图标。
- `doc_url`（可选）为频道文档链接，可以是纯字符串，也可以是本地化字典
  （如 `{"zh": "...", "en": "..."}`，键的长短码规则同 `label`）。仅支持
  `http`/`https` 链接；控制台设置面板标题栏会显示一个 “Doc” 按钮，点击按当前
  语言跳转，值非法或缺失时不显示按钮。
- 插件频道与内置频道共享启用/禁用、访问控制、`bot_prefix` 等功能。
- 如果插件频道 key 与内置频道冲突，内置频道优先，插件频道会被跳过并打印警告。
- 对于基于 webhook 的频道，可在同一个插件中组合 `register_channel` 和
  `register_http_router`。

### 依赖管理

#### 声明 Python 包依赖

可以在 `plugin.json` 中声明依赖，无需同时创建 `requirements.txt`：

```json
{
  "dependencies": ["httpx>=0.24.0", "pydantic>=2.0.0"]
}
```

也可以使用 `requirements.txt`：

```
httpx>=0.24.0
pydantic>=2.0.0
```

两处声明会合并后进入同一依赖检查和安装流程，不存在覆盖优先级。例如清单声明
`example-package>=1.0`、文件声明 `example-package<2.0`，环境必须同时满足两项约束；
互相冲突的约束会使检查或依赖解析失败。建议只在一处维护同一项依赖，避免重复声明。
这里的 `dependencies` 指 Python 包，不是其他插件 ID 或运行时服务依赖。

显式安装、更新或修复时，框架检查并安装缺失依赖。开机只检查，不自动安装；缺失依赖会
使该插件加载失败。可调用 `POST /api/plugins/{plugin_id}/repair-dependencies` 修复；
停用的插件修复后仍保持停用。与受保护宿主包冲突的版本会被拒绝，需先解决环境冲突。
管理员管理的本地运行环境不自动安装依赖，需由管理员处理。

#### 使用自定义 PyPI 源

```
--index-url https://custom-pypi.example.com/simple
my-package>=1.0.0
```

支持单独一行的 `--index-url URL` 或 `--index-url=URL`。源地址交给 pip / uv，
依赖包仍接受版本和宿主包检查。其他选项、嵌套 `-r` 文件、extras 和直接 URL 依赖暂不支持。
源配置只能写在 `requirements.txt` 中；manifest 的每个依赖项必须是一条包名及可选版本、
环境条件声明，不能包含安装选项或多行文本。

### 最佳实践

#### 1. 命名规范

- **插件 ID**：使用小写字母和连字符，如 `my-plugin`
- **版本号**：遵循语义化版本（1.0.0, 1.1.0, 2.0.0）

#### 2. 错误处理

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

#### 3. 日志记录

使用 Python logging 记录插件行为：

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Plugin loaded")
logger.debug("Debug information")
logger.error("Error occurred", exc_info=True)
```

#### 4. 文档

提供清晰的 README.md 文档，包括：

- 功能说明
- 安装步骤
- 使用示例
- 配置说明
- 故障排查

### 优先级系统

#### Hook 优先级

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

### 故障排查

#### 插件未加载

1. 检查插件是否已安装：

   ```bash
   qwenpaw plugin list
   ```

2. 查看 QwenPaw 日志：

   ```bash
   tail -f ~/.qwenpaw/logs/qwenpaw.log | grep -i plugin
   ```

3. 验证插件清单格式：
   ```bash
   qwenpaw plugin info <plugin-id>
   ```

#### 依赖安装失败

1. 检查 `requirements.txt` 格式
2. 手动安装依赖测试：
   ```bash
   pip install -r /path/to/plugin/requirements.txt
   ```
3. 使用 `--force` 重新安装插件

#### Provider 未显示

1. 确认插件已安装并重启 QwenPaw
2. 检查 Web UI 的模型管理页面
3. 查看日志中的 provider 注册信息

#### 命令未响应

1. 确认插件已安装
2. 检查日志中命令处理器是否注册成功
3. 确认命令名称是否匹配（如 `/status`）

### 安全注意事项

1. **只安装可信插件**：插件代码会在 QwenPaw 进程中执行
2. **检查依赖**：确保插件依赖来自可信源
3. **审查代码**：安装前审查插件源代码
4. **热加载注意**：当前版本支持运行中通过 API 热安装/热卸载插件，无需重启。请注意热加载时的状态一致性

### PluginApi 参考

#### register_memory_backend

注册插件拥有的记忆后端。Memory 插件应在常规 `register()` 方法中调用，并在 manifest 中
声明 `type: "memory"`，以便在 Agent 启动前完成注册。

```python
api.register_memory_backend(
    *,
    backend_id: str,
    factory: Type,
    label: str = "",
    config_schema: Type | None = None,
    metadata: dict | None = None,
)
```

核心使用的 metadata 包括 `description`、`network_access`、`secret_fields` 和 `tools`。
每个 `tools` 条目可以设置 `python_name`、`policy_name`、`tool_type`、`target_param` 和
`sandbox_required`，用于治理注册。

#### register_provider

注册自定义 LLM Provider。

```python
api.register_provider(
    provider_id: str,              # Provider 唯一标识符（必填）
    provider_class: Type,          # Provider 类（必填）
    label: str = "",               # 显示名称（可选，默认为 provider_id）
    base_url: str = "",            # API base URL（可选）
    **metadata,                    # 额外关键字参数（chat_model, require_api_key 等）
)
```

#### register_startup_hook

注册启动钩子。

```python
api.register_startup_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

#### register_shutdown_hook

注册关闭钩子。

```python
api.register_shutdown_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

#### register_http_router

将 `fastapi.APIRouter` 挂载到 `/api` + _prefix_ 下。

```python
api.register_http_router(
    router: APIRouter,             # fastapi.APIRouter 实例
    *,
    prefix: str,                   # /api 下的路径，例如 "/pets"
    tags: Optional[List[str]] = None,  # OpenAPI 标签（可选）
)
```

完整步骤见上文「示例 7：暴露 FastAPI 接口」。

#### register_control_command

注册自定义 `/slash` 控制命令。

```python
api.register_control_command(
    handler: BaseControlCommandHandler,  # 命令处理器实例
    priority_level: int = 10,            # 命令优先级（默认: 10）
)
```

handler 必须继承 `qwenpaw.runtime.commands.control.base.BaseControlCommandHandler`，并实现 `command_name`、`help_text` 和 `async handle(self, ctx, args)` 方法。

#### register_tool

将工具函数注册到 Agent 的工具集中。

```python
api.register_tool(
    tool_name: str,          # 工具函数的唯一名称
    tool_func: Callable,     # 要注册的工具函数
    description: str = "",   # UI 中显示的描述
    icon: str = "🔧",        # 显示图标（emoji 字符串）
    enabled: bool = False,   # 是否默认启用
)
```

#### register_uninstall_hook

注册卸载钩子，仅在插件被显式卸载时执行。

```python
api.register_uninstall_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

#### register_workspace_created_hook

注册 workspace 创建时触发的钩子。

```python
api.register_workspace_created_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数: (workspace_info: dict) -> None
    priority: int = 100, # 优先级（越低越早执行）
)
```

#### get_tool_config / set_tool_config

获取或保存每个 Agent 的工具配置。

```python
config = api.get_tool_config(tool_name: str, agent_id: str)  # 返回 dict
api.set_tool_config(tool_name: str, agent_id: str, config: dict)
```

#### register_middleware

注册 AgentScope `MiddlewareBase` 工厂。

```python
api.register_middleware(
    middleware_factory: Callable,   # 工厂函数
    *,
    priority: int = 100,           # 优先级（越低越靠外层）
)
```

工厂函数签名：`(ctx: HookContext, agent_config: AgentProfileConfig) -> MiddlewareBase | None`

- `ctx` 包含 `session_id`、`agent_id`、`workspace_dir` 等请求级上下文
- 返回 `None` 表示本次请求跳过该 middleware
- `priority` 越小越先进入洋葱模型（即越靠外层）

工厂在每次请求的 `AgentBuilder.build()` 阶段被调用，返回的 middleware 实例将被插入到 agent 的中间件链中。

完整步骤见上文「示例 8」和「示例 9」。

### 高级功能

#### 修改 Agent 行为

如需拦截或增强 agent 的请求处理，推荐以下方式：

- **增强 agent 推理循环**：使用 `register_middleware` 注册 AgentScope middleware（`on_acting` / `on_reasoning` 钩子）
- **拦截特定命令**：使用 `register_control_command` 注册自定义命令处理器
- **在请求生命周期中注入逻辑**：使用 `HookRegistry`（8 阶段 hook）

当前请求流程为 `Runtime.run()` → `AgentBuilder.build()` → `AgentExecutor.run()`。

#### 访问运行时信息

通过 `api.runtime` 访问运行时信息：

```python
def my_hook():
    # 访问 provider manager
    provider_manager = api.runtime.provider_manager

    # 获取所有 providers
    providers = provider_manager.list_provider_info()
```

### 插件打包

将插件打包为 ZIP 文件以便分发：

```bash
cd /path/to/plugins
zip -r my-plugin-1.0.0.zip my-plugin/
```

用户可以通过 URL 安装：

```bash
qwenpaw plugin install https://example.com/my-plugin-1.0.0.zip
```

### 常见问题

#### Q: 插件可以访问哪些 QwenPaw API？

A: 插件通过 `PluginApi` 访问核心功能，包括：

- Provider 注册
- Middleware 注册（`register_middleware`）
- Hook 注册
- 自定义命令注册（`register_control_command`）
- HTTP 路由注册（`register_http_router`）
- Runtime helpers（provider_manager 等）

#### Q: 插件可以修改 QwenPaw 的核心行为吗？

A: 可以，通过 `register_middleware`（注入 AgentScope middleware）、`register_control_command`、`register_tool`、runtime hooks 和其他 PluginApi 方法。请谨慎使用，确保不会破坏核心功能。

#### Q: 插件之间会冲突吗？

A: 如果多个插件注册相同的 provider_id 或 command_name，后注册的会覆盖先注册的。建议使用唯一的 ID。

### 示例插件

#### GPT Image 2 工具插件

一个为 QwenPaw agents 添加 OpenAI GPT Image 2 图片生成能力的工具插件。

**系统要求：**

- QwenPaw 最低版本：`1.1.5`

**安装方法：**

```bash
# 克隆 QwenPaw 仓库（如果尚未克隆）
git clone https://github.com/agentscope-ai/QwenPaw.git
cd QwenPaw

# 安装插件
qwenpaw plugin install plugins/tool/gpt-image2
```

**配置步骤：**

1. 安装完成后，重启 QwenPaw
2. 进入 Agent 设置 → 工具管理
3. 找到 "generate_image_gpt" 工具
4. 点击"配置"按钮，输入你的 OpenAI API Key
5. 启用该工具

**使用方法：**

配置完成后，agent 可以通过调用工具来生成图片：

```
用户: 请生成一张可爱的小猫在花园里玩耍的图片
Agent: [调用 generate_image_gpt 工具]
       [返回生成的图片]
```

**功能特性：**

- 支持多种图片尺寸：1024x1024, 1024x1792, 1792x1024
- 质量选项：low, medium, high, auto
- 自动验证 API Key
- Per-agent 配置（每个 agent 可以使用不同的 API Key）

更多详情请参考 `plugins/tool/gpt-image2/README.md`。
