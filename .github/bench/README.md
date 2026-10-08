# QwenPaw release benchmarks

TL;DR：不创建根目录 `evaluation/`，不修改产品依赖。配置和调度使用 YAML，调用 Harbor 0.24.0 原生 ACP agent；少量 Python 只处理冻结任务、调用和结果汇总。首期 GAIA validation、SpreadsheetBench Verified、SWE-bench Verified 等权，六个模型在 `models.yaml` 中配置。

## 文件与环境

| 位置 | 职责 |
| --- | --- |
| `.github/bench/suite.yaml` | benchmark、题数、分批与预算配置 |
| `.github/bench/models.yaml` | 六个模型、服务地址、能力及生成参数 |
| `.github/bench/harbor.yaml` | 原生 Harbor JobConfig、Docker 和 ACP 安装定义 |
| `.github/workflows/bench.yml` | release/manual 入口、冻结任务、串行模型、最终汇总 |
| `.github/workflows/bench-model.yml` | 单模型九批串行执行 |
| `.github/workflows/bench-batch.yml` | 批内 matrix，每题一个 GitHub-hosted runner |
| `scripts/bench/` | prepare / run / collect，共用 manifest 校验 |
| `tests/unit/scripts/bench/` | 计分、完整性、预算、费用与隔离测试 |
| `docs/design/` | HTML 效果原型与实施 checklist |

所有命令从仓库根目录执行。`uv run --no-project --with harbor==0.24.0` 使用 uv 的工具环境，不读取产品项目依赖，不创建产品 `.venv`。容器里的 QwenPaw 使用 `uvx` 安装指定已发布版本，通过 ACP 调用，不复制产品 agent loop。运行数据放 `$RUNNER_TEMP`，不进入源码目录。

不做纯 YAML：完整性校验、跨 benchmark 等权聚合、费用未知处理不是 workflow 表达式擅长的工作。把这些逻辑塞进 YAML 的内联脚本也没有减少代码，反而难以测试。

## 执行

配置 `DASHSCOPE_API_KEY` secret。离线验收后将 repository variable `BENCH_ENABLED=true`，才自动响应 published release；手动 workflow_dispatch 可用于验收，version 必须是已发布包的精确版本。发布 tag 与包版本须一致，包须已可下载。

1. 原生 Harbor CLI 导出数据；核对 165 + 400 + 500 题，冻结文件校验和与本轮配置。
2. 每模型 1,065 题，拆成 8 × 128 + 41，共九批。六模型依次执行，批间串行、批内并发 8，一题一次 trial 独占一台 runner。完整一轮为 6,390 个任务 job，另有准备和汇总 job。
3. 每个 runner 只下载所在批次。启动前再校验题目内容。Harbor 重试为 0，尝试次数为 1；模型任务只获模型 key，不获网站写权限。
4. 任务使用原生 agent/verifier/build timeout；job 预算另外包含安装和上传余量。超过 hosted 单 job 上限时准备阶段报错，不缩短 benchmark timeout。将来接 self-hosted 时修改 runner 与预算预检，当前没有启用。
5. 汇总单题 receipt；缺题或基础设施失败使相应 benchmark 和综合分为空。有效失败和 agent timeout 计 0，verifier 错误不伪装为模型失败。各 benchmark 和领域按宏平均等权。

九批、六模型和并发 8 是首期明确固定的 workflow 结构。改变规模时需同步 YAML；准备阶段会检查配置和结构的一致性。当前不支持 Actions 的直接 rerun 合并；需要新 dispatch，保留旧轮次为 incomplete，不择优合并。底层聚合器已限制只有基础设施错误才可接续 attempt，自动恢复尚未接入。

本地验证已有导出的数据（目录为 OUTPUT/datasets/benchmark-id/task）：

```sh
uv run --no-project --with harbor==0.24.0 python -m scripts.bench.prepare \
  --output /tmp/qwenpaw-bench --version 1.0.0 --sha COMMIT_SHA
uv run --no-project --with harbor==0.24.0 --with pytest python -m pytest \
  -c /dev/null --confcutdir=tests/unit/scripts/bench \
  -p no:cacheprovider tests/unit/scripts/bench -q
```

Windows 使用等价路径和 PowerShell 命令续行；Python 帮助程序使用 pathlib。容器执行工作流的目标环境是 Linux。

## 结果、费用与边界

公开 JSON 是白名单摘要，包含 SDK 版本、模型、配置摘要、综合/领域/benchmark 分数、覆盖率、平均耗时和模型费用。保留每轮产物供后续构建 SDK 历史，不选最高 attempt。当前费用只取 Harbor 返回的 model cost；未知为 null，不填 0、不冒充完整账单。`observed_model_spend_usd` 单独统计收到的全部 attempt 中已知费用（含基础设施失败），同时给出已知数量和 observed 数量；它不是全量费用。工具、judge、基础设施费用仍待对账接入。

原始轨迹单独上传 artifact，不进入摘要。在公开仓库中 artifact 不是私有存储；只允许公开评测进入该 workflow，须完成数据许可和日志披露检查。private harness 比较必须留在私有仓库；当前运行器只实现 QwenPaw，不能宣称已经支持其他 harness。

## 验收状态与后续

- 已通过单测、Harbor JobConfig 校验与 actionlint；没有修改产品依赖文件。
- 本机 Docker daemon 不可用，尚未运行真实容器或模型 API；标准 hosted runner 的内存、磁盘和全流程时间仍须逐 benchmark 实测。Harbor 有 adapter 不代表当前 runner 或模型组合已验收。
- 数据导出在单轮内按文件哈希冻结；跨 release 固定 dataset revision、镜像 digest 与传递依赖锁定仍待完成，当前不能宣称跨轮完全可复现。
- 六模型的账户权限、多模态、工具调用和生成参数需离线确认；parity 报告也离线完成，不放进 release 的在线确认流程。
- 当前只生成公开 summary artifact，尚未接网站历史存储和自动部署。HTML 是带 mock 数据的设计原型，不是实测成绩。
- PawBench / Claw-Eval 待确认现成 Harbor 接入后再讨论纳入；AppWorld / Terminal-Bench 不在首期。
