# AgentGateway × QwenPaw 多 MCP 统一接入演示指南

本演示面向**从未接触过本项目的演示者**。它是换岗降权故事的**前置幕**：先说明没有网关时多个 MCP 各自裸奔的问题，再展示由 AgentGateway 统一入口、统一鉴权和后端防绕过。

> 论坛、人事、财务三个 MCP 一开始谁都能直连；接入网关后，客户端只走 `http://localhost:3000/mcp`，必须持有合法 JWT。后端同时只信任网关注入的内部凭证，绕过网关直连会被拒绝。

**用 QwenPaw 当演示界面的完整分步流程、MCP 配置切换与对话原文：** 见 [QwenPaw_demo.md](./QwenPaw_demo.md)。

换岗后的工具级授权（同一 Token 降权）见 [Demo_readme.md](./Demo_readme.md)，不要和本幕混在一次讲解里。

---

## 一、演示前准备

目录与 [Demo_readme.md](./Demo_readme.md) 相同：`agentgateway.exe`、`Demo_readme.md`、`Gateway_readme.md`、`demo-rbac/` 放在同一 DeployRoot。

| 依赖 | 用途 |
|------|------|
| Windows + PowerShell | 运行脚本与网关 |
| Python 3.10+ | MCP 后端与断言客户端 |
| QwenPaw（`qwenpaw` 命令） | 对话演示（可选，命令行也能走完全程） |

进入 DeployRoot：

```powershell
cd <DeployRoot>
Test-Path .\agentgateway.exe
Test-Path .\demo-rbac\scripts\start-open-demo.ps1
```

---

## 二、故事线与权限对照

| 阶段 | 客户端入口 | 后端鉴权 | 无 Token | 伪造 Token | 合法 Token |
|------|------------|----------|----------|------------|------------|
| **A 无网关** | 三个独立 URL（`:9001` / `:9002` / `:9003`） | 无 | 可读可写敏感工具 | — | — |
| **B 接入网关** | 仅 `localhost:3000/mcp` | 每个 MCP 校验网关内部凭证 | 拒绝 | 拒绝 | 7 个聚合工具可用 |

角色：

| 角色 | 含义 |
|------|------|
| `anonymousAgent` | 不带 Token，用于第一幕成功、第三幕失败 |
| `forgedAgent` | 结构合法但签名错误的 JWT |
| `employeeQwenpaw` | 已签发的演示 JWT（文件 `demo-rbac\jwt\employeeQwenpaw.key`） |

网关暴露的工具名带后端前缀：`forum_*`、`hr_*`、`finance_*`。

---

## 三、演示步骤

建议 2 个 PowerShell 窗口：窗口 A 跑脚本，窗口 C 跑 `qwenpaw app`（可选）。

### 步骤 1：第一幕 — 三个 MCP 各自裸露

```powershell
.\demo-rbac\scripts\start-open-demo.ps1 -Restart
```

**讲解：** “团队陆续上线了论坛、人事、财务 MCP，但每个团队只关注功能，没有统一安全入口。”

**预期：**

| 服务 | 地址 | 鉴权 |
|------|------|------|
| HR | `http://127.0.0.1:9001/mcp` | 无 |
| Forum | `http://127.0.0.1:9002/mcp` | 无 |
| Finance | `http://127.0.0.1:9003/mcp` | 无 |

命令行探测（匿名应全部成功）：

```powershell
python .\demo-rbac\clients\demo_unified.py --phase open
```

或在 QwenPaw（`qwenpaw app` → http://127.0.0.1:8088/ → **智能体 → MCP**）导入：

`demo-rbac\qwenpaw\open-clients.json`

对话示例：

```
请分别调用 list_posts、get_employee、get_department_budget，再尝试发帖和提交一笔报销。
```

**预期结果：** 全部成功。人事记录和部门预算对匿名调用者可见，写操作也能执行。

**结论话术：** “问题不只是没有 Token，而是入口、身份、策略和审计全部分散。以后每增加一个 MCP，都要重复建设一遍。”

### 步骤 2：第二幕 — 统一接入 AgentGateway

```powershell
.\demo-rbac\scripts\enable-gateway.ps1
```

**讲解：** “不改业务工具协议，把身份验证和统一入口交给网关；后端只信任网关身份。”

