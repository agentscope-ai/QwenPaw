# AgentGateway × QwenPaw — 完整对话演示流程（统一接入）

本文件专门写 **用 QwenPaw 当演示界面** 的逐步操作。后端脚本仍在 PowerShell 里跑；观众只看浏览器里的 QwenPaw。

配套技术说明与命令行断言见 [Gateway_readme.md](./Gateway_readme.md)。换岗降权见 [Demo_readme.md](./Demo_readme.md)。

---

## 0. 窗口与文件

| 窗口 | 用途 |
|------|------|
| A | DeployRoot：启停后端 / 网关 |
| B | `qwenpaw app` |
| 浏览器 | http://127.0.0.1:8088/ |

DeployRoot 示例：`D:\coding\QwenPawGithub\QwenPaw\deploy\agentGatewayDemo`

### QwenPaw MCP 配置文件（演示中按顺序切换）

| 文件 | 何时用 | 含义 |
|------|--------|------|
| [`demo-rbac/qwenpaw/open-clients.json`](./demo-rbac/qwenpaw/open-clients.json) | 第一幕 | 直连三个 MCP，无 Authorization |
| （同一配置，先不改） | 第二幕 A | 启用网关后仍直连 → 应失败 |
| [`demo-rbac/qwenpaw/gateway-no-token.json`](./demo-rbac/qwenpaw/gateway-no-token.json) | 第二幕 B | 只连网关，无 Authorization → 应失败 |
| [`demo-rbac/qwenpaw/gateway-forged-client.json`](./demo-rbac/qwenpaw/gateway-forged-client.json) | 第二幕 C | 连网关 + 伪造 JWT → 应失败 |
| [`demo-rbac/qwenpaw/gateway-client.json`](./demo-rbac/qwenpaw/gateway-client.json) | 第三幕 | 连网关 + 合法 JWT → 应成功 |

生成/刷新后三个网关相关 JSON（含合法 Token，**勿在屏幕念出**）：

```powershell
cd <DeployRoot>
.\demo-rbac\scripts\print-qwenpaw-gateway-json.ps1
```

`enable-gateway.ps1` 也会自动调用上述脚本。

### QwenPaw 操作约定（每换一次 MCP 都做）

1. **智能体 → MCP**
2. **禁用或删除**上一幕不再需要的客户端（避免多个入口同时生效）
3. **创建 → JSON**，粘贴对应文件全文
4. 对该客户端 **Reconnect / 重新连接**
5. **新开一轮对话**（不要沿用旧会话）

---

## 1. 开场（演示前）

**窗口 A：**

```powershell
cd <DeployRoot>
.\demo-rbac\scripts\stop-all.ps1
```

**窗口 B：**

```powershell
qwenpaw app
```

浏览器打开控制台，确认模型可对话。

---

## 2. 第一幕 — 没有网关，谁都能访问

### 2.1 启动三个开放 MCP

**窗口 A：**

```powershell
.\demo-rbac\scripts\start-open-demo.ps1 -Restart
```

预期地址（均无鉴权）：

- HR `http://127.0.0.1:9001/mcp`
- Forum `http://127.0.0.1:9002/mcp`
- Finance `http://127.0.0.1:9003/mcp`

### 2.2 QwenPaw 导入直连配置

1. **智能体 → MCP → 创建**
2. 粘贴 [`open-clients.json`](./demo-rbac/qwenpaw/open-clients.json) 全文
3. 确认三个客户端均 **已启用**：`forum-direct` / `hr-direct` / `finance-direct`
4. 新开对话

### 2.3 对话（复制即用）

```
你现在是公司里的匿名 Agent：没有登录、没有 Token，并且是直连三个 MCP 地址（不是网关）。

请检查当前已连接的 MCP 工具，然后依次完成（证件号和金额请打码）：
1. 读取论坛帖子列表
2. 读取全部员工信息
3. 读取各部门预算
4. 发帖：标题「匿名也能发帖」，内容「没有鉴权」
5. 提交报销：部门 D-SALES，金额 88，用途「演示绕过」

最后用一句话总结：现在是否存在统一的身份校验？
```

### 2.4 预期与话术

- 工具名多为 **无前缀**：`list_posts`、`get_employee`、`get_department_budget` 等
- 读敏感数据、写操作都应成功
- **话术：** “入口、身份、策略、审计全部分散。Agent 要维护三个地址，服务也不知道调用者是谁。”

---

## 3. 第二幕 — 启用网关后：用 QwenPaw 连续演示三种失败

**讲解：** “不改业务工具协议。后端只信任网关；客户端必须持有合法用户 Token，并只走统一入口。”

**窗口 A：**

```powershell
.\demo-rbac\scripts\enable-gateway.ps1
```

此时：

- 三个后端变为 **protected**（校验网关内部凭证）
- AgentGateway 监听 `http://localhost:3000/mcp`（strict JWT）
- 已生成/刷新 `gateway-client.json`、`gateway-no-token.json`、`gateway-forged-client.json`

下面 **A → B → C** 全部在 QwenPaw 完成，不要跳过。

---

### 3.A 配置不变，直连应变失败（绕过网关）

**故意不改 MCP 配置**：三个 `*-direct` 仍启用，URL 仍是 `:9001/:9002/:9003`。

操作：

1. MCP 页面对三个直连客户端 **Reconnect**
2. **新开对话**

对话：

