# Security

CoPaw includes built-in security features to protect your agent from malicious inputs and unsafe skills. These are configured in the Console under **Settings → Security**, or via `config.json`.

---

## Tool Guard

The **Tool Guard** scans tool execution parameters **before** the agent invokes a tool, detecting dangerous patterns such as command injection, path traversal, or data exfiltration attempts.

### How it works

1. When the agent calls a tool (e.g. `execute_shell_command`, `write_file`), the Tool Guard inspects the call parameters.
2. Built-in regex rules check for dangerous patterns like `rm -rf`, SQL injection, path traversal (`../`), etc.
3. If a CRITICAL or HIGH finding is detected, the tool call is blocked and the agent sees a denied message.

### Configuration

In `config.json`:

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

| Field            | Description                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| `enabled`        | Enable or disable Tool Guard entirely.                                                           |
| `guarded_tools`  | `null` = guard all built-in tools; `[]` = guard nothing; `["tool_a"]` = guard only listed tools. |
| `denied_tools`   | Tools that are always blocked regardless of parameters.                                          |
| `custom_rules`   | Additional regex rules (same format as built-in rules).                                          |
| `disabled_rules` | Built-in rule IDs to disable.                                                                    |

### Console management

In **Settings → Security → Tool Guard** you can:

- Toggle Tool Guard on/off
- Select which tools to guard
- View built-in rules and their descriptions
- Add custom rules with regex patterns and severity levels
- Disable specific built-in rules

---

## Skill Scanner

The **Skill Scanner** automatically scans skills for security threats (command injection, data exfiltration, hardcoded secrets, etc.) before they are enabled or installed.

### How it works

1. When a skill is created, enabled, or imported from the Hub, the scanner runs before activation.
2. The scanner uses YAML regex-signature rules to detect dangerous patterns in skill files.
3. Scan results are cached (mtime-based) — unchanged skills are not re-scanned.
4. A configurable timeout (default 30s) prevents scans from blocking indefinitely.

### Scanner modes

| Mode               | Behavior                                                                      |
| ------------------ | ----------------------------------------------------------------------------- |
| **Block**          | Scan and block unsafe skills. The operation fails with a detailed error.      |
| **Warn** (default) | Scan and record findings, but allow the skill to proceed. A warning is shown. |
| **Off**            | Disable scanning entirely.                                                    |

Set the mode in Console (**Settings → Security → Skill Scanner → Scanner Mode**) or via the environment variable `COPAW_SKILL_SCAN_MODE` (`block`, `warn`, or `off`). The environment variable takes precedence over the config file.

### Scan Alerts

All scan findings (both blocked and warned) are recorded in **Scan Alerts**. From the Console you can:

- View detailed findings for each alert
- Add a skill to the whitelist (bypasses future scans for that exact content version)
- Remove individual alerts or clear all

### Whitelist

Whitelisted skills bypass the security scan. Each whitelist entry records the skill name and a SHA-256 content hash — if the skill's files change, the whitelist entry no longer applies and the skill will be scanned again.

### Custom rules

The scanner uses YAML rule files in `src/copaw/security/skill_scanner/rules/signatures/`. You can customize the scan policy via a YAML policy file:

```python
from copaw.security.skill_scanner import SkillScanner
from copaw.security.skill_scanner.scan_policy import ScanPolicy

policy = ScanPolicy.from_yaml("my_org_policy.yaml")
scanner = SkillScanner(policy=policy)
```

### Configuration

In `config.json`:

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