**预期：**

- 三个 MCP 切换为 protected，校验 `X-Gateway-Token`
- AgentGateway 监听 `http://localhost:3000/mcp`
- 脚本生成 `demo-rbac\qwenpaw\gateway-client.json`（不要在屏幕上念出 Token）

在 QwenPaw 中：**禁用或删除**三个直连客户端，只导入 `gateway-client.json`。

### 步骤 3：第三幕 — 连续四次验证

按固定顺序。命令行：

```powershell
python .\demo-rbac\clients\demo_unified.py --phase bypass
python .\demo-rbac\clients\demo_unified.py --phase no-token
python .\demo-rbac\clients\demo_unified.py --phase forged
python .\demo-rbac\clients\demo_unified.py --phase valid
```

| 顺序 | 动作 | 预期 |
|------|------|------|
| 1 | 直连 `:9001` / `:9002` / `:9003` | `[BLOCKED]` 缺少网关内部凭证 |
| 2 | 访问网关但不带 Token | `[BLOCKED]` strict JWT |
| 3 | 访问网关但带伪造 Token | `[BLOCKED]` 签名/校验失败 |
| 4 | 访问网关并带 `employeeQwenpaw` Token | 7 个工具，论坛/人事/财务调用成功 |

QwenPaw 对话（合法 Token 已写在 gateway-client 里）：

```
请列出当前 MCP 工具，并分别读取论坛帖子、员工信息和部门预算。不要回显完整证件号或金额明细。
```

查看集中审计（不要贴完整 JWT 或内部密钥）：

```powershell
Get-Content .\demo-rbac\logs\gateway-access.log -Tail 30
```

关注 `jwt.sub`、`mcp.target` / `audit_mcp_tool`、`http.status`、`error=`。

### 步骤 4：第四幕 — 衔接到换岗降权（点到为止）

**话术：** “统一认证解决谁能进来；换岗降权演示继续解决进来以后能做什么。”

然后按 [Demo_readme.md](./Demo_readme.md) 使用 `start-all.ps1` / `downgrade-employee.ps1`。本幕不要同时开着 Finance + unified 配置，以免和 RBAC 的 5 工具矩阵打架。先执行：

```powershell
.\demo-rbac\scripts\stop-all.ps1
```

---

## 四、一键自动走完全程

```powershell
.\demo-rbac\scripts\run-gateway-demo.ps1
```

顺序：开放直连成功 → 上锁 → 绕过拒绝 → 无 Token 拒绝 → 伪造 Token 拒绝 → 合法 Token 成功。任一步断言失败则非 0 退出。

---

## 五、相关文件

| 路径 | 说明 |
|------|------|
| `demo-rbac\scripts\start-open-demo.ps1` | 阶段 A：三个开放 MCP |
| `demo-rbac\scripts\enable-gateway.ps1` | 阶段 B：后端上锁 + 启动网关 |
| `demo-rbac\scripts\run-gateway-demo.ps1` | 自动断言全程 |
| `demo-rbac\clients\demo_unified.py` | 分阶段断言客户端 |
| `demo-rbac\config\agentgateway-unified.yaml` | 严格 JWT + 三目标 + 后端凭证 |
| `demo-rbac\qwenpaw\open-clients.json` | QwenPaw 直连三个 MCP |
| `demo-rbac\secrets\` | 网关内部凭证（本机生成，不入库） |

用户 JWT 与后端内部凭证是两套身份：前者标识 Agent，后者标识 Gateway。

---

## 六、常见问题

### Q1：`enable-gateway.ps1` 后直连仍然成功

确认脚本已重启三个 MCP 为 `--auth-mode protected`。看日志里是否出现 `Auth: PROTECTED`。

### Q2：合法 Token 仍被网关拒绝

确认 `employeeQwenpaw.key` 与 `demo-rbac\jwt\pub-key` 是一对。不要手改 JWT。用 `print-qwenpaw-gateway-json.ps1` 重新生成导入文件。

### Q3：Finance 端口没起来

`start-open-demo.ps1` / `enable-gateway.ps1` 会安装 `mcp-finance` 依赖。查看 `demo-rbac\logs\mcp-finance.log`。

### Q4：想单独停服务

```powershell
.\demo-rbac\scripts\stop-all.ps1
```
