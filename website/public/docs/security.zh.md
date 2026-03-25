# 安全

CoPaw 内置了安全功能，保护你的 Agent 免受恶意输入和不安全技能的影响。这些功能在控制台 **设置 → 安全** 中配置，也可以通过 `config.json` 进行设置。

---

## 工具守卫

**工具守卫** 在 Agent 调用工具**之前**扫描工具执行参数，检测命令注入、路径遍历或数据外泄等危险模式。

### 工作原理

1. 当 Agent 调用工具（如 `execute_shell_command`、`write_file`）时，工具守卫会检查调用参数。
2. 内置的正则规则检查危险模式，如 `rm -rf`、SQL 注入、路径遍历（`../`）等。
3. 如果发现 CRITICAL 或 HIGH 级别的问题，工具调用会被阻止，Agent 会看到拒绝消息。

### 配置

在 `config.json` 中：

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "guarded_tools": null,
      "denied_tools": [],
      "custom_rules": [],
      "disabled_rules": []
    }
  }
}
```

| 字段             | 说明                                                                              |
| ---------------- | --------------------------------------------------------------------------------- |
| `enabled`        | 启用或禁用工具守卫。                                                              |
| `guarded_tools`  | `null` = 守护所有内置工具；`[]` = 不守护任何工具；`["tool_a"]` = 只守护指定工具。 |
| `denied_tools`   | 无论参数如何，始终被阻止的工具列表。                                              |
| `custom_rules`   | 附加的正则规则（格式与内置规则相同）。                                            |
| `disabled_rules` | 要禁用的内置规则 ID 列表。                                                        |

### 控制台管理

在 **设置 → 安全 → 工具守卫** 中，你可以：

- 开启/关闭工具守卫
- 选择要守护的工具
- 查看内置规则及其描述
- 添加自定义正则规则和严重级别
- 禁用特定的内置规则

---

## 文件防护

**文件防护** 阻止 Agent 工具访问敏感文件和目录。它在**每次工具调用**时运行（不仅限于受保护的工具），扫描文件路径参数和 shell 命令参数，以执行受保护路径的拒绝列表。

### 工作原理

1. 当任何工具被调用时，文件防护会检查其参数是否包含匹配敏感文件列表的路径。
2. 对于已知的文件工具（`read_file`、`write_file`、`edit_file` 等），直接检查 `file_path` 参数。
3. 对于 `execute_shell_command`，从命令字符串中提取文件路径（包括重定向目标如 `>`、`>>`、`<`）。
4. 对于所有其他工具，扫描每个看起来像文件路径的字符串参数。
5. 如果发现匹配，工具调用将以 HIGH 级别发现被阻止。

默认情况下，`.copaw.secret` 目录（存储认证凭据和 API 密钥的位置）会被包含在敏感文件列表中。

### 配置

在 `config.json` 中：

```json
{
  "security": {
    "file_guard": {
      "enabled": true,
      "sensitive_files": ["~/.ssh/", "/etc/passwd"]
    }
  }
}
```

| 字段              | 说明                                 |
| ----------------- | ------------------------------------ |
| `enabled`         | 启用或禁用文件防护（默认：`true`）。 |
| `sensitive_files` | 要阻止工具访问的文件/目录路径。      |

以 `/` 结尾的路径被视为目录防护 — 其中的所有文件和子目录都会被递归阻止。

### 控制台管理

在 **设置 → 安全 → 文件防护** 中，你可以：

- 开启/关闭文件防护
- 查看受保护的敏感路径列表
- 添加新的文件或目录路径进行保护
- 从保护列表中移除路径

---

## 技能扫描器

**技能扫描器** 在技能被启用或安装前，自动扫描安全威胁（命令注入、数据外泄、硬编码密钥等）。

### 工作原理

1. 创建、启用或从 Hub 导入技能时，扫描器会在激活前运行。
2. 扫描器使用 YAML 正则签名规则检测技能文件中的危险模式。
3. 扫描结果基于文件修改时间缓存 — 未更改的技能不会重复扫描。
4. 可配置的超时时间（默认 30 秒）防止扫描无限阻塞。

### 扫描模式

| 模式               | 行为                                               |
| ------------------ | -------------------------------------------------- |
| **拦截**           | 扫描并阻止不安全的技能，操作失败并显示详细错误。   |
| **仅提醒**（默认） | 扫描并记录发现，但允许技能继续使用。显示警告通知。 |
| **关闭**           | 完全禁用扫描。                                     |

在控制台（**设置 → 安全 → 技能扫描器 → 扫描模式**）或通过环境变量 `COPAW_SKILL_SCAN_MODE`（`block`、`warn` 或 `off`）设置。环境变量优先于配置文件。

### 扫描告警

所有扫描发现（拦截和提醒）都记录在 **扫描告警** 中。在控制台中你可以：

- 查看每条告警的详细发现
- 将技能加入白名单（跳过该特定内容版本的后续扫描）
- 删除单条告警或清除全部

### 白名单

白名单中的技能跳过安全扫描。每条白名单记录包含技能名称和 SHA-256 内容哈希 — 如果技能文件发生变化，白名单条目不再适用，技能将被重新扫描。

### 自定义规则

扫描器使用 `src/copaw/security/skill_scanner/rules/signatures/` 中的 YAML 规则文件。你可以通过 YAML 策略文件自定义扫描策略：

```python
from copaw.security.skill_scanner import SkillScanner
from copaw.security.skill_scanner.scan_policy import ScanPolicy

