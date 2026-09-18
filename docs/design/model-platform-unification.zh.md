# 模型能力、协议适配与目录维护统一方案

状态：核心实现与本地验收完成，提交前最终复核。2026-09-18。实际模块、验证数据与外部验证边界见 [验收记录](model-platform-validation.zh.md)。
分支：`fix/model-info-auto-discovery`。
本方案扩展并修订 `model-info-auto-discovery.zh.md`；上一阶段测试结果不代表本次新增范围已经完成。
用户批准实施；在线模型生成仅按 CI 有界 canary 约束执行。

## 1. 已核实的缺口

| 入口 | 当前行为 | 本次处理 |
| --- | --- | --- |
| provider 目录 | 单 JSON；`provider_catalog.py` 在模块导入时展开多家模型列表 | 分片、按需加载、延迟构造 provider |
| Hub | 独立 ModelBody、别名能力映射；上游仅 Chat Completions；请求字段白名单未包含缓存控制 | 共用能力解析和协议策略，保留组织授权与预算边界 |
| ACP headless 自定义模型 | `runtime_provider.py` 只读取输入/输出整数；输出固定生成 `max_tokens` | 共用覆盖 schema、模板、协议参数映射 |
| selector | 前端仍用 `is_free` 二分；免费自动模型没有质量门槛 | 后端统一候选/可选策略，未知计费独立展示 |
| 多模态探测 | OpenAI 探测把部分 API/网络错误变成 False，manager 持久化 | 三态能力 + 独立探测结果，失败不污染能力 |
| OpenCode | 后缀识别免费；类中硬编码两个下架 ID；未找到会话头注入 | 动态目录、数据化异常记录、请求级会话上下文 |
| 模型适配 | 已有 OpenAI 正式子类；Anthropic 使用动态内部类；行为散落 factory/provider/formatter | 整理为正式 AgentScope 模型子类和可组合策略 |
| 缓存 | 已有 usage 统计；不能据此认定各协议参数及响应头已打通 | 请求、格式化、响应 usage/诊断完整契约测试 |

## 2. Python 类型 + provider 分片数据

推荐 Python 定义强类型 model card，JSON 保存可更新的声明式数据。业务只拿类型对象。
Python 常量也可以缓存，但模块导入会构造对象、导入依赖，不天然比分片 JSON 更快。
使用 JSON 的主要原因是同一 schema 能服务安装包、远程更新、CI 差异报告和前端，不需要执行远程代码。

建议结构：

```text
providers/
  model_info.py               # 强类型能力、价格证据、用户覆盖、解析结果
  catalog/
    loader.py                # resources 读取、分片校验与进程缓存
    resolver.py              # 字段级解析、身份与精确模板匹配
    sync.py                  # 目录更新、价格/下架状态
    selection.py             # selector 准入与手动添加策略
  adapters/
    openai_chat.py           # AgentScope OpenAIChatModel 子类
    openai_responses.py      # AgentScope OpenAIResponseModel 子类
    anthropic.py            # AgentScope AnthropicChatModel 正式子类
    request_context.py      # 会话/组织/请求上下文
    cache_policy.py         # 协议相关缓存参数与断点
    usage.py                # provider usage 与响应诊断归一化
  data/
    index.json              # provider 路径、分片版本/hash、精确模板定位
    providers/
      openai.json
      anthropic.json
      dashscope.json
      openrouter.json
      opencode.json
    selection_policy.json   # 质量阈值及其指标版本
```

模块名以实现时最小合理拆分为准，不增加通用插件框架或大量空基类。
一个 provider 一个文件，模型记录不复制到另一份完整总表。
跨供应商模板索引由构建工具生成，仅保存 ID 到原厂分片位置的映射。

加载约束：

