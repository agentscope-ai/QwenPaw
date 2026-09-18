# Model platform：实现边界与验收

## 配置与维护

目录位于 `src/qwenpaw/providers/data/`：`index.json` 保存提供商路径、SHA-256、精确模板 ID 与默认模型摘要；完整 model card 分别保存在 `providers/<provider>.json`。启动加载默认摘要，不读取全部完整分片；完整元数据按提供商惰性读取并缓存。默认摘要是为了启动性能保留的派生数据，修改分片后必须同步生成摘要和哈希。运行 `python scripts/model_catalog/reindex.py` 后执行目录单测。

远程目录刷新先写入不可变、按内容哈希命名的分片，再原子替换索引。下载、解析、哈希校验失败保留上一版。`models.dev` 用于能力补全，不作为 endpoint 的价格、可访问性或免费证明。自定义 endpoint 只做精确名称匹配；有歧义时需用户指定 `provider/model-id` 模板，不能从相近型号推断容量。

排行榜独立保存在 `model_rankings.json`。当前策略为 Artificial Analysis Intelligence Index v4.3 ≥ 40，且必须有工具调用能力、免费证据及可用连接。估计分数、没有评分的模型不自动进入选择器，仍可手动添加。评分关联通过 model card 的 `ranking_id` 完成；免费价格和评分不互相推导。当前只收录本次核对过的两条评分证据，不伪造其余模型的成绩。远程价格证据超过 24 小时不再用于自动推荐。

用户明确添加优先于推荐过滤，并持久化；删除和隐藏不会被下次同步自动撤销。OpenCode 不再使用代码内永久封禁模型 ID 的列表，发现结果与连接检查共同表达可用性。

## 请求与协议

Hub 内置连接直接复用提供商类。自定义连接才需要选择 Chat Completions、Responses 或 Anthropic。Hub 的原生协议桥转换请求、工具调用、流事件和 usage，同时保留预算、组织鉴权与断流结算。组织发布的输出上限还会被实际 model card 输出能力收紧。

