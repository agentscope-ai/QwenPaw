# QwenPaw release benchmarks

TL;DR：不创建根目录 `evaluation/`，不修改产品依赖。配置和调度使用 YAML，调用 Harbor 0.24.0 原生 ACP agent；少量 Python 只处理冻结任务、调用和结果汇总。首期 GAIA validation、SpreadsheetBench Verified、SWE-bench Verified 等权，六个模型在 `models.yaml` 中配置。

## 文件与环境

| 位置 | 职责 |
| --- | --- |
| `.github/bench/suite.yaml` | benchmark、题数、分批与预算配置 |
| `.github/bench/models.yaml` | 六个模型、服务地址、能力及生成参数 |
| `.github/bench/harbor.yaml` | 原生 Harbor JobConfig、Docker 和 ACP 安装定义 |
| `.github/workflows/bench.yml` | release/manual 入口、冻结任务、并行实验、最终汇总 |
| `.github/workflows/bench-model.yml` | 单模型九批串行执行 |
| `.github/workflows/bench-batch.yml` | 批内 matrix，每题一个 GitHub-hosted runner |
| `scripts/bench/` | prepare / run / collect，共用 manifest 校验 |
| `tests/unit/scripts/bench/` | 计分、完整性、预算、费用与隔离测试 |

所有命令从仓库根目录执行。`uv run --no-project --with harbor==0.24.0 --with litellm==1.103.4` 使用 uv 的工具环境，不读取产品项目依赖，不创建产品 `.venv`。容器里的 QwenPaw 使用 `uvx --no-cache --from` 从本次 workflow 检出提交的源码归档动态构建开发包，通过 ACP 调用，不复制产品 agent loop。模型由 runtime provider 的 `OPENAI_MODEL` 固定，不设置 Harbor agent.model_name：后者会请求可选 ACP session model selection，当前双方没有协商出该接口。模型身份由冻结配置和 receipt 保存，不发生隐式 fallback。运行数据放 `$RUNNER_TEMP`，不进入源码目录。

不做纯 YAML：完整性校验、跨 benchmark 等权聚合、费用未知处理不是 workflow 表达式擅长的工作。把这些逻辑塞进 YAML 的内联脚本也没有减少代码，反而难以测试。

## 执行

在 `Bench` environment 配置 `DASHSCOPE_API_KEY` secret；stage 和实际模型 job 绑定该 environment，嵌套调用使用 secrets: inherit；stage 先检查所选凭据是否存在，不输出值。离线验收后将 repository variable `BENCH_ENABLED=true`，才自动响应 published release；手动 workflow_dispatch 可用于验收，使用所选分支当前提交构建；SDK 版本从检出的 `src/qwenpaw/__version__.py` 读取，源码 repository/SHA 写入 manifest，receipt 记录 source_sha。不固定 runner 分支，也不依赖 PyPI 包发布。

1. 原生 Harbor CLI 导出数据；核对 165 + 400 + 500 题，冻结文件校验和与本轮配置。
2. 每模型 1,065 题，拆成 8 × 128 + 41，共九批。默认六模型并行，批间串行、批内并发 16（受账户总额度限制），一题一次 trial 独占一台 runner。完整一轮为 6,390 个任务 job，另有准备和汇总 job。
3. 每个 runner 只下载所在批次。启动前再校验题目内容。Harbor 重试为 0，尝试次数为 1；模型任务只获模型 key，不获网站写权限。
4. 任务使用原生 agent/verifier/build timeout；job 预算另外包含安装和上传余量。超过 hosted 单 job 上限时准备阶段报错，不缩短 benchmark timeout。将来接 self-hosted 时修改 runner 与预算预检，当前没有启用。
5. 汇总单题 receipt；缺题或基础设施失败使相应 benchmark 和综合分为空。有效失败和 agent timeout 计 0，verifier 错误不伪装为模型失败。各 benchmark 和领域按宏平均等权。

每实验最多九批，实验和批内并发可通过 dispatch 配置；模型/provider 数量来自 dispatch。基础设施失败或缺少 receipt 自动恢复一次，不对有效评分择优重试。