- 启动只读取轻量索引；provider 描述信息与完整模型列表分离，移除导入时展开全目录的行为。
- 精确模型查询只加载命中的 provider/模板分片；完整目录管理页才允许显式遍历。
- 同一版本分片每进程校验和解析一次；缓存不可变快照，调用方配置另存，避免共享实例污染。
- 远程更新按分片版本/hash 获取；临时写入并校验完成后原子切换索引；失败保留上一版。
- 使用 package resources 和平台无关路径，验证 wheel、Windows/Linux/macOS。
- 本分支刚引入的目录格式直接替换，不为草稿格式增加兼容层；既有用户配置只迁移确有必要的字段，保留明确覆盖与删除偏好。

## 3. 一个身份，多类信息，不混用优先级

模型身份包含 provider、endpoint、wire protocol、模型 ID；模型能力另关联明确的原厂 template ID。
不能凭别名猜原厂，不能因为名称是 Claude 就把 OpenAI endpoint 改走 Messages。

| 数据 | 内容 | 规则 |
| --- | --- | --- |
| 能力 | context window、max input/output、image/audio/video、tools、thinking、structured output | 三态或 nullable；每字段记录来源/时间；用户覆盖 > endpoint 明确能力 > 服务目录 > 原厂精确模板 > unknown |
| 价格与访问 | free/paid/unknown、单价/单位/币种、需要鉴权、套餐/额度、有效期 | endpoint/套餐特定，不能从原厂模板继承免费，也不能让用户手动勾选变成“已核实免费” |
| 可用性 | available、missing、temporarily unavailable、unknown | 与价格、质量分离；失败不等于下架 |
| 推荐策略 | 质量分、指标版本、评测日期、手动/自动加入 | 决定自动 selector 展示，不改变能力和价格事实 |
| 用户配置 | 请求输出预算、能力覆盖、template ID、缓存偏好、删除/隐藏偏好 | 单独存储，可恢复自动；同步不覆盖 |

组织策略和确定的 endpoint 硬上限最后约束请求；用户覆盖不能绕过 Hub 授权/预算。
context window 与输入上限不合并成一个字段；运行时按协议预留输出/思考预算及消息开销，避免把全部窗口当输入额度。

多模态改为 image/audio/video 各自 supported/unsupported/unknown。
401/403、429、超时、5xx、结果无法判定只更新诊断，不写 unsupported。
只有明确的模态拒绝才作为 endpoint 级负向证据，带 TTL；不修改原厂模板，不覆盖手动设置。
换 Key/URL/协议使旧 endpoint 观测失效；异步探测沿用 revision 校验，防止旧结果回写。
有可靠模板时不自动生成探测；未知默认保留未知，用户可手动测试及设置。

## 4. Free/Pro、质量门槛与 selector

目前分支：OpenRouter 根据远端 pricing 判定；OpenCode/Kilo 优先 isFree/is_free，缺失时用服务特定后缀。
内置 is_free、provider 的 is_free_tier、下架 ID 仍参与行为，尚未做到完全由证据驱动。

改造后：

- 优先远端价格/明确免费标记；文档约定的后缀只在对应服务内使用，作为带来源的证据。
- 价格缺失/非法/过期/冲突为 unknown。订阅内含额度、试用余额、BYOK 不等于公开免费推理。
- 内置价格只作为快照，带 checked_at/有效期；首次网络失败不把陈旧快照当实时已验证免费。
- 免费转付费/unknown 或明确下架，暂停自动加入模型；已创建模型实例、重试和 fallback 都检查。
- 保留已手动添加的选择；价格风险需要明确确认，不自动切换付费替代模型。
- 后端返回候选、可选、未自动推荐原因；Console、ACP、CLI、定时任务共用，不各自二分推断。

建议自动推荐门槛（待 review）：AA Intelligence Index v4.3 >= 40，实测非估计、模型身份明确，并确认支持工具调用、endpoint 可访问、计费为有效免费。
该门槛是本产品推荐策略，不是 AA 对模型是否可用的定义。
用户提供页面当前 GLM 5.3 Flash 为 42、Step 3.7 Flash 为 19（估计）；据此建议 40 作为初始门槛。
记录 metric/version/score/estimated/evaluated_at/source/model mapping；版本改变后重新审核，不能跨版本直接比较。
无成绩、估计成绩、匿名模型、路由器动态别名、低于门槛仅列为可手动添加候选。
已经手动添加的模型不因排名变化被删除；默认选择也不随榜单自动切换。
AA 分数采用可追溯的审核快照，不让应用启动依赖抓排行榜；合法可用的数据接口另行接入。

