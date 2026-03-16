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
