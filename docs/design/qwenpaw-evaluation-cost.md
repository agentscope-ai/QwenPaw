# QwenPaw Evaluation 费用口径

TL;DR：优先使用服务端报告的 cost，缺失时调用 LiteLLM `completion_cost`；LiteLLM 无法计算时，使用冻结的官方价格快照 × token usage 独立兜底，逐次累加到任务。仅当兜底也缺少必要用量或适用费率时才标 unknown。首期直接调用百炼，不部署计费代理，固定依赖版本和价格快照。缺失不是零，估算不是账单实付。此文件定义实现口径，不表示费用链路已验收。

## 已确认的实现选择

1. `reported cost → LiteLLM completion_cost → official price snapshot × token usage → unknown`，分别记录 `reported`、`litellm_estimated`、`snapshot_estimated`、`unknown` 来源。每次调用只选一个费用结果，不重复相加。
2. 使用 provider 对应的真实 usage；缓存与 reasoning 由 LiteLLM 支持的字段传入。不得将 context occupancy 当累计计费 token。
3. 百炼模型使用百炼地域和服务模式对应的官方价格。缺失价格通过 LiteLLM 模型价格注册机制补充；缓存价格不能仅靠输入/输出两个自定义单价表达。
4. `scripts/bench/` 负责 usage 提取、费用来源选择、价格注册、快照公式兜底和汇总。快照兜底独立于 LiteLLM：即使 LiteLLM 不识别模型或计算失败，只要官方费率和必要 usage 齐全，仍须计算估算费用。
5. 只有完整且适用的 usage/费率才能生成可比较估算。缓存信息缺失可标记保守估算；无法确定计费条件时保留 unknown。区间展示不是首期必需项。
6. LiteLLM 仅进入隔离的评测环境，固定版本；不改变 QwenPaw 产品依赖或 API 调用路径。

## 已核实的参考实现

核查日期：2026-10-08。以下是固定 commit 的源码证据，不代表线上 Index 每条历史记录都使用该版本。

