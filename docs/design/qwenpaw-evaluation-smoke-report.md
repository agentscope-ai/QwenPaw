# 个人 origin 的 GitHub-hosted 试跑

2026-10-08；仓库 `rayrayraykk/CoPaw`，分支 `feat/bench`。

[成功 workflow](https://github.com/rayrayraykk/CoPaw/actions/runs/37736770418) 对应代码 `df044bceead29bdd341750c8ec0708aa69b8264b`。使用 Harbor 0.24.0、QwenPaw 2.2.2b4、`qwen3.8-27b`、北京区 DashScope 兼容接口。两个 job 分别使用独立的 `ubuntu-24.04` GitHub-hosted runner，未使用 self-hosted runner。

| 验证 | 结果 | trial 耗时 |
| --- | --- | --- |
| 模型直接请求 | HTTP 200 | 不纳入 benchmark 耗时 |
| 合成 shell 工具测试 | 原生 grader reward 1 | 90.85 秒 |
| GAIA 固定题 | 原生 grader reward 0，无基础设施错误 | 152.88 秒 |

GAIA 题目为 `0383a3ee-47a7-41a4-b493-519bdefe0488`，按导出任务 ID 排序选择首个 level 1 任务，选择时未读取参考答案。保留原生任务文件、600 秒 agent timeout、300 秒 verifier timeout 和 300 秒 build timeout。本题只执行一次，不重跑选最高成绩；0 分表示该题未通过，workflow 成功表示执行和评分链路完成，不等于模型答对。

GAIA 单题 manifest SHA256：`4cfcaaf739a3d56089510d24d90d4357dda1ffa571eee985240ebd69efec5e47`。本地亦通过 Harbor CLI 成功导出全部 165 个 GAIA 任务；本轮没有运行完整 GAIA、SpreadsheetBench 或 SWE-bench。

## 排查结论

Harbor 的 `agent.model_name` 会触发 ACP session model selection；当前组合未协商出该可选接口，导致执行在 prompt 前失败。当前实现通过 QwenPaw runtime provider 的 `OPENAI_MODEL` 固定单轮模型，不再额外请求模型切换；模型身份保存在冻结配置和 receipt 中。

合成测试曾出现模型宣称文件完成但 grader 给 0 的情况。随后明确了合成指令中的 shell 命令、16 字节要求和无 BOM 要求，保留原判分逻辑。合成测试不属于能力榜；这些调试运行不合并进正式成绩。GAIA 原题和 grader 没有修改。

参考项目仅用于理解 ACP 用法，没有带入其私有 wheel、数据或目录配置。产品依赖文件、产品环境和 ACP 实现均未修改。

## 凭据与数据

- Key 留在 GitHub 的 `Bench` environment secret `DASHSCOPE_API_KEY` 中，通过运行步骤环境变量注入。未下载 Key 到本机，也未写入源码或命令参数。
- Harbor 子进程输出不进入 Actions 日志，原始轨迹不上传。仅上传结构化 receipt；诊断错误摘要和合成任务回复先脱敏，再检查是否包含 Key。真实 GAIA 回复正文不导出。
- 两份公开 receipt 均通过凭据模式扫描。这是额外检查，不替代上面的环境隔离与导出限制。
- ACP 当前没有回传 token usage 和模型费用；相关字段为 `null`，不代表费用为 0。完整费用对账仍待实现。

## 验证与剩余工作

本地 18 项单测通过，相关文件的完整 pre-commit 检查通过，包括 mypy、black、flake8、pylint、私钥检测和 actionlint。网站未部署，正式 release 全量评测未开启。

仍需完成三项 benchmark 全量资源验收、跨轮 dataset/镜像/依赖固定、费用采集、离线 parity、私有 harness 实际接入以及网站历史数据与自动部署。此记录不宣称 QwenPaw 相对其他 harness 的优越性，也不是正式综合榜成绩。


## 开发源码与费用链路验收（2026-10-08）

[GitHub Actions run 37740027507](https://github.com/rayrayraykk/CoPaw/actions/runs/37740027507) 成功。代码提交 `464e16c3e122d497366276771585a63b099ce251`。

runner 不再安装发布包：每次使用 workflow 的 repository/SHA 从源码归档动态构建，uvx 禁用缓存；版本标签从检出的源码读取。没有固定 runner 分支。manifest 保存源码来源、官方价格和汇率，receipt 保存 source_sha 与价格 hash。

| 任务 | 原生 reward | 输入 token | 输出 token | 缓存命中 token | 官方价估算 CNY | 换算 USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 合成 ACP 验收 | 1 | 33,903 | 830 | 19,968 | 0.0637458 | 0.0094647147 |
| 固定 GAIA 单题 | 1 | 200,815 | 2,809 | 171,776 | 0.2238906 | 0.0332423572 |

模型为 `qwen3.8-27b`。usage_source 为 `qwenpaw_acp_meta`，cost_source 为 `litellm_estimated`，cost_basis 为 `list_price`。价格 hash 为 `db3ec0f6dfbfdef93342c19669af6c4ef0fe68ec26ad168c231d48021f3ef8a8`。CNY 按 2026-09-30 的 6.7351 CNY/USD 冻结汇率换算；这些是 list-price 估算，不是账单实付。

本次 GAIA 只是同一固定任务的开发验收，不替换前次 reward 0 的记录，也不能据此声称整套 benchmark 性能提升。未修改题目或 grader。

新增 ACP 缓存字段已通过真实容器链路；部分调用缓存缺失时不冒充完整计数。独立快照兜底已通过 LiteLLM 异常/无效结果测试；真实试跑正常走 LiteLLM 路径，没有故意制造 API 失败。

本地 32 项评测单测、75 项 ACP/token 单测及相关 pre-commit 检查通过。两个公开 receipt 的凭据模式扫描通过，未上传原始请求、完整轨迹或模型运行环境。