## 5. 全入口覆盖

| 场景 | 接入方式 | 验收重点 |
| --- | --- | --- |
| 个人设置/Chat selector | 同一 resolved model card + selection policy | 源、自动预填、手动覆盖、候选不刷屏 |
| Hub 管理端 | 按连接解析上游能力，管理员设置组织限额并发布 | 自动补全不自动授权、不自动扩大预算 |
| Hub runtime | 下发安全的 resolved card + policy revision，保持别名 | 不泄露上游 Key/URL，不用别名猜模板 |
| Hub gateway | 复用协议适配策略；内置 provider 复用自己的默认协议；仅自定义连接选择 Chat/Responses/Messages | 请求白名单、按协议 usage 归一化、预算预留结算、断流/取消不能漏账 |
| ACP server 模型列表/切换 | 共用可选列表和会话模型解析 | 与 Console 一致，跨 session 不串配置 |
| ACP headless runtime 自定义模型 | QWENPAW_MODEL_INFO_JSON 解析为共用 overrides；支持 template、模态、协议配置 | max output 能力与生成预算分离；不写全局 provider 配置 |
| 外部 ACP harness | 使用其公开模型/配置能力，保留能力边界 | 不将本地 ModelInfo 冒充外部 agent 已支持的设置 |
| CLI/TUI、/model、Cron、Agent 默认、fallback/压缩/辅助调用 | 审计并接入同一解析结果/请求上下文 | 实际选中模型决定预算/模态/计费；不是一直使用 primary 元数据 |
| 本地 Ollama/LMStudio 等 | endpoint 本地信息优先 | 不套云端价格，不误加云端上限 |

Hub 当前只支持 Chat，增加上游 Responses/Messages 必须连同流事件转换、工具调用和预算契约一起完成，不能只扩大下拉列表。
Hub runtime 的现有 Chat 入口可保持不变，由 gateway 转换受支持的公共能力；不能表达的能力明确拒绝，不静默丢参数。

## 6. 正式 AgentScope 适配层与 provider 特性

保留 AgentScope 模型接口和已验证的工具/流行为，把现有 Compat 实现逐步迁入三个正式子类。
provider 负责连接和模型目录；适配器负责 wire protocol；provider policy 提供特定 header、参数支持与 usage 解析。
不建立每个品牌一套重写的模型类，也不修改全局 SDK 或全局 monkey patch。
Gemini/DashScope/本地 adapter 做能力与 usage 契约审计，有实际缺口才修改。

请求上下文包含 organization/runtime/conversation/request 标识，用 request-scoped/ContextVar 方式传递，不写进共享 client 的 default_headers。
同一对话跨工具轮、重试及辅助调用保持会话 ID；不同对话/组织隔离；新子对话按真实生命周期单独建 ID。

- OpenCode #7531：Go/适用 Zen endpoint 注入稳定 x-opencode-session 和 QwenPaw 自身 User-Agent；覆盖直接调用、自定义 endpoint、Hub、ACP 与辅助请求。官方 Go 文档已明确该要求。
- OpenAI Responses：按 GPT-5.6 等实际 capability 支持 prompt_cache_key、prompt_cache_options 和 input block 的 prompt_cache_breakpoint；参考 #6668 的请求体兼容方式，核对当前固定 SDK。旧模型及第三方兼容服务不得直接假设支持。
- Anthropic：独立支持 cache_control 自动/显式策略、tools/system/messages 的正确断点、TTL/数量/最小长度约束；根据官方能力限定，不能只因 wire protocol 是 Messages 就假设模型支持 Claude 缓存。
- DeepSeek：官方 usage.prompt_cache_hit_tokens/miss_tokens 为计数依据。x-ds-cache-status 如存在作为可选响应诊断；目前核对的官方缓存文档未确立该 header 的通用契约，不依赖它计算 token。
- OpenRouter 等聚合服务：同时检查路由提供的 supported_parameters 与实际模型/服务协议；不把原厂缓存控制盲目透传给所有代理。
- 统一 cache read/write/input/reasoning/output usage，流/非流各自验证；避免累计流事件重复计数。Hub 组织预算仍按原规则结算，缓存折扣不偷偷改变 token 限额。

