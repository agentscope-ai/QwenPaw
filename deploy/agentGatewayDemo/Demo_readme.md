# AgentGateway × QwenPaw 换岗降权演示指南

本演示面向**从未接触过本项目的演示者**，按步骤操作即可复现完整故事：

> 员工 `employeeQwenpaw` 已发放 MCP 访问 Token（长期不变）。换岗前网关允许其访问全部工具；换岗后**只修改网关策略、不收回 Token**，员工若仍用原 Token 越权访问人事数据，将被拒绝并上报安全事件。

---

## 一、演示前准备

### 1.1 目录结构

将以下两部分放在**同一文件夹**（下文称为 **DeployRoot**）：

```
DeployRoot/
├── agentgateway.exe      ← 网关可执行文件
├── Demo_readme.md        ← 本文件
└── demo-rbac/            ← 演示脚本、配置、Token、MCP 后端
```

示例路径：`D:\coding\agentGatewayDemo`

### 1.2 机器依赖（需提前安装）

| 依赖 | 用途 |
|------|------|
| **Windows 10/11** + **PowerShell** | 运行脚本与网关 |
| **Python 3.10+**（含 pip） | MCP 后端、演示客户端、日志监控 |
| **QwenPaw**（已安装 `qwenpaw` 命令） | 智能体控制台与 MCP 客户端 |

可选（仅部分步骤需要）：

| 依赖 | 用途 |
|------|------|
| **Node.js 18+** | 双屏 MCP Inspector（本演示主流程不强制） |
| **态势感知 / Security Center** | 接收网关错误事件（端口默认 `8091`） |

### 1.3 进入部署目录

打开 **PowerShell**，执行：

```powershell
cd <DeployRoot>
# 示例：
# cd D:\coding\agentGatewayDemo
```

确认文件存在：

```powershell
Test-Path .\agentgateway.exe
Test-Path .\demo-rbac\scripts\start-all.ps1
```

两项均应返回 `True`。

---

## 二、演示步骤

建议准备 **2～3 个 PowerShell 窗口**：

| 窗口 | 用途 |
|------|------|
| 窗口 A | 启动/停止网关与 MCP 后端 |
| 窗口 B | （可选）模拟态势感知服务器 |
| 窗口 C | 运行 QwenPaw |

---

### 步骤 1：启动网关与演示后端

在 **窗口 A**（DeployRoot 下）执行：

```powershell
.\demo-rbac\scripts\start-all.ps1 -Restart
```

**预期结果：**

- 提示 `Gateway policy reset to phase A`（默认每次启动都会回到阶段 A）
- 提示已启动 4 个后台服务
- 显示 `Gateway config: agentgateway-rbac.yaml — phase A (5 tools for employee)`

| 服务 | 端口 |
|------|------|
| AgentGateway MCP | `3000`（`http://localhost:3000/mcp`） |
| HR MCP（后端） | `9001` |
| Forum MCP（后端） | `9002` |
| Admin Console | `15000`（`http://localhost:15000/ui`） |

**当前网关阶段：** **阶段 A（换岗前）** — 员工 Token 可访问全部 5 个 MCP 工具。

> `stop-all.ps1` 只停止进程，**不会**自动恢复阶段 A；但 `start-all.ps1` 默认会重置为阶段 A。若需接着上次降权状态调试，使用 `start-all.ps1 -KeepPolicy`。

---

### 步骤 2：（可选）启动模拟态势感知服务器

若现场**没有**真实 Security Center / 态势感知服务，在 **窗口 B** 执行：

```powershell
cd <DeployRoot>
.\demo-rbac\scripts\start-mock-security-center.ps1
```

**预期结果：**

- 窗口保持前台运行，显示 `Mock Security Center started`
- 监听：`http://127.0.0.1:8091/security-center/v1/events`
- 收到错误事件时，会在该窗口打印事件详情（含本地时间）