policy = ScanPolicy.from_yaml("my_org_policy.yaml")
scanner = SkillScanner(policy=policy)
```

### 配置

在 `config.json` 中：

```json
{
  "security": {
    "skill_scanner": {
      "mode": "block",
      "timeout": 30,
      "whitelist": []
    }
  }
}
```

---

## Web 登录认证

CoPaw 支持可选的 Web 登录认证，保护控制台免受未授权访问。认证**默认关闭**，需要通过 `COPAW_AUTH_ENABLED` 环境变量显式启用。关闭时，CoPaw 的行为与默认配置完全一致 — 无登录页面，无令牌检查。

### 工作原理

1. 设置 `COPAW_AUTH_ENABLED=true` 并启动 CoPaw。
2. 首次访问时，控制台显示**注册页面** — 创建管理员账户（用户名 + 密码）。
3. 注册完成后，后续访问显示**登录页面**。
4. 每个部署只能注册**一个账户**（单用户模式，专为个人使用设计）。
5. 登录后，签名令牌（有效期 7 天）存储在浏览器的 localStorage 中，所有 API 请求自动携带该令牌。
6. 来自**本地**（`127.0.0.1` / `::1`）的请求自动跳过认证，因此 CLI 命令（`copaw app`、`copaw chat` 等）无需令牌即可正常工作。

### 环境变量

| 变量                  | 说明                       | 是否必填         |
| --------------------- | -------------------------- | ---------------- |
| `COPAW_AUTH_ENABLED`  | 设为 `true` 启用认证       | 是               |
| `COPAW_AUTH_USERNAME` | 首次启动时预设管理员用户名 | 可选（自动注册） |
| `COPAW_AUTH_PASSWORD` | 首次启动时预设管理员密码   | 可选（自动注册） |

- `COPAW_AUTH_ENABLED=true` 是启用认证唯一必需的变量。
- `COPAW_AUTH_USERNAME` 和 `COPAW_AUTH_PASSWORD` 为可选项。当两者都设置且尚未注册过用户时，CoPaw 会在启动时自动创建管理员账户 — 适用于 Docker 编排、Kubernetes、服务器管理面板（1Panel、Portainer、CasaOS 等）及其他无法通过浏览器交互注册的自动化部署场景。
- 如果不设置自动注册变量，首次访问时通过网页注册第一个用户（原有行为不变）。

### 启用认证

#### 脚本安装 / pip 安装

在启动前设置环境变量。如需自动创建管理员账户，可同时设置 `COPAW_AUTH_USERNAME` 和 `COPAW_AUTH_PASSWORD`。

**Linux / macOS：**

```bash
export COPAW_AUTH_ENABLED=true
# 可选：预设管理员凭据，实现自动注册
# export COPAW_AUTH_USERNAME=admin
# export COPAW_AUTH_PASSWORD=mypassword
copaw app
```

如需永久生效，将 `export` 行添加到 `~/.bashrc`、`~/.zshrc` 或等效文件中。

**Windows (CMD)：**

```cmd
set COPAW_AUTH_ENABLED=true
rem 可选：预设管理员凭据，实现自动注册
rem set COPAW_AUTH_USERNAME=admin
rem set COPAW_AUTH_PASSWORD=mypassword
copaw app
```

**Windows (PowerShell)：**

```powershell
$env:COPAW_AUTH_ENABLED = "true"
# 可选：预设管理员凭据，实现自动注册
# $env:COPAW_AUTH_USERNAME = "admin"
# $env:COPAW_AUTH_PASSWORD = "mypassword"
copaw app
```

#### Docker

通过 `-e` 传递环境变量：

```bash
docker run -e COPAW_AUTH_ENABLED=true \
  -e COPAW_AUTH_USERNAME=admin \
  -e COPAW_AUTH_PASSWORD=mypassword \
  -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