缓存断点针对实际稳定前缀，不标记每轮变化的最新用户/工具消息；缓存策略由用户/组织明确配置，有来源和降级原因。
本次不包括 previous_response_id 的完整跨会话持久化、自动跑昂贵 benchmark、重写整个 AgentScope 或全部前端。

## 7. 低消耗目录巡检 CI

新增 `.github/workflows/model-catalog-canary.yml`，脚本和 fixture 放 `scripts/model_catalog/` 与 `tests/contract/providers/`。
默认分支相关路径 push（合并后）+ workflow_dispatch + 每周定时；PR 只跑离线契约。在线 workflow 不订阅 pull_request 或 pull_request_target，手动触发也限制默认分支。

| 层次 | 请求预算 | 结果 |
| --- | --- | --- |
| 无 Key 目录巡检 | 每 provider 一次公开 models GET；有分页时设置总请求上限并记录完整性 | 增删 ID、价格、协议、能力差异 artifact |
| 无 Key 推理 canary | 仅已确认允许匿名的固定 provider/model/endpoint/protocol；每 provider 最多 1 个，全局最多 2 次；串行 | 真实请求和响应结构、有效文本/工具结果、header 契约 |
| 需 Key 的免费模型 | 用户愿意提供一个或多个专用 Key；独立 job，无 secret 默认不执行，匿名与鉴权生成共用每次运行最多 2 次总预算 | 明确报告 skipped_requires_auth，不能当推理已通过 |

固定 prompt <= 64 输入 token，输出上限 32 token；若模型强制较大 thinking 最小预算则不进入默认 canary。
SDK retries=0，单请求 20 秒、job 5 分钟、concurrency 防重叠；失败不遍历候选、不随机换模型、不回退付费。
pin exact ID，不用随机 free router/latest 自动替代。免费价格和匿名访问资格在生成前检查；目录读取失败即跳过生成。
200 但空输出/截断无法判断与真正成功分开；401/403 为鉴权/访问变化，429/超时/5xx 为 inconclusive。
404 或明确下架为目录漂移候选；一次不完整分页或临时失败不能删目录。
产出 job summary、JSON 差异与建议更新分片，维护者 review 后更新；CI 不直接修改默认分支或自行扩大名单。
pin 清单与运行时推荐清单分开：可用性探针不代表质量认证。

GitHub 配置交付约定：实施完成后提供逐项设置清单。暂定 Secrets 为
`MODEL_CANARY_OPENROUTER_API_KEY`、`MODEL_CANARY_OPENCODE_API_KEY`，
如纳入 Kilo 则使用 `MODEL_CANARY_KILO_API_KEY`；只要求为实际启用的 provider 配置。
暂定 Repository Variable `MODEL_CANARY_ENABLED=true` 控制定时在线测试，workflow_dispatch 可选择经过仓库 pin 清单验证的 provider。
最终名称以提交的 YAML 为准，交付时明确必需/可选、路径及手动触发方法。
Key 只注入对应 job，不打印 header/原始异常体，不落 artifact；workflow 最小权限 `contents: read`。
含 secret 的 job 仅在受信任默认分支 schedule/workflow_dispatch 运行，不运行 fork PR 代码、不使用 pull_request_target 执行 PR 内容。
固定模型变成付费或价格无法核实即不生成；有多个 Key 也不增加总预算、不轮换 Key 绕过限流。

