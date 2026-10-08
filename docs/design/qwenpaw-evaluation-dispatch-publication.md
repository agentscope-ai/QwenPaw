# Evaluation dispatch 与 JSON PR 发布机制

此方案取代原来的「评测直接写 bench-results 并部署」机制。评测完成不自动合并，不在合并前改变正式网站。

## TL;DR

```text
release published / manual dispatch
  → 解析选择与冻结配置
  → Harbor 执行、收集完整与失败记录
  → 基于默认分支最新 JSON 做 upsert
  → 创建或更新纯 JSON PR
  → PR 合并到默认分支
  → 网站 workflow 构建、部署
```

默认 release 范围：QwenPaw × 六模型 × GAIA、SpreadsheetBench Verified、SWE-bench Verified。手动运行不创建 release，运行器仍使用该次 dispatch 选定 ref 的源码包；PR 目标为仓库默认分支。首期只修改同一仓库里的工作流和模块，不维护另一套私有仓库代码。

## 选择输入

| 输入 | 默认值 | 行为 |
|---|---|---|
| `harnesses` | `qwenpaw` | 一个 ID 或逗号分隔多个 ID；只接受已登记的 Harbor 配置 |
| `models` | `all` | 实际模型 ID、多个 ID 或默认模型 all；允许新 ID |
| `provider` | `dashscope` | 单个、多个或登记 provider 的 all |
| `base_url` / `api_key_secret` | 空 | 单 provider 的 HTTPS endpoint / secret 名称覆盖 |
| `model_options` | `{}` | 按模型 ID 覆盖能力、token 限制与生成参数 |
| `price_snapshot` | 空 | 仓库内价格快照；没有价格则 unknown |
| `benchmarks` | `all` | 一个 benchmark ID、多个 ID 或 all |

GitHub 原生 workflow_dispatch choice 是单选，不提供原生多选组件；因此多选使用逗号分隔字符串。prepare 去空白、去重、验证 ID、解析 all。空值、未登记 harness/benchmark 和空任务集直接失败，不静默退回默认全量。

provider × 模型 × harness × benchmark 取所选笛卡尔积。一题一个 runner；批次大小 128、批内并发 8。不再把六模型或九批写成运行所必需的固定数量。替代 harness 不混入公开 release 默认运行，私有结果只在私有仓库创建结果 PR。

例：`harnesses=qwenpaw`、`models=qwen3.8-27b,glm-5.3`、`benchmarks=gaia` 只执行两个模型的 GAIA，不能生成新的三项完整主榜成绩。

## 配置判同与默认覆盖

以 **单 benchmark × model × harness × SDK/source 版本 × 有效实验配置** 作为最小存储单位，不能用整个 dispatch 的选择列表作主键。

```text
result_key = SHA256(canonical_json(effective_configuration))
```

有效配置包含：harness ID/版本/源码 SHA，模型实际 ID、provider endpoint/地域和生成参数，benchmark split、任务内容摘要、grader/adapter 和 Harbor 版本、原生预算、工具/skills/权限/初始化策略、资源规格及价格快照。

不包含：运行日期、workflow run ID、运行状态、得分、费用、密钥、同批选中的其他模型或 benchmark。配置只记录环境变量名称和策略，不记录 secret 值。

- 同一个 result_key：默认更新该 key 的当前完整结果；不追加同配置的重复榜单行。
- 新 result_key：新增 JSON 记录，保留不同 SDK/source 版本的历史。
- 单选重跑和全选重跑若有效配置相同，命中同一个 key。
- 只更新所选结果，未选择的模型、harness、benchmark 和历史版本全部保留。
- 记录最新 workflow、manifest 摘要、日期和 attempt。旧内容可从 Git/PR 历史追溯，不因覆盖抹去审计记录。

跨 release 精确复用要求数据/镜像/依赖实际固定；尚未固定的条件必须记入 manifest 并披露，不能将同名配置宣称为已证明 parity。按用户要求，这部分在完整运行后继续验证。

## 完整性与失败

只有一个 benchmark 的预期任务全部得到有效结果，才能替换该 benchmark 的正式分数；正常失败和 agent timeout 按评分协议计入，基础设施失败不伪造成有效失败题。

未完成运行记录为状态 JSON，并引用 workflow 和已知费用。若同 key 已有完整成绩，保留其成绩，同时标明最近一次重跑失败/未完成；不把旧成绩伪装成本次成功。首次运行未完成时不出正式分数。

综合主榜仅由同一可比配置组中三个完整 benchmark 组成，等权平均。手动单项更新后，只在另外两项仍属于同一配置组且完整时更新综合分。不得跨 SDK、源码、工具或数据协议拼接历史最佳值；不完整时只显示已完成子榜与缺项状态。

## JSON PR 的范围

建议文件结构：

```text
website/public/evaluation/data/
  index.json                   # 网站构建时生成，结果 PR 不修改
  results/<result_key>.json     # 每配置/benchmark 的当前结果与最近状态
  attempts/<run_id>.json        # 本轮状态、覆盖率、已知费用和证据链接
```

PR 只允许上述目录中的 `.json` 文件，不包含 Markdown、代码、workflow、原始模型输出或密钥。说明、运行链接、选择范围、更新/新增数量和失败摘要写在 PR body。

发布 job 从默认分支最新提交创建受控结果分支，执行字段白名单、JSON schema、配置主键和差异路径校验，才提交和创建 PR。不能从被评测的旧 release 分支直接创建包含产品代码差异的 PR。

结果生成脚本使用受信任实现，模型 task 不获得 PR 写入权限。发布 job 只有所需的 contents/pull-requests 权限，不注入模型 API Key。JSON 字符串按文本渲染。

同一 workflow run 的重执行更新其已有 PR；新 dispatch 创建独立 PR。writer 串行化，基于最新默认分支应用 upsert。总索引由合并后的结果文件生成，不提交共享索引；不同 key 的 PR 可以独立合并。相同 key 冲突应显式呈现，不能强推整个索引覆盖已经合并的更新。

默认不自动合并。JSON PR 合并后才成为网站正式数据。

## 部署触发

网站 workflow 增加默认分支上的结果 JSON 路径触发。构建直接读取已合并 JSON，不再通过 hydrate 下载旧 bench-results 分支覆盖它。

旧的评测 `publish → website` 直接部署依赖移除。数据合并后走现有统一网站 workflow 与 concurrency，保留整站内容和历史深链。开发预览可以单独手动部署，必须明确 mock 与正式数据的区别。

## 实施 checklist

- [x] dispatch 的 harness/provider/model/benchmark 单多选与动态模型配置。
- [x] 动态实验组合与批次调度，默认公开范围保持不变。
- [x] 明确并测试独立于 dispatch 选择集合的配置主键。
- [x] JSON upsert：覆盖同 key、新增新 key、保留未选与 SDK 历史。
- [x] 失败状态与完整成绩分离，单项更新不生成不合法主榜。
- [x] 从默认分支生成纯 JSON PR，路径/字段/来源检查。
- [ ] 并发与未合并 PR 更新测试，不自动合并。
- [x] 网站改为读取合并结果；JSON 合并触发统一部署。
- [ ] 个人 origin 完整正式运行，检查 JSON PR 的真实差异与部署。

目前网站交互代码已在本地提交 `36539618c`；桌面/390px 移动端、悬停、筛选、搜索、中英文切换、详情和真实空数据模式通过浏览器验证。JSON PR 流程代码已实现，真实 hosted 运行与 PR/部署验收另行记录；不得把单测完成当作全量运行完成。
