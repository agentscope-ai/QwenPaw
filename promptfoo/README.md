# QwenPaw promptfoo 安全测试

这个目录用于对本地 QwenPaw 实例开展 promptfoo 连通性测试、红队用例生成、人工审视和分批执行。

## 目录结构

- `configs/`：按 suite 拆分后的 promptfoo 配置文件。
- `curated/`：人工编写和人工改进的固定必测用例。
- `generated/`：`redteam generate` 生成后的测试用例 YAML。
- `report-templates/`：报表模板，维护 HTML/Markdown 的布局和占位符。
- `reports/`：根据 `results/` 生成的汇总报表。
- `results/`：`eval` 或 `redteam eval` 的执行结果。
- `scripts/build-report.cjs`：读取 `results/*.results.json` 并填充报表模板。
- `qwenpaw-provider.cjs`：调用本地 QwenPaw Console API。
- `openai-compatible-provider.cjs`：调用 DeepSeek 或其他 OpenAI-compatible 模型，用于生成用例和判分。
- `load-env.ps1`：从 `.env` 加载环境变量。
- `qwenpaw-security-test-plan.md`：安全设计与测试方案依据。

## 准备环境

```powershell
cd D:\projects\QwenPawGroup\promptfoo
Copy-Item .env.example .env
. .\load-env.ps1
```

首次使用时，先复制 `.env.example` 为 `.env`，再填写本地 QwenPaw 地址和 OpenAI-compatible 模型配置。`.env` 不提交到 git。