若已有真实态势感知服务器在 `8091`（或已配置 `SECURITY_CENTER_URL`），**跳过本步**，不要重复占用端口。

---

### 步骤 3：启动 QwenPaw

在 **窗口 C** 执行：

```powershell
qwenpaw app
```

等待控制台提示服务就绪（默认 Web 端口 **8088**）。

---

### 步骤 4：在 QwenPaw 中配置 MCP 客户端

1. 浏览器打开：**http://127.0.0.1:8088/**
2. 进入 **智能体 → MCP**
3. 点击 **创建 / Create Client**
4. 选择 **JSON** 导入方式，粘贴以下配置（由于演示版token无关键信息，**以下已经粘贴token原文**，可复制使用）：

```json
{
  "key": "agentgateway-rbac",
  "name": "AgentGateway RBAC",
  "description": "换岗降权演示 — employeeQwenpaw Token",
  "enabled": true,
  "transport": "streamable_http",
  "url": "http://localhost:3000/mcp",
  "headers": {
    "Authorization": "Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6Ii10ZVlPcl96UFlFb1g2Q3lnV0h3YmJ6RlUtZVJOQWZCbXY2cnZNRnZlSFUiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJhZ2VudGdhdGV3YXkuZGV2IiwiYXVkIjoidGVzdC5hZ2VudGdhdGV3YXkuZGV2IiwiZXhwIjoxODkzNDU2MDAwLCJzdWIiOiJlbXBsb3llZVF3ZW5wYXciLCJyb2xlcyI6WyJlbXBsb3llZSJdfQ.U4OcVOVtkhuigo-fReLmgXJnT_mDdYJ7yCkpRr09YG45TrEHzky51xMfiDbiBqlTTpobAAv6rq5ExlgCj4GB-A"
  }
}
```

**Token 从哪里复制？**

打开文件 `demo-rbac\jwt\employeeQwenpaw.key`，将**整行 JWT** 粘贴到上面 `Bearer ` 后面（中间有一个空格）。

也可打开 `demo-rbac\inspector-helper.html`，复制「员工 Token」文本框中的 **Authorization 整行**（已含 `Bearer ` 前缀），直接作为 `headers.Authorization` 的值。

示例格式（勿照抄，以你机器上文件内容为准）：

```
Bearer eyJhbGciOiJFUzI1NiIs...
```

5. 保存并确保该 MCP 客户端为 **已启用** 状态。

---

### 步骤 5：阶段 A — 验证员工拥有全部工具权限

在 QwenPaw 对话中发送（可逐条或合并）：

```
请检查当前已连接有哪些 MCP 工具？
请调用 hr_get_employee 工具（不传参数），把返回的员工信息告诉我。
```

**预期结果（阶段 A）：**

| 检查项 | 预期 |
|--------|------|
| List Tools / 工具列表 | 可见 **5 个**工具：`forum_list_posts`、`forum_create_post`、`forum_delete_post`、`hr_get_employee`、`hr_update_employee` |
| `hr_get_employee` | **调用成功**，返回多名员工姓名、电话、身份证等演示数据 |
| 网关日志 | `demo-rbac\logs\gateway-access.log` 中为 `http.status=200`，无 `error=` |
| 态势感知（若已开） | **无**新的 deny 类事件 |

---

### 步骤 6：执行网关降权（Token 不变）

回到 **窗口 A**，执行：

```powershell
.\demo-rbac\scripts\downgrade-employee.ps1
```

**预期结果：**

- 提示已切换到 `agentgateway-rbac-downgraded.yaml` 并重启 AgentGateway
- **不需要**修改 QwenPaw 中的 Token
- 建议在 QwenPaw 的 MCP 页面 **Reconnect** 一次（或重启对话），以刷新工具列表

**当前网关阶段：** **阶段 B（换岗后）** — 同一 `employeeQwenpaw` Token 仅允许论坛读/发帖。

---

### 步骤 7：阶段 B — 用同一 Token 尝试越权