OpenRouter 公开 models 目录可无 Key 获取，免费模型推理仍按官方认证要求使用 Key；不能承诺所有免费 provider 都有匿名推理。
本轮未进行生成请求，具体匿名 pin 在实施时以当前服务规则及最小实测确认；若没有合格项，明确报告无匿名 canary，不伪造通过。

## 8. 实施顺序与验收 checklist

- [x] 阅读 #7531、#6649、#6668 与相关 #882；核对 Hub/ACP/selector/多模态路径。
- [x] 核对 OpenAI、Anthropic、DeepSeek、OpenCode 官方文档与 AA 对比页面。
- [x] 用户确认扩展方案；要求每个 provider 独立类实现能力、价格、可用性、推荐与协议请求策略。
- [x] A：类型/分片/加载重构；证明单模型查询不解析所有分片，同版本仅解析一次；记录冷/热加载耗时与峰值内存。
- [x] B：能力、计费、质量与选择策略；测价格异常、免费转付费、删除记忆、模态探测失败、手动覆盖。
- [x] C：正式适配器、请求上下文、OpenCode 会话头、三种缓存协议和 usage；测并发隔离、取消、流/非流、参数不能跨协议。
- [x] Hub 协议归属：内置连接复用原 provider 类及其协议；只有自定义连接显示协议选择；连接发现、能力解析与网关使用同一工厂。新增每个内置 provider 的协议与实例隔离测试、自定义三协议测试、表单显隐测试。
- [x] D：Hub、ACP、Console、CLI 共用解析与 provider 策略；验证组织凭证、预算结算、原生协议、手动覆盖。会话上下文覆盖 Agent 回复链；TUI/Cron/辅助调用沿用统一 model factory 与 provider 请求策略。
- [x] E：目录巡检、固定 pin、合并后 CI、离线故障矩阵、总量限制与零重试检查；无 Key 公开目录已核查。
- [ ] 外部验收：配置目标仓库 canary Secrets 后执行真实生成；本机未配置 Key，生成明确跳过。
- [x] F：QwenPaw conda 后端、前端、类型/格式、本地 macOS、wheel/sdist 分片打包核验。
- [ ] 外部验收：Windows/Linux 由现有 nightly matrix 执行；本机未运行其他操作系统，不能标记为通过。

每阶段独立检查，最后整体验收；不能用上一阶段 727/121 的结果覆盖新增范围。

## 9. 依据

- https://github.com/agentscope-ai/QwenPaw/issues/7531
- https://github.com/agentscope-ai/QwenPaw/issues/6649
- https://github.com/agentscope-ai/QwenPaw/pull/6668 （调查时 OPEN）
- https://github.com/agentscope-ai/QwenPaw/pull/882 （历史会话亲和方案，调查时 CLOSED）
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://api-docs.deepseek.com/guides/kv_cache/
- https://opencode.ai/docs/go/#where-can-i-use-it
- https://opencode.ai/docs/zen/
- https://openrouter.ai/docs/quickstart
- https://openrouter.ai/docs/api/api-reference/models/get-models
- https://artificialanalysis.ai/models/comparisons/glm-5-3-flash-vs-step-3-7-flash

## 10. 用户确认的架构修订

每个内置 provider 使用明确的类（区域/套餐可复用同品牌基类），暴露独立的能力、价格、可用性、推荐资格方法。provider 负责配置 AgentScope 正式协议子类；二者构成完整模型提供者实现。公共方法可继承，但品牌特有免费识别、缓存策略及协议限制在其类中声明/实现，不在中央按 ID 堆条件。逐家核对官方缓存文档，未确证的能力保持未知。

评分数据采用独立 model_rankings.json，model card 精确关联 ranking_id，解析后附带评分证据；阈值仅存一份。未知或估计成绩仅手动添加，例外必须有来源、理由与复核日期。

Hub 修订：内置 provider 直接复用现有类并推导 wire protocol，只有自定义连接选择协议；Hub 无独立供应商规则。