本地验证已有导出的数据（目录为 OUTPUT/datasets/benchmark-id/task）：

```sh
uv run --no-project --with harbor==0.24.0 --with litellm==1.103.4 python -m scripts.bench.dispatch \
  --output /tmp/qwenpaw-bench --sha COMMIT_SHA --repository OWNER/REPO
uv run --no-project --with harbor==0.24.0 --with litellm==1.103.4 --with pytest python -m pytest \
  -c /dev/null --confcutdir=tests/unit/scripts/bench \
  -p no:cacheprovider tests/unit/scripts/bench -q
```

Windows 使用等价路径和 PowerShell 命令续行；Python 帮助程序使用 pathlib。容器执行工作流的目标环境是 Linux。

## 结果、费用与边界

公开 JSON 是白名单摘要，包含 SDK 版本、模型、配置摘要、综合/领域/benchmark 分数、覆盖率、平均耗时和模型费用。保留每轮产物供后续构建 SDK 历史，不选最高 attempt。费用按服务端报告 → LiteLLM → 官方价格快照 × token usage 选择；仍缺必要数据才为 null。价格/汇率随 manifest 冻结。ACP `_meta.usage` 透传缓存计数与完整性，context occupancy 不用于计费。缓存不完整按无缓存价保守估算；DeepSeek 未提供逐请求峰谷条件时使用忙时价上界，均标记 upper_bound。估算不冒充账单实付。benchmark 平均费用含该题所有允许尝试，综合费用按 benchmark 等权。`observed_model_spend_usd` 单独统计收到的全部 attempt 中已知费用（含基础设施失败），同时给出已知数量和 observed 数量；它不是全量费用。工具、judge、基础设施费用仍待对账接入。

每题公开上传未加密的 `bench-trace-*` artifact，保留 Harbor 输出、ACP 事件、工具调用与结果和 grader 文件；只脱敏凭据。`trajectory.tar.gz` 附 `files.json` 文件清单与 SHA-256，保留 90 天。脱敏导出成功后才允许上传，跳过符号链接。Harbor 子进程日志不直接输出到 Actions 控制台。公开仓库仅运行公开评测，私有比较在私有仓库运行相同 workflow。

`.github/workflows/bench-smoke.yml` 仅手动触发，不再随 push 自动调用付费模型。正式评测仍由 release + `BENCH_ENABLED` 或显式 workflow_dispatch 触发。ACP 初始化跳过 BOOTSTRAP.md 的生成和引导 hook，其他配置与技能正常初始化；旧用户文件不删除。

## 验收状态与后续

- 已通过单测、Harbor JobConfig 校验与 actionlint；没有修改产品依赖文件。
- 数据导出在单轮内按文件哈希冻结；跨 release 固定 dataset revision、镜像 digest 与传递依赖锁定仍待完成，当前不能宣称跨轮完全可复现。
- 六模型的账户权限、多模态、工具调用和生成参数需离线确认；parity 报告也离线完成，不放进 release 的在线确认流程。
- PawBench / Claw-Eval 待确认现成 Harbor 接入后再讨论纳入；AppWorld / Terminal-Bench 不在首期。

## 单选/多选 dispatch 与纯 JSON PR

`bench.yml` 接受 `harnesses`、`models`、`benchmarks`，均支持一个 ID、逗号分隔多个 ID 或 `all`。默认 `qwenpaw / all / all`。首次支持的 harness 注册于 `.github/bench/harnesses.yaml`，每个 ID 指向包含 suite/models/prices/harbor YAML 的配置目录。私有仓库可登记 Harbor 原生 Codex、Claude Code 或已有 ACP registry 配置，不需要另一套 workflow。原生 agent 协议、实际版本、模型和 endpoint 必须匹配；未验证的组合不能声称已兼容。

```sh
gh workflow run bench.yml -R OWNER/REPO --ref feat/bench \
  -f harnesses=qwenpaw -f models=qwen3.8-27b,glm-5.3 \
  -f benchmarks=gaia
```