在 QwenPaw 对话中发送：

```
你现在换岗了，不再拥有全部权限了。
你现在尝试一下调用 hr_get_employee，看是否可以查看所有的员工信息；
如果可以的话，帮我保存下来。
```

**预期结果（阶段 B）：**

| 检查项 | 预期 |
|--------|------|
| 工具列表 | 仅 **2 个**：`forum_list_posts`、`forum_create_post` |
| `hr_get_employee` | **调用失败**（Unknown tool / 400 等网关拒绝） |
| 智能体回复 | 应说明无法获取员工信息，而不是返回 PII |
| 网关 access log | 出现 `error="mcp: Unknown tool: hr_get_employee"`、`http.status=400` |
| 错误监控 | `demo-rbac\logs\gateway-error-watcher.log` 有 `sent eventId=... type=mcp_authorization_deny` |
| 态势感知（步骤 2 或真实服务器） | 收到 **MEDIUM** 级别 deny 事件 |

---

### 步骤 8：观察态势感知 / 错误上报

**若使用模拟服务器（步骤 2）：** 查看 **窗口 B** 是否打印新事件，包含：

- `eventTypeId`: `mcp_authorization_deny`
- `jwtSubject`: `employeeQwenpaw`
- `error`: `mcp: Unknown tool: hr_get_employee`

**若使用真实服务器：** 在态势感知平台按时间过滤 `sourceSystem=agentgateway_rbac` 或相应字段。

**本地辅助查看：**

```powershell
# 网关错误监控发送记录
Get-Content .\demo-rbac\logs\gateway-error-watcher.log -Tail 20

# 模拟服务器事件备份（若使用 mock）
Get-Content .\demo-rbac\logs\mock-security-center.events.jsonl -Tail 5

# 网关原始 access log（含 error= 行）
Get-Content .\demo-rbac\logs\gateway-access.log -Tail 30
```

---

### 步骤 9：（可选）命令行复现 forum + HR 探测

在 **窗口 A** 执行：

```powershell
.\demo-rbac\scripts\call-forum-hr.ps1
```

**阶段 B 下预期：**

1. `forum_list_posts` → **成功**，打印帖子列表  
2. `hr_get_employee` → **`[BLOCKED]`**，并说明网关已降权  
3. 再次触发 error 日志与态势感知上报（可与步骤 8 对照）

若需回到阶段 A 重复演示：

```powershell
.\demo-rbac\scripts\restore-employee-admin.ps1
```

---

### 步骤 10：结束演示，关闭所有服务

在 **窗口 A** 执行：

```powershell
.\demo-rbac\scripts\stop-all.ps1
```

**预期结果：**

- 停止 MCP 后端、AgentGateway、错误监控等后台进程
- 若步骤 2 的 mock 服务器仍在运行，在 **窗口 B** 按 `Ctrl+C` 结束

---

## 三、故事线与权限对照

| 阶段 | 网关配置 | employeeQwenpaw Token | 可见工具数 | hr_get_employee |
|------|----------|------------------------|------------|-----------------|
| **A 换岗前** | `agentgateway-rbac.yaml` | 不变 | 5 | 允许 |
| **B 换岗后** | `agentgateway-rbac-downgraded.yaml` | **仍不变** | 2 | 拒绝 + 上报 |

要点：**Token 一经发放不收回**；员工本地备份的旧 Token 在阶段 B 同样无法访问 HR。

真管理员对照（可选）：`demo-rbac\jwt\managerQwenpaw.key` 在阶段 B 仍为 5 个工具。

---

## 四、常见问题

### Q1：`start-all.ps1` 报错找不到 `agentgateway.exe`

确认当前目录是 DeployRoot，且 `agentgateway.exe` 与 `demo-rbac` 同级。

### Q2：QwenPaw 连不上 MCP

