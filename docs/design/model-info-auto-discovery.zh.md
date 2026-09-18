# ModelInfo 自动发现、模板补齐与 Free/Pro 同步方案

状态：用户已确认，实施与验收完成。2026-09-18。
分支：`fix/model-info-auto-discovery`，基于 upstream/main `79f8e7d30`。
背景：https://github.com/agentscope-ai/QwenPaw/issues/6167

用户已确认方案，并要求模块化重构、按 provider 将 ModelInfo JSON 内置到安装包。实现不新增旧格式兼容层。

## 1. 目标与边界

用户配置 API Key / endpoint / 协议后，不需要先查模型文档、手填 token 上限。
能从接口取到的信息自动获取；不能获取时按供应商目录或完整模型名模板预填。
免费模型自动更新且记住删除；付费模型自动发现，但是否加入常用列表由用户决定。

本次包含元数据、发现、同步偏好、相关配置 UI 和运行时上下文一致性。
不重写 issue 中独立的多模型 fallback、整个 selector 或 agent thinking 体系；只修正这些系统读取模型能力和构造输出预算时的必要连接点。

## 2. 必须拆开的三个维度

| 维度 | 决定什么 | 不决定什么 |
| --- | --- | --- |
| 协议：OpenAI Chat / Responses / Anthropic Messages 等 | 鉴权、请求字段、响应结构、分页、输出与 thinking 参数约束 | 不决定模型原厂、价格或上下文大小 |
| 服务：供应商、区域、endpoint、账号配置 | 可用模型、部署限制、套餐限制、API 返回元数据 | 同名模型不能跨 endpoint 当作同一份实测信息 |
| 计费：free / paid / unknown | 自动展示策略、免费变付费的处理 | 不能由是否有 API Key、模型原厂或协议推断 |

例如：自定义 Anthropic Messages endpoint 提供 qwen3.8-max。
参数发送走 Anthropic 适配器，能力模板来自 Qwen，不能套 Claude 的上下文与 thinking 能力。
同一个供应商可以同时有免费与付费模型。

## 3. 协议差异与修正

| 接入方式 | 发现 / 元数据 | 请求输出上限 |
| --- | --- | --- |
| OpenAI 官方 | `/models` 提供 ID 等基本信息，不能指望返回 token 上限；用模型目录补齐 | Chat 根据适配器能力使用 `max_completion_tokens` 或 `max_tokens`；Responses 使用 `max_output_tokens` |
| OpenAI 兼容服务 | 独立供应商适配器解析其真实扩展字段，不能认为所有服务字段都一致 | 按服务实际支持字段映射，不仅凭模型名判断 |
| Anthropic 官方 | 分页读取 `/v1/models`；解析 `max_input_tokens`、`max_tokens` 与已提供的 capabilities | Messages 必须构造 `max_tokens`；自动模式由适配器选默认预算并校验模型上限 |
| Anthropic 兼容服务 | 支持 models 时按其实际 schema 获取；不支持列表时允许手动输入模型 ID + 模板补齐 | 使用 Messages 请求结构，但不因为协议相同就给非 Claude 模型套 Claude thinking 参数 |
| OpenRouter | 解析 `context_length`、`top_provider.max_completion_tokens` 和定价信息 | 不把模型输出能力直接当成每次请求的输出预算 |
| 本地 Ollama / LM Studio | 优先服务实际加载的上下文 / runtime 配置 | 不套用云端模型模板夸大本地可用窗口 |

自动发现只请求目录 / 元数据接口。不通过发送真实 chat/messages 请求猜测上下文或检查收费模型。
“测试连接 / 测试模型”保留为用户主动操作，与后台自动发现分开。
列表返回 404/405 表示发现不支持，不直接宣称推理接口不可用。

官方依据：
- OpenAI Models：https://developers.openai.com/api/reference/resources/models/methods/list
- OpenAI Chat：https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- Anthropic Models：https://platform.claude.com/docs/en/api/models/list
- Anthropic Messages：https://platform.claude.com/docs/en/api/messages/create
- OpenRouter：https://openrouter.ai/docs/api_reference/overview

## 4. Token 语义与来源

需要分别表达以下概念，不能继续把它们都叫 max tokens：

1. Context window：模型整体上下文容量。
2. Max input tokens：服务明确声明的输入上限；没有则保持未知，不凭空编造。
3. Max output tokens：模型输出能力上限。
4. Request output limit：用户或适配器为单次请求设置的输出预算。

元数据归一化由各协议适配器负责，保留字段的真实语义。实现时收敛现有字段和调用点，不为本分支新格式增加兼容层。
若服务分别限制总上下文和输入，压缩预算同时服从两者；输出 / reasoning 预留由对应协议现有预算链路统一计算，避免重复扣减。
聊天用量展示、压缩阈值、配置框必须读取同一个有效值解析器。

每个能力字段独立记录 source / source reference / updated_at。一个模型可以是 API 提供上下文、模板补齐输出；不能只有一个整模型来源标签。
未知值保留 unknown/null。128K 只能标为“应用默认值”，不能伪装成模型真实能力或保证安全的上限。