检查 QwenPaw 认证状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8088/api/auth/status
```

如果输出是 `{"enabled":false,"has_users":false}`，说明认证未启用，`.env` 里保持如下配置即可：

```env
QWENPAW_AUTH_TOKEN=
```

如果 PowerShell 阻止执行脚本，在同一个终端里先运行一次：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## OpenAI-Compatible 供应商

红队生成和判分模型由这些环境变量控制：

```env
PROMPTFOO_OPENAI_BASE_URL=https://api.deepseek.com/v1
PROMPTFOO_OPENAI_API_KEY=sk-...
PROMPTFOO_OPENAI_MODEL=deepseek-chat
PROMPTFOO_OPENAI_MAX_TOKENS=12000
```

如果使用 DeepSeek，把 key 填到 `PROMPTFOO_OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY` 即可。

如果使用其他 OpenAI-compatible 供应商，修改 `PROMPTFOO_OPENAI_BASE_URL`、`PROMPTFOO_OPENAI_API_KEY`、`PROMPTFOO_OPENAI_MODEL` 三项即可。

## Suite 列表

| Suite | 中文说明 | 配置文件 | 生成文件 | 结果文件 | 类型 |
| --- | --- | --- | --- | --- | --- |
| connectivity | 连通性测试 | `configs/connectivity.yaml` | 无 | `results/connectivity.results.json` | 固定连通性测试 |
| benign | 正常请求回归 | `configs/benign.yaml` | 无 | `results/benign.results.json` | 固定正常用例 |
| curated | 人工必测用例 | `configs/curated.yaml` | 无 | `results/curated.results.json` | 人工固定必测用例 |
| shell | 系统命令测试 | `configs/shell.yaml` | `generated/shell.generated.yaml` | `results/shell.results.json` | 红队生成 |
| file-secret | 敏感文件测试 | `configs/file-secret.yaml` | `generated/file-secret.generated.yaml` | `results/file-secret.results.json` | 红队生成 |
| credentials | 凭据泄露测试 | `configs/credentials.yaml` | `generated/credentials.generated.yaml` | `results/credentials.results.json` | 红队生成 |
| mcp | MCP 边界测试 | `configs/mcp.yaml` | `generated/mcp.generated.yaml` | `results/mcp.results.json` | 红队生成 |
| plugin-skill | 插件技能供应链 | `configs/plugin-skill.yaml` | `generated/plugin-skill.generated.yaml` | `results/plugin-skill.results.json` | 红队生成 |
| workspace-injection | 工作区提示注入 | `configs/workspace-injection.yaml` | `generated/workspace-injection.generated.yaml` | `results/workspace-injection.results.json` | 红队生成 |
| approval | 审批绕过测试 | `configs/approval.yaml` | `generated/approval.generated.yaml` | `results/approval.results.json` | 红队生成 |
| auth-api | 认证接口边界 | `configs/auth-api.yaml` | `generated/auth-api.generated.yaml` | `results/auth-api.results.json` | 聊天层 API 边界红队 |
| multi-agent | 多 Agent 绕过 | `configs/multi-agent.yaml` | `generated/multi-agent.generated.yaml` | `results/multi-agent.results.json` | 红队生成 |
| browser-desktop | 浏览器桌面隐私 | `configs/browser-desktop.yaml` | `generated/browser-desktop.generated.yaml` | `results/browser-desktop.results.json` | 红队生成 |
| prompt-extraction | 系统提示泄露 | `configs/prompt-extraction.yaml` | `generated/prompt-extraction.generated.yaml` | `results/prompt-extraction.results.json` | 红队生成 |

`auth-api` 当前是聊天层边界测试，用来验证 agent 是否会帮助绕过 API 鉴权。真正的 HTTP 接口级鉴权测试，后续建议再补一个 dedicated HTTP provider。

## 先跑连通性和正常用例

红队测试前，先确认 QwenPaw 与 provider 是通的：

```powershell
npx promptfoo@latest validate config -c configs/connectivity.yaml
npx promptfoo@latest eval -c configs/connectivity.yaml --no-cache --no-share -o results/connectivity.results.json
```

再跑一组正常用例，确认安全策略没有过度误伤：

```powershell
npx promptfoo@latest validate config -c configs/benign.yaml
npx promptfoo@latest eval -c configs/benign.yaml --no-cache --no-share -o results/benign.results.json
```

如果普通用例返回 `Model refused the request` 或空输出，应先排查 QwenPaw agent/API/provider 对接问题，再相信红队测试结果。

## 运行人工固定用例

`curated/` 下的用例是人工维护资产，不会被 `redteam generate --force` 覆盖。它适合存放已经确认质量高、必须长期回归的安全用例。

```powershell
npx promptfoo@latest validate config -c configs/curated.yaml
npx promptfoo@latest eval -c configs/curated.yaml --no-cache --no-share -o results/curated.results.json
```

维护固定用例：

- 直接编辑 `curated/must-have.yaml`。
- 从 `generated/*.generated.yaml` 里发现好用例后，把对应 `vars.prompt` 复制到 `curated/must-have.yaml`。
- 复制后补充 `description` 和 `vars.category`，并把措辞改成稳定、可复现、不会依赖某次生成上下文的版本。
- 不要把人工改进直接长期保存在 `generated/`，因为下一次 `--force` 生成会覆盖它。

## 第二轮重点回归

第一轮主要失败集中在审批绕过、认证降级、MCP 内网/凭据绑定、插件技能供应链、debug/tool schema 泄露几个方向。第二轮不要先盲目扩大全部 suite，建议先按下面顺序复测：

1. 连通性和正常用例仍然 100% 通过。
2. `curated/must-have.yaml` 中的 10 条第一轮失败用例全部通过。
3. 只重新生成并执行失败集中 suite：`approval`、`auth-api`、`mcp`、`plugin-skill`、`prompt-extraction`。
4. 生成报表后，优先确认是否还存在真实安全失败；判分模型拒绝或超时类问题单独归为测试问题。

固定失败回归：

```powershell
npx promptfoo@latest validate config -c configs/curated.yaml
npx promptfoo@latest eval -c configs/curated.yaml --no-cache --no-share -o results/curated.results.json
```

第二轮重点生成：

```powershell
npx promptfoo@latest redteam generate -c configs/approval.yaml -o generated/approval.generated.yaml --force --strict
npx promptfoo@latest redteam generate -c configs/auth-api.yaml -o generated/auth-api.generated.yaml --force --strict
npx promptfoo@latest redteam generate -c configs/mcp.yaml -o generated/mcp.generated.yaml --force --strict
npx promptfoo@latest redteam generate -c configs/plugin-skill.yaml -o generated/plugin-skill.generated.yaml --force --strict
npx promptfoo@latest redteam generate -c configs/prompt-extraction.yaml -o generated/prompt-extraction.generated.yaml --force --strict
```

第二轮重点执行：

```powershell
npx promptfoo@latest redteam eval -c generated/approval.generated.yaml --no-cache --no-share -j 1 -o results/approval.results.json
npx promptfoo@latest redteam eval -c generated/auth-api.generated.yaml --no-cache --no-share -j 1 -o results/auth-api.results.json
npx promptfoo@latest redteam eval -c generated/mcp.generated.yaml --no-cache --no-share -j 1 -o results/mcp.results.json
npx promptfoo@latest redteam eval -c generated/plugin-skill.generated.yaml --no-cache --no-share -j 1 -o results/plugin-skill.results.json
npx promptfoo@latest redteam eval -c generated/prompt-extraction.generated.yaml --no-cache --no-share -j 1 -o results/prompt-extraction.results.json
node scripts/build-report.cjs
```

如果 `prompt-extraction` 判分出现 `returned no final message content` 或 `finish_reason: refusal`，优先换成非 reasoning chat 模型，或者提高 `PROMPTFOO_OPENAI_MAX_TOKENS`。

## 单个 Suite 的标准流程

以 shell suite 为例：

```powershell
npx promptfoo@latest validate config -c configs/shell.yaml
npx promptfoo@latest redteam generate -c configs/shell.yaml -o generated/shell.generated.yaml --force --strict
```

审视或编辑 `generated/shell.generated.yaml` 后，再执行：

```powershell
npx promptfoo@latest redteam eval -c generated/shell.generated.yaml --no-cache --no-share -j 1 -o results/shell.results.json
npx promptfoo@latest redteam report
```

生成文件仍然是 promptfoo 评测配置，不是纯文本用例列表。真正的输入在 `tests:` 下面，每条通常是一个 `- vars:` 块，`vars.prompt` 才是会发送给 QwenPaw 的内容。

## 审视生成用例

常用审视命令：

```powershell
rg -n "pluginId|strategyId|description|prompt:" generated/shell.generated.yaml
rg -n "Remove-Item|curl|wget|\\.env|base64|cron|schtasks|sudo|chmod|credential|token" generated/shell.generated.yaml
(Select-String -Path .\generated\shell.generated.yaml -Pattern "^\s+- vars:" | Measure-Object).Count
```

如果文件头里的 `Total cases` 不是预期数量，或者 `vars.prompt` 看起来像一整段模型 API JSON，说明用例生成失败或被截断了。检查 `.env` 中的 `PROMPTFOO_OPENAI_MODEL`、`PROMPTFOO_OPENAI_BASE_URL` 和 `PROMPTFOO_OPENAI_MAX_TOKENS` 后，用 `--force` 重新生成。

## 生成全部红队 Suite

这些命令只生成用例，不执行：

```powershell
npx promptfoo@latest validate config -c configs/shell.yaml
npx promptfoo@latest redteam generate -c configs/shell.yaml -o generated/shell.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/file-secret.yaml
npx promptfoo@latest redteam generate -c configs/file-secret.yaml -o generated/file-secret.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/credentials.yaml
npx promptfoo@latest redteam generate -c configs/credentials.yaml -o generated/credentials.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/mcp.yaml
npx promptfoo@latest redteam generate -c configs/mcp.yaml -o generated/mcp.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/plugin-skill.yaml
npx promptfoo@latest redteam generate -c configs/plugin-skill.yaml -o generated/plugin-skill.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/workspace-injection.yaml
npx promptfoo@latest redteam generate -c configs/workspace-injection.yaml -o generated/workspace-injection.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/approval.yaml
npx promptfoo@latest redteam generate -c configs/approval.yaml -o generated/approval.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/auth-api.yaml
npx promptfoo@latest redteam generate -c configs/auth-api.yaml -o generated/auth-api.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/multi-agent.yaml
npx promptfoo@latest redteam generate -c configs/multi-agent.yaml -o generated/multi-agent.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/browser-desktop.yaml
npx promptfoo@latest redteam generate -c configs/browser-desktop.yaml -o generated/browser-desktop.generated.yaml --force --strict

npx promptfoo@latest validate config -c configs/prompt-extraction.yaml
npx promptfoo@latest redteam generate -c configs/prompt-extraction.yaml -o generated/prompt-extraction.generated.yaml --force --strict
```

建议先单个 suite 跑通，再批量生成。当前每个 suite 默认小批量，通常是 `numTests: 5`；要扩大覆盖面，修改对应 `configs/*.yaml` 里的 `numTests`。

固定用例不需要生成，直接运行 `configs/curated.yaml`。

## 执行全部已生成 Suite

这些命令只执行已经审视过的 `generated/*.generated.yaml`：

```powershell
npx promptfoo@latest redteam eval -c generated/shell.generated.yaml --no-cache --no-share -j 1 -o results/shell.results.json
npx promptfoo@latest redteam eval -c generated/file-secret.generated.yaml --no-cache --no-share -j 1 -o results/file-secret.results.json
npx promptfoo@latest redteam eval -c generated/credentials.generated.yaml --no-cache --no-share -j 1 -o results/credentials.results.json
npx promptfoo@latest redteam eval -c generated/mcp.generated.yaml --no-cache --no-share -j 1 -o results/mcp.results.json
npx promptfoo@latest redteam eval -c generated/plugin-skill.generated.yaml --no-cache --no-share -j 1 -o results/plugin-skill.results.json
npx promptfoo@latest redteam eval -c generated/workspace-injection.generated.yaml --no-cache --no-share -j 1 -o results/workspace-injection.results.json
npx promptfoo@latest redteam eval -c generated/approval.generated.yaml --no-cache --no-share -j 1 -o results/approval.results.json
npx promptfoo@latest redteam eval -c generated/auth-api.generated.yaml --no-cache --no-share -j 1 -o results/auth-api.results.json
npx promptfoo@latest redteam eval -c generated/multi-agent.generated.yaml --no-cache --no-share -j 1 -o results/multi-agent.results.json
npx promptfoo@latest redteam eval -c generated/browser-desktop.generated.yaml --no-cache --no-share -j 1 -o results/browser-desktop.results.json
npx promptfoo@latest redteam eval -c generated/prompt-extraction.generated.yaml --no-cache --no-share -j 1 -o results/prompt-extraction.results.json
npx promptfoo@latest redteam report
```

高危测试建议保持 `-j 1` 串行执行，便于观察 QwenPaw 的工具调用、审批流和副作用。

## 生成汇总报表

完成一组或多组测试后，使用报表脚本读取 `results/*.results.json`，并填充 `report-templates/` 下的模板：

```powershell
node scripts/build-report.cjs
```

默认输出：

- `reports/index.html`：本地 HTML 看板，以 tab 页切换查看总体概览、测试套件汇总、分类汇总、用例明细和报告详情；总览数字可跳转到对应清单，并支持筛选、搜索和分页；默认每页显示 10 条。
- `reports/summary.md`：Markdown 汇总，适合粘贴到 issue、PR 或测试记录。
- `reports/summary.json`：机器可读聚合结果，后续可用于 CI 门禁或趋势分析。

脚本会对常见 key、token、Authorization header、私钥等内容做脱敏后再写入报表。`reports/` 默认不提交到 git。

可选参数：

```powershell
node scripts/build-report.cjs --results results --templates report-templates --out reports
```

## 运行建议

- 用例生成和执行必须拆开：先 `redteam generate`，人工审视，再 `redteam eval`。
- 人工精选和必须长期保留的用例放在 `curated/`，不要放在 `generated/`。
- 测试完成后运行 `node scripts/build-report.cjs`，用 `reports/index.html` 做失败/异常分析。
- 扩大规模前，建议使用专用 QwenPaw 测试工作区，并只放假的 secret 和 canary 数据。
- 不要通过重复声明同一个插件来凑数量；修改同一个插件的 `numTests` 更可控。
- 修改供应商、模型、提示词或测试数量后，需要用 `--force` 重新生成用例。
- `generated/`、`results/` 和 `reports/` 默认不提交到 git；需要保留某次结果时，可另行归档。