> 如果希望首次访问时通过网页注册，移除 `COPAW_AUTH_USERNAME` 和 `COPAW_AUTH_PASSWORD` 即可。

#### docker-compose.yml

```yaml
services:
  copaw:
    image: agentscope/copaw:latest
    ports:
      - "127.0.0.1:8088:8088"
    environment:
      - COPAW_AUTH_ENABLED=true
      - COPAW_AUTH_USERNAME=admin
      - COPAW_AUTH_PASSWORD=mypassword
    volumes:
      - copaw-data:/app/working
      - copaw-secrets:/app/working.secret
```

#### 环境文件 (.env)

也可以使用 `.env` 文件：

```
COPAW_AUTH_ENABLED=true
COPAW_AUTH_USERNAME=admin
COPAW_AUTH_PASSWORD=mypassword
```

然后通过 `--env-file .env` 传递给 Docker，或在运行 `copaw app` 前在 shell 中 source 该文件。

### 关闭认证

移除或取消环境变量并重启 CoPaw：

```bash
# Linux / macOS
unset COPAW_AUTH_ENABLED
copaw app

# Docker — 移除 -e 参数即可。以下示例包含用于持久化的卷。
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working -v copaw-secrets:/app/working.secret agentscope/copaw:latest
```

### 重置密码

如果忘记密码，使用 CLI 命令：

```bash
copaw auth reset-password
```

该命令会：

1. 显示当前注册的用户名。
2. 提示输入新密码（隐藏输入，需确认）。
3. 轮换 JWT 签名密钥，**使所有现有会话失效** — 当前已登录的用户需要使用新密码重新登录。

Docker 部署时，在容器内运行该命令：

```bash
docker exec -it <容器名> copaw auth reset-password
```

> **替代方案**：也可以删除 `SECRET_DIR`（默认 `~/.copaw/.secret/`）下的 `auth.json` 文件并重启 CoPaw。这会完全移除已注册的账户，下次访问时可以重新注册。

### 退出登录

点击控制台侧边栏底部的**退出登录**按钮。这会清除 localStorage 中的令牌并跳转到登录页面。

如果令牌过期（7 天后）或失效，控制台会自动跳转到登录页面。

### 安全细节

| 特性           | 说明                                                                                  |
| -------------- | ------------------------------------------------------------------------------------- |
| 密码存储       | 加盐 SHA-256 哈希存储在 `auth.json` 中（不存储明文）                                  |
| 令牌格式       | HMAC-SHA256 签名载荷，7 天过期                                                        |
| 令牌存储       | 浏览器 localStorage，退出登录或收到 401 响应时清除                                    |
| 外部依赖       | 无 — 仅使用 Python 标准库（`hashlib`、`hmac`、`secrets`）                             |
| 文件权限       | `auth.json` 以 `0o600` 权限写入（仅所有者可读写）                                     |
| 本地免认证     | 来自 `127.0.0.1` / `::1` 的请求跳过认证（CLI 访问不受影响）                           |
| CORS 预检      | `OPTIONS` 请求无需认证直接放行                                                        |
| WebSocket 认证 | 令牌通过查询参数传递，仅限升级请求                                                    |
| 受保护路由     | 仅 `/api/*` 路由需要认证                                                              |
| 公开路由       | `/api/auth/login`、`/api/auth/register`、`/api/auth/status`、`/api/version`、静态资源 |