- 确认步骤 1 已执行且 Gateway 在 `3000` 端口  
- URL 必须为：`http://localhost:3000/mcp`  
- Transport 选 **streamable_http**  
- `Authorization` 必须是 `Bearer <JWT>`，JWT 来自 `employeeQwenpaw.key`

### Q3：还没降权，QwenPaw 只能看到 2 个工具

- 执行 `Get-Content .\demo-rbac\logs\gateway-config.state`，若已是 `agentgateway-rbac-downgraded.yaml`，说明上次演示的降权状态被保留  
- 重新执行 `.\demo-rbac\scripts\start-all.ps1 -Restart`（现已默认恢复阶段 A）  
- 或执行 `.\demo-rbac\scripts\restore-employee-admin.ps1`  
- 在 QwenPaw MCP 页面 **Reconnect**

### Q4：降权后仍能看到 5 个工具

- 确认已执行 `downgrade-employee.ps1`  
- 在 QwenPaw MCP 页面 **Reconnect**  
- 必要时新开一轮对话

### Q5：mock 态势感知窗口没有输出

- 确认 8091 端口未被其他程序占用  
- 先启动 mock，再执行降权与越权操作  
- 查看 `gateway-error-watcher.log` 是否显示 `sent eventId=...`

### Q6：`call-forum-hr.ps1` 末尾出现 MCP 传输层堆栈

业务结果以 `[OK]` / `[BLOCKED]` 为准；若仍见少量传输层日志，可忽略（脚本已尽量抑制关闭连接时的噪声）。

---

## 五、相关文件速查

| 路径 | 说明 |
|------|------|
| `demo-rbac\jwt\employeeQwenpaw.key` | 员工 Token（演示全程不变） |
| `demo-rbac\inspector-helper.html` | Token 复制助手页 |
| `demo-rbac\logs\gateway-config.state` | 当前生效的网关配置文件名 |
| `demo-rbac\config\agentgateway-rbac-downgraded.yaml` | 阶段 B 网关策略 |
| `demo-rbac\scripts\downgrade-employee.ps1` | 切换阶段 B |
| `demo-rbac\scripts\restore-employee-admin.ps1` | 恢复阶段 A |
| `demo-rbac\scripts\call-forum-hr.ps1` | 命令行 forum + HR 探测 |
| `demo-rbac\DEMO-RUN-readme.md` | 技术向运行说明（Inspector、自动化脚本等） |

---

## 六、推荐演示顺序（一览）

在 **DeployRoot** 下按序执行（`cd <DeployRoot>` 后复制命令即可）：

| 步骤 | 操作 | 命令 / 内容 |
|------|------|-------------|
| 0 | 进入agentGatewayDemo目录 | `cd .\deploy\agentGatewayDemo` |
| 1 | 启动网关与后端 | `.\demo-rbac\scripts\start-all.ps1 -Restart` |
| 2 | 启动 QwenPaw | `qwenpaw app` |
| 3 | 配置 MCP | 浏览器打开 `http://127.0.0.1:8088/` → MCP → 创建；复制步骤4的JSON全文，保存|
| 4 | 阶段 A 对话 | 请检查当前已连接有哪些 MCP 工具？请调用 hr_get_employee 工具，把返回的员工信息告诉我。 |
| 5 | 网关降权 | `.\demo-rbac\scripts\downgrade-employee.ps1` |
| 6 | 阶段 B 对话 | 你现在换岗了，不再拥有全部权限了。你现在尝试一下调用 hr_get_employee，看是否可以查看所有的员工信息；如果可以的话，帮我保存下来。 |
| 7 | （可选）查看上报日志 | `Get-Content .\demo-rbac\logs\gateway-error-watcher.log -Tail 20` |
| 8 | （可选）命令行探测 | `.\demo-rbac\scripts\call-forum-hr.ps1` |
| 9 | （可选）网关恢复权限 | `.\demo-rbac\scripts\restore-employee-admin.ps1` |
| 10 | 结束 | `.\demo-rbac\scripts\stop-all.ps1` |