```
注意：后端刚刚启用了网关鉴权，但我这边的 MCP 配置完全没有改——仍然直连三个地址，也没有带任何 Token。

请再次检查 MCP 是否还能用：
1. 查看客户端/工具状态
2. 尝试调用 list_posts、get_employee、get_department_budget
3. 若失败，如实说明错误（如 401、Unauthorized、连接失败），不要编造成功
4. 用一句话对比：和刚才“谁都能访问”相比，现在发生了什么
```

**预期：** 调用失败 / 无法握手。  
**话术：** “Agent 配置一行没改。旧直连地址还在，但后端已只接受网关转发，所以绕过网关进不去了。”

---

### 3.B 统一入口、无 Token → 失败

1. **禁用或删除**三个 `*-direct`
2. 导入 [`gateway-no-token.json`](./demo-rbac/qwenpaw/gateway-no-token.json)
3. 只启用这一个客户端 → Reconnect → **新开对话**

对话：

```
现在我只连接统一网关 http://localhost:3000/mcp，但故意不携带 Authorization Token。

请尝试：
1. 列出可用 MCP 工具
2. 调用 forum_list_posts（或任意工具）

如果被拒绝，请说明这证明了什么（是否“只要连上网关地址就能用”）。
```

**预期：** 鉴权失败（无 bearer / 401）。  
**话术：** “统一入口也不允许匿名。没有合法用户 Token，连工具列表都拿不到。”

---

### 3.C 统一入口、伪造 Token → 失败

1. **禁用** `agentgateway-no-token`
2. 导入 [`gateway-forged-client.json`](./demo-rbac/qwenpaw/gateway-forged-client.json)
3. Reconnect → **新开对话**

对话：

```
现在我连接同一个网关地址，但 Authorization 里放的是伪造 Token（看起来像 JWT，签名无效）。

请尝试列出工具并调用 forum_list_posts。
如果失败，请说明：网关是在校验 Token 真伪，还是只要请求头里有 Bearer 字样就放行？
```

**预期：** 鉴权失败（JWT 校验失败）。  
**话术：** “不是有 Bearer 就放行，而是校验签名、issuer、audience。”

---

## 4. 第三幕 — 合法 Token：统一入口成功

1. **禁用** `agentgateway-forged`（以及残留的直连 / no-token）
2. 导入 [`gateway-client.json`](./demo-rbac/qwenpaw/gateway-client.json)  
   （若文件过期：先跑 `.\demo-rbac\scripts\print-qwenpaw-gateway-json.ps1`）
3. 确认 **仅** `AgentGateway Unified` 启用 → Reconnect → **新开对话**
4. **不要**在屏幕上滚动展示完整 JWT

对话：

```
你现在只能通过 AgentGateway 访问 MCP，并且已配置合法 Token。

请：
1. 列出当前全部 MCP 工具名称
2. 分别调用 forum_list_posts、hr_get_employee、finance_get_department_budget
3. 摘要回复，证件号和金额打码
4. 说明：客户端现在只配了一个地址，还是三个？工具名是否带 forum_/hr_/finance_ 前缀？
```

可选写操作：

```
请再用 forum_create_post 发帖：标题「网关后发帖」，作者 employeeQwenpaw，内容「合法 Token」；
用 finance_submit_expense 提交报销：部门 D-ENG，金额 100，用途「网关演示」。
```

**预期：**

| 检查项 | 结果 |
|--------|------|
| 工具数 | **7** |
| 工具名 | `forum_*` / `hr_*` / `finance_*` |
| 三类读取 | 成功 |
| 入口 | 仅 `http://localhost:3000/mcp` |

（可选）窗口 A 看审计：

```powershell
Get-Content .\demo-rbac\logs\gateway-access.log -Tail 20
```

关注 `jwt.sub=employeeQwenpaw`、`http.status=200`（勿贴完整 Token）。

---

## 5. 收尾与衔接到换岗降权

**话术：** “统一网关解决谁能进来；换岗降权演示继续解决进来以后能调哪些工具。”

```powershell
.\demo-rbac\scripts\stop-all.ps1
```

然后按 [Demo_readme.md](./Demo_readme.md) 另行开场（不要与本幕 Finance + unified 配置同时开着）。

在 QwenPaw MCP 页可清理本幕客户端，避免下次演示串台。

---

## 6. 提词器一览

| 顺序 | PowerShell | QwenPaw MCP 配置 | 对话目的 | 预期 |
|------|------------|------------------|----------|------|
| 1 | `start-open-demo.ps1 -Restart` | 导入 `open-clients.json` | 匿名直连读写 | 成功 |
| 2 | `enable-gateway.ps1` | **不改**直连配置，Reconnect | 旧直连失效 | 失败 |
| 3 | （已启用网关） | 只留 `gateway-no-token.json` | 网关无 Token | 失败 |
| 4 | （已启用网关） | 只留 `gateway-forged-client.json` | 伪造 Token | 失败 |
| 5 | （已启用网关） | 只留 `gateway-client.json` | 合法 Token | 成功 7 工具 |

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 第二幕 A 直连仍成功 | 确认 `enable-gateway.ps1` 已跑完；日志中 MCP 应为 `Auth: PROTECTED` |
| 换配置后工具列表还是旧的 | 禁用无关客户端 + Reconnect + **新开对话** |
| 合法 Token 也失败 | 重新执行 `print-qwenpaw-gateway-json.ps1` 并重新导入 `gateway-client.json` |
| 多个客户端同时启用导致混乱 | 每幕只保留当前要用的一个（第一幕例外：三个直连） |
| 屏幕上露出 JWT | 用文件导入，不要打开 JSON 给观众念 Bearer 后面的串 |