按字段解析优先级：

`用户显式覆盖 > 当前 endpoint API > 精确供应商/区域/套餐目录 > 完整模型名模板 > 已维护的内置基线 > 应用默认值/未知`

API 只返回 ID 或省略某字段时，不能用空值冲掉已有有效元数据。
用户未改动的预填值不保存为 user override；恢复自动只删除用户覆盖，不销毁其下的 API / 目录信息。
API 返回的能力改变时，不重写正在运行请求的模型参数；新模型实例使用更新后的解析结果。

## 5. 模型名预填模板

### 用户流程

1. 选择协议、输入 endpoint 和 Key。
2. 接口能列出模型时展示候选；不能列出时允许输入完整模型 ID。
3. 输入 `qwen3.8-max` 后，匹配 Qwen 原厂模板，显示上下文、最大输出能力和“模型模板”来源。
4. 用户直接保存使用，也可以打开高级设置覆盖网关实际限制。
5. 后续接口返回真实值时，未覆盖字段自动采用 API 值，保留用户显式覆盖。

### 匹配规则

- 优先精确匹配服务目录，然后完整模型 ID；原厂模板与服务目录单独索引。
- 允许数据中明确维护的别名，不做 substring/模糊匹配，不因包含 `qwen`、`claude` 就套整族上限。
- 版本、后缀、免费路由标识、部署别名不能随意剥离。
- `deployment-123` 等无法识别的别名可由用户主动选择模板，原始请求 model ID 保持不变。
- 多个原厂候选冲突时不随意选第一条，提示用户选模板或保留未知。
- 模板不复制 API Key、价格、可用性、服务特定 thinking 参数或 beta header。
- 模板不意味着该 endpoint 已验证支持这些上限，UI 明确标记模板来源。

### 数据与更新

使用项目内可审查的精简快照保证离线可用；models.dev 作为补充目录来源，不当成所有服务的权威接口。
原厂/供应商专有能力优先于第三方目录；有条件启用的长上下文/beta 能力不能无条件生效。
后台每 24 小时更新公共元数据，校验后原子替换，失败保留上次成功数据。
记录来源和更新时间，保留来源许可证。公共元数据下载不带用户凭据。

## 6. 免费 / 付费同步策略

“发现候选”与“已启用模型”必须分开。后台同步不自动切换当前模型。

| 场景 | 自动发现时机 | 新发现模型如何出现 |
| --- | --- | --- |
| 已知免费服务 / 免费模型 | 启动时缓存过期刷新（建议 6 小时 TTL），手动刷新强制执行 | 经可信服务目录确认免费的模型自动展示，扣除删除与隐藏偏好 |
| 付费服务 | 保存有效凭据后自动发现；启动缓存过期刷新（建议 24 小时 TTL） | 候选列表自动出现，用户添加后进入常用/已启用列表 |
| 混合免费与付费服务 | 同一次发现获取模型级价格身份 | free 自动展示，paid/unknown 进入候选；不按供应商整体打免费标签 |
| 自定义服务 | 保存有效连接配置后尝试发现；不支持则使用手动 ID + 模板 | 默认价格 unknown，不因模型同名为免费而自动启用 |
| 无 Key 且需要认证 | 不发无效请求 | 展示已缓存/内置信息及“需要配置凭据” |

免费身份需要该 endpoint 的可信价格/服务契约；不能仅靠缺失价格、返回 0 的错误默认值或模型名字推断。
第三方模型模板不授予免费身份。套餐/额度内包含与永久免费也不混为一谈。

### 三方合并规则

- 同步更新远端事实，独立保留用户添加、置顶、隐藏、删除记录。
- 用户删除的模型，下次同步和重启都不能复活；只能主动恢复。
- 用户置顶不覆盖删除、计费变化或下架状态。
- 网络失败/超时/部分分页失败：保留已有目录，显示错误和最后成功时间；不按空列表批量下架。
- 完整成功同步后远端消失：标记“远端已下架/不再返回”，保留配置和偏好；免费自动列表停止默认展示，用户已配置项仍可查看。
- 免费变付费或免费身份无法确认：退出自动免费集合，保留配置并显著提示；原来自动启用的免费项不得静默产生付费请求，需用户主动重新启用付费使用。
- 新增收费保护若触及模型激活/调用路径，单独测试；不擅自自动改用其他付费模型。

缓存必须隔离 endpoint、区域、协议及凭据配置版本。更改连接配置后旧 API 数据不能继续冒充当前服务的已识别数据；模板和用户偏好可保留。
同步复用已有 revision / generation 机制防止旧请求覆盖新配置；限制并发并做超时，手动刷新与启动刷新合并，避免重复请求。

## 7. 前端呈现

默认显示模型信息摘要：

| 字段 | 展示方式 |
| --- | --- |
| 上下文 / 最大输入（若已知） | 有效值 + API/目录/模板/手动/默认来源 |
| 模型最大输出能力 | 能力值或未知，不与生成参数混为同一个输入框 |
| 单次输出预算 | 默认“自动”，高级设置中可覆盖 |
| 计费 | 免费 / 付费 / 未知，独立于协议和能力来源 |
| 同步状态 | 同步中、最后成功时间、失败原因、手动刷新 |