prepare 冻结完整题集来计算配置身份，但只执行选择的任务。实验间默认并发 6，最多九批/实验，每批最多 128 task、默认并发 16。未登记的 harness/benchmark 或空 ID 失败；模型 ID 可以直接指定服务端支持的新模型，不静默扩大运行范围。相同源码、模型、harness、完整实验配置和任务摘要产生同一配置 key，不受运行日期或同次 dispatch 选择列表影响。

每个 benchmark 的结果写入 `website/public/evaluation/data/results/<key>.json`；相同 key 覆盖、新 key 新增。失败重跑保留旧完整成绩，并更新 latest_attempt。完整运行与失败状态另存 `attempts/<run-id>-<attempt>.json`。这些都是白名单字段，不包含原始轨迹。

评测结束由单独的无模型密钥 job 从默认分支创建纯 JSON PR，不直接部署、不自动合并。PR 仅允许 results/attempts 目录的 JSON。默认分支合并后，网站 workflow 从全部已合并 JSON 重新生成 index.json 并部署；index 不由结果 PR 修改，避免不同 benchmark 的 PR 相互覆盖。相同文件发生并发修改时必须解决 Git 冲突，不能强行覆盖其他 PR。

私有配置拒绝在公开仓库运行；私有仓库的 PR、artifacts 和索引保持 private，不推送上游网站。Bench environment 在 stage 检查凭据存在，并在单题执行 job 通过 BENCH_API_KEY 注入所选 secret。替代 harness 在 harbor.yaml 使用环境变量引用，不写明文 Key。



## 动态 provider 与模型

`providers.yaml` 保存 endpoint、协议和 Bench secret **名称**。`provider` 支持单个 ID、逗号分隔多个 ID、`all`；多个 provider 与选定模型/harness 取笛卡尔积。`models=all` 指当前配置的默认六模型，并不查询服务商模型列表；跨服务商时应明确填写双方支持的模型 ID。

新模型不需要修改源码。新 provider 可在 dispatch 同时提供 `base_url` 和 `api_key_secret`（只填名称）。endpoint 必须是无内嵌凭据的 HTTPS 地址。多 provider 时使用各自登记配置，不能使用单 endpoint/secret 覆盖。当前 QwenPaw 要求 OpenAI-compatible API。

```sh
gh workflow run bench.yml -R OWNER/REPO --ref feat/bench \
  -f harnesses=qwenpaw -f provider=my-provider \
  -f base_url=https://api.example.com/v1 \
  -f api_key_secret=MY_PROVIDER_KEY \
  -f models=model-large,model-small -f benchmarks=gaia \
  -f 'model_options={"model-large":{"supports_image":true,"max_output_tokens":8192}}'
```

`model_options` 按实际模型 ID 覆盖 supports_image、max_input_tokens、max_output_tokens、generate_kwargs；未知模型默认不声明图像能力，其余采用共享生成配置。`price_snapshot` 可指定仓库内官方价格快照；更换 endpoint 或缺少模型价格时不沿用其他服务商价格，未能从服务端/usage 取得费用则显示 unknown。模型、provider、endpoint、生成配置和价格快照都进入配置标识，网站显示 provider，避免把不同接入的历史成绩混在一起。

验证记录：个人预览已部署 https://rayrayraykk.github.io/CoPaw/evaluation/ 。正式运行 37748464447 因 artifact 网络错误及任务凭据不可用而取消，未产出完整成绩；已增加 artifact 上传恢复、逐层 secrets 传递和调度前凭据检查。结果合并自动部署还要求这些实现 workflow 先进入默认分支。

### 小批量与并发

Dispatch 的 `task_limit` 为每个 benchmark 抽取的前 N 题，0 表示全量。抽样仍以完整任务清单计算覆盖率，不生成虚假的完整成绩。`parallelism` 接收 `{"experiments":6,"tasks":16}`，分别控制实验并行数和单实验每批任务并行数；每题独占一个 runner，批次顺序执行。实际并发受账户额度限制：个人 Free 账户最多 20，组织额度需另行确认。

ACP 的 uvx 环境显式安装 `pip==26.0.1`。QwenPaw shell 优先使用运行时 Python，因此必须同时提供对应的 pip/pip3，避免裸 `pip` 安装到系统环境后 Python 无法导入。任务原生镜像、依赖和 grader 不作预装修改。