OpenCode 的不同模型确实使用不同协议，已按 [官方 endpoint 表](https://opencode.ai/docs/zen/) 固定精确路由；Responses / Messages 复用对应 provider 实现。目录中的 Gemini 原生路由暂不由 Hub 的三协议桥承载，明确报不支持，不伪装成 Chat Completions。

ACP 的 `QWENPAW_MODEL_INFO_JSON` 可设置 `protocol`、`template_id`、模态/工具能力和上下文、输出限制；配置仅保留于当前 runtime，不写入个人 provider。Hub 与个人设置均支持能力的自动/支持/不支持三态。401、429、超时、模型未识别探测内容不等于不支持多模态。

## 缓存策略核对

| 提供商 | 本次处理 | 依据与边界 |
| --- | --- | --- |
| OpenAI / Responses | 按模型验证缓存参数；GPT-5.6 显式断点、`prompt_cache_options` 走 SDK extra body；保留读写 token | [官方缓存文档](https://developers.openai.com/api/docs/guides/prompt-caching)；不把 Responses 参数塞进其他协议 |
| Anthropic | `cache_control` 与静态 system 前缀断点；保留原生 usage | [官方缓存文档](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| DeepSeek | 隐式缓存，保留 hit token；若返回 `x-ds-cache-status` 则记录诊断，支持流式和非流式 | [官方 KV cache 文档](https://api-docs.deepseek.com/guides/kv_cache/) 的 token 数是计费依据，响应头不用于猜测 token 数 |
| OpenRouter | 按 routed vendor 区分缓存语法；稳定 `x-session-id`；保留 cache read/write | [官方缓存指南](https://openrouter.ai/docs/guides/best-practices/prompt-caching) |
| OpenCode | 稳定 `x-opencode-session` 与 QwenPaw User-Agent；模型协议路由 | [Go](https://opencode.ai/docs/go/) / [Zen](https://opencode.ai/docs/zen/)；不同会话不共享 header 状态 |
| Kilo | 稳定 `X-KiloCode-TaskId`，不虚构 Anthropic 显式缓存能力 | [认证与头字段](https://kilo.ai/docs/gateway/authentication) |
| MiniMax | 已核对 M2、M2.1、M2.5、M2.7 及对应高速版本的 Messages 显式缓存 | [官方文档](https://platform.minimax.io/docs/api-reference/anthropic-api-compatible-cache)；未核对型号不自动套用 |
| Zhipu / Z.AI | 隐式缓存，读取 `prompt_tokens_details.cached_tokens` | [官方文档](https://docs.z.ai/guides/capabilities/cache) |
| SiliconFlow | 保留兼容协议 usage 的缓存计数；不注入显式 marker | [API 文档](https://docs.siliconflow.cn/docs/api/chat-completions-post) |
| Azure OpenAI | 服务端隐式缓存；不沿用 api.openai.com 的 GPT-5.6 显式策略 | [官方文档](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/prompt-caching) |
| Gemini | 继续使用原生 GenerateContent 配置与 usage；已有 `cached_content` 配置可透传 | [官方指南](https://ai.google.dev/gemini-api/docs/caching)；不创建需要单独计费和生命周期管理的缓存资源 |
| DashScope / Aliyun 套餐 | 保留原生/兼容 usage 与 provider 配置；套餐不自动插入未经逐型号确认的显式断点 | [文档入口](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/context-cache)，本轮读取受页面大小限制，不能把主站能力泛化到所有套餐 |
| Kimi、MiMo、Volcengine、ModelScope、QwenPaw 服务 | 独立 provider 类，缓存参数能力保持未知；保留上游兼容 usage | 没有取得足够的逐 endpoint 显式缓存契约，不因模型名称相似开启别家语法；服务端隐式缓存无需客户端开关 |
| Ollama / LM Studio | 继续使用本地服务能力与运行时容量，不套用云端容量和价格 | [Ollama API](https://docs.ollama.com/api/chat)、[LM Studio 缓存实现](https://lmstudio.ai/blog/mlx-engine-agentic-workloads)；本地 KV cache 不等于云 API 免费价格证据 |
| GitHub Models | 保留已有配置，不新增缓存或免费推荐假设 | [官方页面](https://docs.github.com/en/github-models) 已提示服务下线；不能把 Copilot 缓存文档当作 Models API 契约 |

## GitHub canary 设置

在目标仓库 **Settings → Secrets and variables → Actions** 配置：

- Repository Variable：`MODEL_CANARY_ENABLED=true`。
- Repository Secret：`MODEL_CANARY_OPENROUTER_API_KEY`。
- Repository Secret：`MODEL_CANARY_OPENCODE_API_KEY`。
- 如启用 Kilo，Repository Secret：`MODEL_CANARY_KILO_API_KEY`。

只需设置要执行生成检查的 provider 的 Key。没有 Key 的 provider 仍读取公开目录，但生成明确记录为 `skipped_requires_auth`。当前没有已验证的匿名生成 pin，不使用伪造 Key，也不将跳过计为通过。

`.github/workflows/model-catalog-canary.yml` 只在默认分支的相关 main push、每周定时或默认分支手动触发时运行。没有 `pull_request` / `pull_request_target`，不会执行 fork PR 代码。PR 仍通过现有 Tests workflow 运行离线 MockTransport 单测。Windows/Linux/macOS 使用现有 nightly matrix；本地 macOS 测试不能代替未运行的其他操作系统结果。

固定模型及 session header 位于 `scripts/model_catalog/canary_pins.json`。每个 provider 一次目录 GET；全 job 最多两次生成，每次最多 32 个输出 token，零重试。按 run number 轮换顺序，避免第三个 provider 永远无法抽检。价格未知、转付费、目录缺失时不生成；429/5xx 记为 inconclusive。目录增删出现在 artifact 与 summary 计数中，供人工更新，CI 不直接改模型名单或评分。

手动操作：Actions → Model catalog canary → Run workflow → 默认分支。查看 `model-catalog-canary` artifact。仅巡检目录可运行 `python scripts/model_catalog/canary.py --output <path>`；加 `--generate` 才尝试生成。

## 本地验收记录

结果在 commit 前和 push 后分别执行并记录于本文件末尾。测试不使用实际 API Key。公开目录巡检验证了三个 pin 的存在与免费字段，生成因未配置 Key 跳过，未消耗模型 token。

本地 macOS / conda `QwenPaw`：

- providers、Hub、ACP runtime、provider discovery router、canary、CLI：**1997 passed，4 skipped**。
- Console Models + Hub：**204 passed**；`tsc -b --noEmit` 通过。
- 修改涉及的 69 个 Python 文件：mypy 通过；flake8 通过；Black 按 79 列格式化。Literal 类型参数使用真正的字符串字面量，运行时新增字符串遵循项目 f-string 约定；flake8 的 F541 对应约定放行。
- wheel 和 sdist 均包含全部 **32** 个 provider 分片、索引、排行榜和来源许可证；归档内分片 SHA-256 全部通过。
- 目录基准（单进程、tracemalloc，本机一次冷加载，不代表全应用启动时间）：默认摘要 200 cards / 3.07 ms / 1029 KiB；单个 Anthropic 分片 14 cards / 3.13 ms / 432 KiB；完整目录 1032 cards / 30.42 ms / 3836 KiB。缓存命中的单提供商 lookup 均值约 0.07 μs（1000 次）。
- 无 Key 公开目录 canary：OpenRouter、OpenCode、Kilo 的固定模型通过免费字段核查；均为 `skipped_requires_auth`，没有进行推理调用。

Hub 三协议桥目前转换文本、图片、工具调用；原生 Responses / Messages 路由不发布 audio/video 为可用能力，避免模板宣称支持但网关无法转换。Chat Completions 透传保留服务自身模态能力。此处是网关传输能力限制，不回写或否定原模型的 model card。

`b7124742c` 推送后合并回归：**2159 passed，4 skipped**；前端再次 **204 passed**，TypeScript 通过。随后资源地址复核发现并修复原生 Messages 的 `/v1` 拼接差异：统一 provider 的 `request_url` 与 SDK base URL 处理，涵盖 Anthropic 根地址、MiniMax `/anthropic` 前缀和 OpenCode `/zen/v1`。新增协议一致性测试，并将 OpenCode/Kilo 纳入 Hub 内置 preset；这组补充回归 **112 passed**。Hub 组织连接仍要求管理员配置组织 API Key，免费计费与免认证不是同一个概念。