“自动”使用协议相关说明：OpenAI 可省略支持省略的参数；Anthropic 由适配器自动提供请求所需预算。
高级设置提供覆盖及恢复自动，不要求每个用户都看懂 token 参数才能添加模型。
沿用现有组件、Lucide 图标和布局，不在本次重设计整个设置页面。

## 8. 实施与验收 checklist

- [x] 从 upstream/main 建分支，读取 #6167 与现有代码。
- [x] 用户补充模型名模板需求，核对 OpenAI / Anthropic 官方 schema。
- [x] 用户 review 并确认本方案。
- [x] 先完成协议差异测试：OpenAI ID-only、Chat/Responses 参数、Anthropic 正确字段及分页、不支持发现的代理。
- [x] 实现字段级能力解析、模板匹配、缓存来源与更新，覆盖未知值和来源冲突。
- [x] 实现免费/付费候选与启用策略、删除记忆、下架与免费变付费处理。
- [x] 实现表单预填/来源/恢复自动；确保运行时与 UI 同源。
- [x] 验证协议与模型原厂交叉场景：Anthropic endpoint + Qwen、OpenAI endpoint + Claude，不能套错参数。
- [x] 验证同名不同 endpoint 的限制不串用、换 Key/URL 后旧同步不能回写。
- [x] 验证离线、坏缓存、无效元数据、同步失败不清空、分页失败不下架、本地模型不套云端模板。
- [x] QwenPaw conda 环境运行后端单测（明确 PYTHONPATH 指向本工作区）；前端单测、类型和格式检查通过。

## 9. 模块边界与内置 JSON

- `model_info.py`：模型身份、能力与用户配置的数据结构。
- `model_catalog.py`：统一 schema、随包目录、校验、缓存、原子更新。
- `model_metadata.py`：endpoint 精确匹配、模型名模板与歧义处理。
- `model_resolution.py`：字段级优先级和来源，UI 与运行时共用。
- `model_sync.py`：同步 TTL、免费自动展示、删除偏好、下架与计费变化。
- 各 provider adapter：只解析协议原生字段、映射请求参数。

`providers/data/model_catalog.json` 是唯一随包 ModelInfo 目录，schema_version=2。
删除了草稿中的独立 model_metadata.json，不保留新格式的兼容层。
按实际 provider ID 分组，32 个服务目录；区域/套餐分别维护，模板仅提取能力。

结构示例（数值仅展示当前目录中该条目的快照）：

```json
{
  "schema_version": 2,
  "catalog_version": "2026.09.18.1",
  "providers": {
    "dashscope": {
      "api_urls": ["https://dashscope.aliyuncs.com/compatible-mode/v1"],
      "remote_id": "alibaba-cn",
      "template_owner": true,
      "template_model_ids": ["qwen3.8-max"],
      "template_families": ["qwen", "qwen3.6", "qwq", "qvq"],
      "default_model_ids": ["qwen3.8-max"],
      "models": [{
        "id": "qwen3.8-max",
        "name": "Qwen3.8 Max",
        "max_input_length": 1000000,
        "max_output_length": 131072
      }]
    }
  }
}
```

`default_model_ids` 与完整目录分离，模板增加不会膨胀默认已启用列表。
`template_model_ids` 明确模板原厂范围，避免把 DashScope 托管的 DeepSeek 当成 Qwen 原厂模板。
`template_families` 仅供远程目录导入时识别原厂记录；运行时依然只按完整 ID 匹配，不按家族猜测数值。
远程缓存使用同一 schema、只补充能力，不修改用户默认展示名单。
`providers/data/**` 已在 setuptools package-data 中，另包含 models.dev MIT 许可证。

已核对 Anthropic 官方上下文文档：Sonnet 4.5 的标准窗口为 200K，
与 models.dev 的 1M 数据冲突。对应记录使用字段级 documentation 来源固定官方值；
远程导入保留这一有文档依据的修正，当前 endpoint API 返回值仍优先。
来源：https://platform.claude.com/docs/en/build-with-claude/context-windows

## 10. 验证记录

测试使用 `PYTHONPATH=src conda run -n QwenPaw`，避免引用其他工作树已安装的包。

- 后端 provider 单测、发现路由单测与模型管理集成测试：727 passed，1 skipped。跳过项依赖大小写敏感文件系统，当前 macOS 文件系统不支持。
- 前端模型配置相关测试：6 个文件、121 项全部通过。
- TypeScript 类型检查、修改文件的 Prettier、Python Black / Flake8 检查通过；遵循本项目 f-string 要求，Flake8 忽略 F541。
- 核心 7 个 Python 模块的定向 Mypy 检查通过，沿用检查命令中显式忽略的既有类型问题类别，不代表全仓严格类型检查。
- wheel 构建通过；读取产物逐字节核对能力模块、JSON 目录和许可证与工作区一致。目录版本 `2026.09.18.1`，包含 32 个 provider。
- `git diff --check` 通过。