- [SDK telemetry](https://github.com/OpenHands/software-agent-sdk/blob/69e26889401fe69157fff536e6a69049e6644cb3/openhands-sdk/openhands/sdk/llm/utils/telemetry.py)：`_compute_cost` 优先读响应隐藏元数据中的代理费用 header，缺失时调用 LiteLLM `completion_cost`。支持自定义输入/输出 token 单价，计算失败返回 None。usage 单独记录输入、输出、缓存读写、reasoning；逐次响应费用累加到 metrics。
- [单题代理计费](https://github.com/OpenHands/benchmarks/blob/405bae7140d7e961a75f4910a0b2e7069731db96/benchmarks/utils/litellm_proxy.py)：配置代理时，每题创建独立 virtual key，查询其 spend。未配置代理则不启用此路径。代理统计不是云厂商最终账单的证明。
- [评测恢复与代理查询](https://github.com/OpenHands/benchmarks/blob/405bae7140d7e961a75f4910a0b2e7069731db96/benchmarks/utils/evaluation.py)：代理费用暂缺或为零会重查；异常分支也尝试恢复统计。
- [成本汇总](https://github.com/OpenHands/benchmarks/blob/405bae7140d7e961a75f4910a0b2e7069731db96/benchmarks/utils/report_costs.py)：区分最终输出与包含多次尝试的 critic 文件；有全尝试记录时使用其总和，避免再加一次最终输出而重复计费。

本项目采用逐次计价和全尝试独立统计。不能只看到 SDK 的 accumulated_cost 为零就认定免费：其累加器只累加正费用，缺失计价可能不会增加总额。

## 计算公式

针对当前百炼 OpenAI-compatible 实时调用、仅隐式缓存的范围：

```text
C_request = ((I - H) × P_input + H × P_cache + O × P_output) / 1,000,000
C_attempt = Σ C_request
C_task_execution = Σ C_attempt（包括基础设施失败后的允许重试）
C_benchmark = Σ C_task_execution / N_tasks
C_index = (C_GAIA + C_SpreadsheetBench + C_SWEbench) / 3
```

- I：API 返回的总输入 token，包含缓存命中部分；H：其中缓存命中 token。先核对 provider 的字段语义，不能对未包含缓存的输入数重复扣除。
- O：API 返回的计费输出 token。若 completion_tokens 已包含 reasoning，不能再把 reasoning_tokens 加一次。
- P：实际供应商、地域、精确模型 ID、服务模式和价格生效时间对应的每百万 token 原价。百炼托管 DeepSeek 使用百炼价格，不能套 DeepSeek 直营 API 价格。
- 阶梯或峰谷价格按每次请求对应条件选择；仅有整题累计 token 时，不能凭整题总量选择单次请求阶梯。
- 显式缓存创建、缓存存储、搜索等额外收费需要独立用量和费率；当前公式不声称覆盖这些项目。启用之前须扩展价格配置与采集。
- 成绩只采用协议允许的计分尝试；运行花费包含已知失败尝试。另保留该计分尝试的费用以便归因。覆盖率不完整时不生成完整主榜费用。

H 缺失但 I、O 已知，且已确认仅有隐式缓存、固定费率时：

```text
C_low  = (I × min(P_input, P_cache) + O × P_output) / 1,000,000
C_high = (I × max(P_input, P_cache) + O × P_output) / 1,000,000
```

上述区间用于解释不确定性，不要求首期实现区间引擎。若采用无缓存价计算，必须标为“保守估算”，不能标成精确费用。峰谷条件无法确定时保留 unknown。只有 total_tokens 而没有输入/输出拆分时不输出精确估算。完全没有 usage 时保留 unknown。

## 价格快照与展示

配置放 `.github/bench/prices.yaml`，随 manifest 冻结。至少包含 model ID、provider、region、currency、费率/适用条件、官方来源 URL、核查日期及快照 hash。LiteLLM 接入代码放 `scripts/bench/`，不改产品依赖。

官方核查入口：[Qwen Max](https://help.aliyun.com/zh/model-studio/qwen3-8-max)、[Qwen 27B](https://help.aliyun.com/zh/model-studio/qwen3-8-27b)、[DeepSeek Pro](https://help.aliyun.com/zh/model-studio/deepseek-v4-pro)、[DeepSeek Flash](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash)、[GLM 5.3](https://help.aliyun.com/zh/model-studio/glm-5-3)、[GLM 5.2](https://help.aliyun.com/zh/model-studio/glm-5-2)。DeepSeek 模型卡存在峰谷价，不能用一个固定单价冒充实际调用费用。

保留原币种金额；注册到 LiteLLM 的 USD 单价必须使用冻结汇率，并保存汇率方向、生效日期和来源。没有汇率时不能把 CNY 数字填到 USD 字段。榜单显示费用来源与 coverage；不完整费用不参与确定性 Pareto 优劣判断。

服务端报告费用与官方价估算并存，不相加。实际账单实付只在取得账单对应记录后单列，避免把免费额度、账户折扣混入跨版本 list-price 比较。工具、judge、runner 花费各自列出，不与模型费用混称。

## 实施 checklist

- [x] 核查 SDK 计算、评测汇总和单题代理统计源码。
- [x] 确定公式、缓存缺失、重试与原币种处理口径。
- [x] 按用户意见采用 LiteLLM 计费路径，并在其失败后增加官方价格快照 × token usage 独立兜底。
- [ ] 固定 LiteLLM 版本并接入 completion_cost 和官方价格注册。
- [ ] 实现快照公式兜底，验证 LiteLLM 失败但费率和 usage 齐全时仍产出估算费用。
- [ ] 冻结六模型官方价格及必要的峰谷/汇率规则。
- [ ] 从 ACP 中提取真正的 token usage；context occupancy 不用于账单计算。
- [ ] 对输入、缓存、输出、reasoning、未知值和重复记录做单测。
- [ ] 在个人 origin 试跑并验证仅导出数值统计，不导出 key 或原始请求。
- [ ] 接入 receipt、聚合结果和网站 hover/table，保留 estimated/reported 区别。
