# Security

CoPaw includes built-in security features to protect your agent from malicious inputs and unsafe skills. These are configured in the Console under **Settings → Security**, or via `config.json`.

## Overview

CoPaw's security system consists of three core security layers:

```
Security Architecture:
├─ Tool Guard — Runtime tool call protection
│  Detects dangerous command patterns, injection attacks, and malicious operations
│  using regex-based rules
│
├─ File Guard — Sensitive file access control
│  Blocks agent access to protected files and directories
│
└─ Skill Scanner — Pre-activation skill security scanning
   Scans for malicious code, hardcoded secrets, and security threats
   before skills are enabled
```

**Additional feature**: Web Authentication — Optional login protection for the Console interface

**Key concepts**:

- **Tool Guard** inspects tool calls in real-time before execution, using regex rules to detect dangerous patterns
- **File Guard** operates independently to protect sensitive files and directories from unauthorized access
- **Skill Scanner** runs before skills are enabled to detect malicious code and security threats
- **Web Authentication** (optional) controls access to the Console interface

---

## Tool Guard

The **Tool Guard** scans tool parameters **before** the agent invokes a tool, detecting dangerous patterns such as command injection, path traversal, or data exfiltration attempts, and blocks potentially malicious operations.

### How it works

1. When the agent calls a tool, the Tool Guard inspects relevant parameters. Built-in regex rules primarily target **`execute_shell_command`**.
2. Regex rules detect dangerous patterns, for example:
   - `rm -rf /` — Dangerous file deletion
   - SQL-injection-like fragments
   - Command substitution `$(...)` or `` `...` ``
   - Path traversal `../`
   - Privilege escalation `sudo`, `su`
   - Reverse shells, fork bombs, etc.
     (Exact coverage depends on built-in and custom rules.)
3. Each rule has an independent severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)
4. For CRITICAL or HIGH findings: in the Console / interactive sessions, the tool call enters a pending-approval flow — you approve or reject before it runs. In non-interactive contexts without a session, findings are logged and execution may still proceed — use **`denied_tools`** to hard-block specific tools or tighten rules when needed.

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

| Field            | Description                                                                                                                                           |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`        | Enable or disable Tool Guard entirely. Can also be set via the `COPAW_TOOL_GUARD_ENABLED` environment variable (takes precedence).                    |
| `guarded_tools`  | Specify guard scope:<br>• `null` (default) — guard all built-in tools<br>• `[]` — guard nothing<br>• `["tool_a", "tool_b"]` — guard only listed tools |
| `denied_tools`   | Tools that are always blocked regardless of parameters.                                                                                               |
| `custom_rules`   | User-defined regex rules (see format below).                                                                                                          |
| `disabled_rules` | Built-in rule IDs to disable.                                                                                                                         |

#### Custom rule format

Each custom rule is a JSON object with the following fields:

```json
{
  "id": "CUSTOM_RULE_ID",
  "tools": ["execute_shell_command"],
  "params": ["command"],
  "category": "command_injection",
  "severity": "HIGH",
  "patterns": ["pattern1", "pattern2"],
  "exclude_patterns": ["safe_pattern"],
  "description": "Brief description of what this rule detects",
  "remediation": "How to fix or avoid this issue"
}
```

| Field              | Type            | Required | Description                                                                          |
| ------------------ | --------------- | -------- | ------------------------------------------------------------------------------------ |
| `id`               | string          | **Yes**  | Unique identifier for this rule (use UPPERCASE_WITH_UNDERSCORES)                     |
| `tools`            | string or array | No       | Tool name(s) this rule applies to. Empty array or omitted means "all tools"          |
| `params`           | string or array | No       | Parameter name(s) to scan. Empty array or omitted means "all string parameters"      |
| `category`         | string          | **Yes**  | Threat category (see available categories below)                                     |
| `severity`         | string          | **Yes**  | Severity level: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, or `INFO`                       |
| `patterns`         | array           | **Yes**  | Regular expressions to match dangerous patterns (case-insensitive)                   |
| `exclude_patterns` | array           | No       | Regular expressions to exclude (allowlist patterns that should NOT trigger the rule) |
| `description`      | string          | No       | Human-readable description of the threat                                             |
| `remediation`      | string          | No       | Guidance on how to fix or avoid the issue                                            |

**Available threat categories**: `command_injection`, `data_exfiltration`, `path_traversal`, `sensitive_file_access`, `network_abuse`, `credential_exposure`, `resource_abuse`, `prompt_injection`, `code_execution`, `privilege_escalation`

**Example custom rules**:

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "custom_rules": [
        {
          "id": "BLOCK_PRODUCTION_DB_ACCESS",
          "tools": ["execute_shell_command"],
          "params": ["command"],
          "category": "sensitive_file_access",
          "severity": "CRITICAL",
          "patterns": ["psql.*prod", "mysql.*production"],
          "description": "Prevent direct access to production databases",
          "remediation": "Use read-only replica or staging database instead"
        },
        {
          "id": "WARN_NPM_GLOBAL_INSTALL",
          "tools": ["execute_shell_command"],
          "params": ["command"],
          "category": "resource_abuse",
          "severity": "MEDIUM",
          "patterns": ["npm\\s+install\\s+-g", "npm\\s+i\\s+-g"],
          "exclude_patterns": ["npm\\s+install\\s+-g\\s+(typescript|eslint)"],
          "description": "Warn about global npm installations",
          "remediation": "Install packages locally in project dependencies"
        }
      ]
    }
  }
}
```

### Console management

In the Console under **Settings → Security → Tool Guard** tab, you can:

![tool guard](https://img.alicdn.com/imgextra/i3/O1CN01RI8YBr1JorIWpB4uI_!!6000000001076-2-tps-3822-2064.png)

- **Enable/disable Tool Guard** — Master switch; when disabled, all tool calls bypass checks
- **Select guard scope** — Leave empty to guard all tools, or specify a list of tools to guard
- **Set denied tools** — Configure tools that are unconditionally blocked and cannot be invoked at all
- **Manage rules** — View, add, edit, and disable rules:
  - **Built-in rules** — System-provided security rules; individual rules can be disabled
  - **Custom rules** — Add organization-specific detection rules with regex patterns and severity levels
  - **Rule preview** — Click to preview detailed patterns and descriptions for each rule
- **Save configuration** — Click "Save" to persist changes; **changes take effect immediately without restart**

### Built-in Rules

Tool Guard includes the following built-in detection rules (for `execute_shell_command` tool):

**Command Injection & File Operations (HIGH):**

| Rule ID                       | Detection Target         | Description                                              |
| ----------------------------- | ------------------------ | -------------------------------------------------------- |
| `TOOL_CMD_DANGEROUS_RM`       | `rm` command             | Detects file removal operations that may cause data loss |
| `TOOL_CMD_DANGEROUS_MV`       | `mv` command             | Detects operations that may move or overwrite files      |
| `TOOL_CMD_UNSAFE_PERMISSIONS` | `chmod -R 777`, `chattr` | Global permission changes or immutable flags             |

**Low-Level Disk Operations (CRITICAL):**

| Rule ID                   | Detection Target                           | Description                                          |
| ------------------------- | ------------------------------------------ | ---------------------------------------------------- |
| `TOOL_CMD_FS_DESTRUCTION` | `mkfs`, `dd of=/dev/`, block device writes | Detects low-level disk formatting or wiping commands |

**Resource Abuse (CRITICAL/HIGH):**

| Rule ID                    | Severity | Detection Target                                | Description                                     |
| -------------------------- | -------- | ----------------------------------------------- | ----------------------------------------------- |
| `TOOL_CMD_DOS_FORK_BOMB`   | CRITICAL | Fork bombs `:(){ :\|:& };:`, `kill -9 -1`       | Detects fork bombs and mass process termination |
| `TOOL_CMD_SYSTEM_REBOOT`   | CRITICAL | `reboot`, `shutdown`, `halt`, `init 0/6`        | Terminates the host system                      |
| `TOOL_CMD_SERVICE_RESTART` | HIGH     | `systemctl restart/stop`, `service ... restart` | Manages or disrupts system services             |
| `TOOL_CMD_PROCESS_KILL`    | HIGH     | `pkill`, `killall`, `kill` (excludes `kill $$`) | Terminates processes that may be critical       |

**Code Execution (CRITICAL/HIGH):**

| Rule ID                    | Severity | Detection Target                    | Description                                       |
| -------------------------- | -------- | ----------------------------------- | ------------------------------------------------- |
| `TOOL_CMD_PIPE_TO_SHELL`   | CRITICAL | `curl/wget ... \| bash/sh` patterns | Downloads and immediately executes remote scripts |
| `TOOL_CMD_OBFUSCATED_EXEC` | HIGH     | `base64 -d \| bash` patterns        | Executes base64-encoded commands                  |

**Privilege Escalation (CRITICAL/HIGH):**

| Rule ID                         | Severity | Detection Target                             | Description                                         |
| ------------------------------- | -------- | -------------------------------------------- | --------------------------------------------------- |
| `TOOL_CMD_PRIVILEGE_ESCALATION` | CRITICAL | `sudo`, `su`, `doas`, `pkexec`               | Executes commands with elevated privileges          |
| `TOOL_CMD_SYSTEM_TAMPERING`     | HIGH     | `crontab`, `authorized_keys`, `/etc/sudoers` | Accesses cron jobs, SSH keys, or sudo configuration |

**Network Abuse (CRITICAL):**

| Rule ID                  | Detection Target                   | Description                                   |
| ------------------------ | ---------------------------------- | --------------------------------------------- |
| `TOOL_CMD_REVERSE_SHELL` | `/dev/tcp`, `nc -e`, `socat EXEC:` | Establishes reverse shells or network tunnels |

**Usage recommendations**:

- Keep CRITICAL level rules enabled; these represent the most dangerous operations
- HIGH level rules can be adjusted based on actual use cases; some legitimate operations may trigger them
- Use `disabled_rules` config to disable rules that don't apply to your use case
- Use `custom_rules` to add organization-specific security rules

---

## File Guard

The **File Guard** blocks agent tools from accessing sensitive files and directories. It runs automatically on **every tool call**, scanning all file-path-related parameters to enforce a deny list of protected paths.

### How it works

File Guard operates as the "File Path Guardian" within the Tool Guard engine, working alongside the Rule-based Guardian:

1. **Independent operation** — File Guard checks every tool call even when Tool Guard is disabled (`tool_guard.enabled = false`), as long as `file_guard.enabled = true`
2. **Multi-scenario detection** — Uses different path extraction strategies for different tools:
   - **Known file tools** (`read_file`, `write_file`, `edit_file`, etc.) — Directly checks the `file_path` parameter
   - **Shell commands** (`execute_shell_command`) — Extracts file paths from the command string, including redirection targets (like `>`, `>>`, `<`)
   - **Other tools** — Scans all string parameters that look like file paths
3. **Path normalization** — Automatically handles relative paths, `~` expansion, and converts to absolute paths for matching
4. **Recursive directory protection** — Paths ending with `/` are treated as directories; all files and subdirectories within are recursively blocked
5. **Blocking mechanism** — When a match is found, the tool call is blocked with a HIGH-severity finding

**Default protection**: The `{WORKING_DIR}.secret/` directory (which stores API keys, authentication credentials, and provider configurations) is included in the sensitive-file list by default. By default, `WORKING_DIR` is `~/.copaw/`, making the full path `~/.copaw.secret/`.

### Configuration

In `config.json`:

```json
{
  "security": {
    "file_guard": {
      "enabled": true,
      "sensitive_files": ["~/.ssh/", "/etc/passwd", "~/.copaw.secret/"]
    }
  }
}
```

| Field             | Description                                                                                                                                                                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`         | Enable or disable File Guard (default: `true`). When disabled, file path checks are skipped.                                                                                                                                                |
| `sensitive_files` | List of file/directory paths to block from tool access. Supports:<br>• Absolute paths: `/etc/passwd`<br>• Relative paths: `secrets/api_keys.json`<br>• User home: `~/.ssh/`<br>• Directory guards: ending with `/` for recursive protection |

**Path handling rules**:

- Relative paths are resolved relative to the current workspace directory
- `~` is automatically expanded to the user's home directory
- All paths are normalized to absolute paths for matching
- Directory paths (ending with `/`) recursively protect all contents within

### Console management

In the Console under **Settings → Security → File Guard** tab, you can:

![file guard](https://img.alicdn.com/imgextra/i1/O1CN01tOHz591o77Z0SsWXA_!!6000000005177-2-tps-3822-2064.png)

- **Enable/disable File Guard** — Independent toggle; controls file protection without affecting other Tool Guard features
- **View protection list** — Table display of all protected paths:
  - Folder icon identifies directory protection
  - File icon identifies individual file protection
  - Orange tag highlights directory types
- **Add protected paths**:
  - Enter file or directory path in the input box
  - Supports absolute paths, relative paths, user home (`~`)
  - Ending with `/` protects entire directory and its contents
  - Press Enter or click "Add" to confirm
- **Remove protection** — Click the delete button to remove paths that no longer need protection
- **Save configuration** — Click "Save" to persist changes to `config.json`; **changes take effect immediately**
- **Reset changes** — Click "Reset" to revert to the last saved state

---

## Skill Scanner

The **Skill Scanner** automatically scans skills for security threats before they are enabled or installed, detecting risk patterns such as command injection, data exfiltration, hardcoded secrets, and social engineering to protect the system from malicious skills.

### How it works

1. **Trigger timing** — The scanner runs before activating a skill when:
   - Creating a new skill
   - Enabling a previously disabled skill
   - Importing a skill from Skill Hub
2. **Scanning mechanism**:
   - Uses YAML regex signature rules to detect dangerous patterns in skill files
   - Defaults to PatternAnalyzer based on the built-in signature library
   - Supports custom scan policies (ScanPolicy) and rules
3. **Smart caching** — Scan results are cached based on file modification time (mtime); unchanged skills are not rescanned
4. **Timeout protection** — Configurable timeout (default 30s) prevents scans from blocking indefinitely
5. **File safety**:
   - Automatically skips symbolic links to prevent path traversal attacks
   - Verifies all file real paths stay within the skill directory boundary
   - Skips binary and archive files by default (images, fonts, archives, etc.)

### Scanner modes

| Mode      | Behavior                                                                                                                |
| --------- | ----------------------------------------------------------------------------------------------------------------------- |
| **Block** | Scan and block unsafe skills. The operation fails with a detailed error; skill cannot be enabled.                       |
| **Warn**  | Scan and record findings, but allow the skill to proceed. Shows warning notification and logs to Scan Alerts. (default) |
| **Off**   | Disable scanning entirely; all skills pass through directly.                                                            |

**Configuration priority**: Environment variable `COPAW_SKILL_SCAN_MODE` > Console settings > `config.json`

Valid values: `block`, `warn`, `off`

### Scan Alerts

All scan findings (both blocked and warned) are recorded in the **Scan Alerts** tab. From the Console you can:

- **View detailed findings** — Click the "eye" icon to see specific findings for each alert:
  - Finding title and description
  - File path and line number where the issue occurs
  - Matched dangerous pattern
- **Add to whitelist** — Click the "shield" icon to add the skill to the whitelist, bypassing future scans for that exact content version
- **Remove alert** — Click the "trash" icon to delete a single alert record
- **Clear all** — Click the "Clear All" button to batch delete all alert records

Alert records include:

- Skill name
- Action type (blocked/warned)
- Detection time
- Detailed findings list

### Whitelist

**Where to add:** In the Console, go to **Settings → Security → Skill Scanner**, open the **Scan Alerts** tab, and click the shield icon (**Add to Whitelist**) on the row for that skill’s alert. Entries appear under the **Whitelist** tab for review and removal (see **Scan Alerts** and **Console management** above).
**Prerequisite:** The skill must have been scanned and show up as **blocked** or **warned** before it appears in Scan Alerts; you cannot add a whitelist entry from the Console with no prior alert. Advanced: edit `security.skill_scanner.whitelist` in `config.json` (see **Configuration** below).

Whitelisted skills bypass the security scan. The whitelist mechanism is based on **content hash verification**:

- Each whitelist entry contains:
  - Skill name
  - SHA-256 content hash (calculated from all skill file contents)
  - Added timestamp
- **Version locking** — If any skill file changes, the content hash changes, the whitelist entry becomes invalid, and the skill will be rescanned
- **Remove from whitelist** — Click the delete button to remove a whitelist entry; the system automatically disables the skill and prompts for rescanning

The whitelist is useful for:

- Self-developed skills that have been verified as safe
- False positives (scanner incorrectly identified)
- Trusted skills that need to bypass specific detections

### Console management

In the Console under **Settings → Security → Skill Scanner** tab, you can:

![skill scanner](https://img.alicdn.com/imgextra/i2/O1CN01oZHdxC1M983gp03Ox_!!6000000001391-2-tps-3822-2064.png)

**Configuration area**:

- **Scanner mode** — Dropdown to select "Block", "Warn", or "Off"
- **Timeout** — Set the maximum duration for scanning a single skill (5-300 seconds); stops after timeout

**Scan Alerts tab** (shows badge count when alerts exist):

![alarm](https://img.alicdn.com/imgextra/i4/O1CN01B3j7d21yhtWQ7b0NB_!!6000000006611-2-tps-3822-2064.png)

- View all blocked and warned records
- Click eye icon to view detailed findings
- Click shield icon to add skill to whitelist
- Click trash icon to delete individual records
- Use "Clear All" button for batch deletion

**Whitelist tab** (shows badge count when entries exist):

![white list](https://img.alicdn.com/imgextra/i1/O1CN01yZTkBE1EmVBHhaNwh_!!6000000000394-2-tps-3822-2064.png)

- View all whitelisted skills
- Shows skill name, content hash (first 16 chars), added time
- Click delete button to remove from whitelist (automatically disables skill)

**Note**: Changes to scanner mode and timeout are automatically saved and **take effect immediately**; no additional save button required.

### Custom rules (Advanced)

For scenarios requiring deep customization, the scanner supports programmatic configuration:

The scanner uses YAML rule files in `src/copaw/security/skill_scanner/rules/signatures/`. You can customize the scan policy via a YAML policy file:

```python
from copaw.security.skill_scanner import SkillScanner
from copaw.security.skill_scanner.scan_policy import ScanPolicy

policy = ScanPolicy.from_yaml("my_org_policy.yaml")
scanner = SkillScanner(policy=policy)
```

Built-in signature categories:

- `command_injection` — Command injection
- `data_exfiltration` — Data exfiltration
- `hardcoded_secrets` — Hardcoded secrets
- `prompt_injection` — Prompt injection
- `social_engineering` — Social engineering
- `supply_chain_attack` — Supply chain attacks
- `obfuscation` — Code obfuscation
- `resource_abuse` — Resource abuse
- `unauthorized_tool_use` — Unauthorized tool use

#### YAML Signature Format

Each YAML signature file contains a list of detection rules:

```yaml
# my_custom_signatures.yaml
- id: CUSTOM_API_KEY_LEAK
  category: hardcoded_secrets
  severity: CRITICAL
  patterns:
    - "api_key\\s*=\\s*['\"][a-zA-Z0-9]{32,}['\"]"
    - "API_KEY\\s*=\\s*['\"][a-zA-Z0-9]{32,}['\"]"
  exclude_patterns:
    - "example"
    - "test_api_key"
    - "<your_api_key_here>"
  file_types: [python, javascript, typescript]
  description: "Hardcoded API keys detected in code"
  remediation: "Use environment variables or secret management systems"

- id: CUSTOM_DANGEROUS_NETWORK_CALL
  category: data_exfiltration
  severity: HIGH
  patterns:
    - "requests\\.post\\([^)]*attacker\\.com"
    - "urllib\\.request\\.urlopen\\([^)]*suspicious"
  file_types: [python]
  description: "Suspicious network requests to untrusted domains"
  remediation: "Review and whitelist allowed domains"
```

**Field descriptions**:

| Field              | Type   | Required | Description                                                                    |
| ------------------ | ------ | -------- | ------------------------------------------------------------------------------ |
| `id`               | string | **Yes**  | Unique identifier for this signature (use UPPERCASE_WITH_UNDERSCORES)          |
| `category`         | string | **Yes**  | Threat category (see list above)                                               |
| `severity`         | string | **Yes**  | Severity level: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, or `INFO`                 |
| `patterns`         | array  | **Yes**  | Regular expressions to match dangerous patterns (case-insensitive)             |
| `exclude_patterns` | array  | No       | Patterns to exclude (reduces false positives)                                  |
| `file_types`       | array  | No       | File types to scan: `python`, `javascript`, `typescript`, `bash`, `json`, etc. |
| `description`      | string | No       | Human-readable description of the threat                                       |
| `remediation`      | string | No       | Guidance on how to fix the issue                                               |

**Usage tips**:

- Test patterns with real code samples before deploying
- Use `exclude_patterns` to filter out false positives from documentation and tests
- Specify `file_types` to improve performance and reduce false positives
- Start with `severity: MEDIUM` and adjust after observing results

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

---

## Complete Configuration Example

Here's a complete `config.json` with all security features configured:

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "guarded_tools": null,
      "denied_tools": ["execute_shell_command"],
      "custom_rules": [
        {
          "id": "CUSTOM_DANGEROUS_PATTERN",
          "tools": ["write_file"],
          "params": ["content"],
          "category": "data_exfiltration",
          "severity": "HIGH",
          "patterns": ["secret_key.*=", "password.*="],
          "description": "Detect hardcoded secrets in file content",
          "remediation": "Use environment variables or secret management"
        }
      ],
      "disabled_rules": ["TOOL_CMD_PROCESS_KILL"]
    },
    "file_guard": {
      "enabled": true,
      "sensitive_files": [
        "~/.ssh/",
        "~/.copaw.secret/",
        "/etc/passwd",
        "/etc/shadow",
        ".env",
        "secrets/"
      ]
    },
    "skill_scanner": {
      "mode": "warn",
      "timeout": 30,
      "whitelist": []
    }
  }
}
```

**Notes**:

- Configuration changes take effect immediately for most settings (no restart required)
- Environment variables override config file values (see each section for details)
- For Docker deployments, mount your config at `/app/working/config.json`

---

## Web Authentication

CoPaw supports optional web login authentication to protect the Console from unauthorized access. Authentication is **disabled by default** and must be explicitly enabled via the `COPAW_AUTH_ENABLED` environment variable.

![login](https://img.alicdn.com/imgextra/i3/O1CN01SP7Ppd289g5e9kKO6_!!6000000007890-2-tps-3822-2064.png)

### How it works

1. **Enable authentication** — Set `COPAW_AUTH_ENABLED=true` and start CoPaw
2. **Registration flow**:
   - On first visit, the Console shows a **registration page**
   - Create the single admin account (username + password)
   - System uses single-user mode, designed for personal use
3. **Login flow**:
   - After registration, subsequent visits show the **login page**
   - After entering credentials, a signed token is generated (valid for 7 days)
   - Token is stored in browser localStorage and automatically attached to all API requests
4. **Auto-registration** (optional):
   - Set `COPAW_AUTH_USERNAME` and `COPAW_AUTH_PASSWORD` environment variables
   - CoPaw automatically creates the admin account on startup, skipping web registration
   - Useful for Docker, Kubernetes, server management panels, and other automated deployments
5. **Localhost bypass** — Requests from localhost (`127.0.0.1` / `::1`) automatically skip authentication; CLI commands (`copaw app`, `copaw chat`, etc.) work without a token

**Security features**:

- Password stored as salted SHA-256 hash, no plaintext stored
- HMAC-SHA256 signed tokens with 7-day auto-expiry
- Uses only Python standard library (`hashlib`, `hmac`, `secrets`), no external dependencies
- `auth.json` file protected with `0o600` permissions (owner read/write only)

### Environment variables

| Variable              | Description                                  | Required |
| --------------------- | -------------------------------------------- | -------- |
| `COPAW_AUTH_ENABLED`  | Set to `true` to enable authentication       | **Yes**  |
| `COPAW_AUTH_USERNAME` | Pre-set admin username for auto-registration | Optional |
| `COPAW_AUTH_PASSWORD` | Pre-set admin password for auto-registration | Optional |

**Configuration notes**:

- `COPAW_AUTH_ENABLED=true` is the only required variable to enable authentication
- `COPAW_AUTH_USERNAME` and `COPAW_AUTH_PASSWORD` are used together:
  - Both set → Auto-creates admin account on startup (for automated deployments)
  - Not set or only one set → Register via web UI on first visit (interactive deployments)
- If a user is already registered, auto-registration environment variables are ignored

### Enable authentication

#### Script install / pip install

Set environment variables before starting:

**Linux / macOS:**

```bash
# Basic enable (web registration)
export COPAW_AUTH_ENABLED=true
copaw app

# Or: Auto-registration mode
export COPAW_AUTH_ENABLED=true
export COPAW_AUTH_USERNAME=admin
export COPAW_AUTH_PASSWORD=mypassword
copaw app
```

To make it permanent, add the `export` lines to your `~/.bashrc`, `~/.zshrc`, or equivalent.

**Windows (CMD):**

```cmd
set COPAW_AUTH_ENABLED=true
rem Optional: auto-registration
rem set COPAW_AUTH_USERNAME=admin
rem set COPAW_AUTH_PASSWORD=mypassword
copaw app
```

**Windows (PowerShell):**

```powershell
$env:COPAW_AUTH_ENABLED = "true"
# Optional: auto-registration
# $env:COPAW_AUTH_USERNAME = "admin"
# $env:COPAW_AUTH_PASSWORD = "mypassword"
copaw app
```

#### Docker

Pass environment variables with `-e` (recommended with auto-registration):

```bash
docker run -e COPAW_AUTH_ENABLED=true \
  -e COPAW_AUTH_USERNAME=admin \
  -e COPAW_AUTH_PASSWORD=mypassword \
  -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

> **Tip**: To skip auto-registration, remove `COPAW_AUTH_USERNAME` and `COPAW_AUTH_PASSWORD` and register via browser on first visit.

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

#### Environment file (.env)

You can also use a `.env` file:

```
COPAW_AUTH_ENABLED=true
COPAW_AUTH_USERNAME=admin
COPAW_AUTH_PASSWORD=mypassword
```

Then pass it to Docker with `--env-file .env`, or source it in your shell before running `copaw app`.

### Disable authentication

Remove or unset the environment variable and restart CoPaw:

```bash
# Linux / macOS
unset COPAW_AUTH_ENABLED
copaw app

# Docker — simply remove the -e flag. The example below includes volumes for persistence.
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working -v copaw-secrets:/app/working.secret agentscope/copaw:latest
```

### Password reset

If you forget your password, use the CLI to reset:

```bash
copaw auth reset-password
```

This command will:

1. Display the current registered username
2. Prompt for a new password (hidden input, requires confirmation twice)
3. Rotate the session signing secret (the key stored in `auth.json`), which **invalidates all existing sessions** — all logged-in devices must log in again with the new password

**Docker deployments**:

```bash
docker exec -it <container_name> copaw auth reset-password
```

**Alternative approach**:

To completely reset the authentication system:

```bash
# Delete the auth file
rm ~/.copaw.secret/auth.json  # or $WORKING_DIR.secret/auth.json
# Restart CoPaw; re-register on next visit
copaw app
```

### Logout

Click the **Logout** button at the bottom of the sidebar in the Console:

- Clears the token from browser localStorage
- Automatically redirects to the login page
- Requires re-entering credentials to access

**Automatic logout**:

- Token expires (after 7 days)
- Token becomes invalid (password reset or signing secret rotation)
- Server returns 401 unauthorized response

### Security details

| Feature               | Detail                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------ |
| Password storage      | Salted SHA-256 hash in `auth.json` (no plaintext stored)                                   |
| Token format          | HMAC-SHA256 signed payload, 7-day expiry                                                   |
| Token storage         | Browser localStorage, cleared on logout or 401 response                                    |
| External dependencies | None — uses only Python standard library (`hashlib`, `hmac`, `secrets`)                    |
| File permissions      | `auth.json` written with `0o600` (owner read/write only)                                   |
| Localhost bypass      | Requests from `127.0.0.1` / `::1` skip auth (CLI access unaffected)                        |
| CORS preflight        | `OPTIONS` requests pass through without auth check                                         |
| WebSocket auth        | Token passed via query parameter, restricted to upgrade requests only                      |
| Protected routes      | Only `/api/*` routes require authentication                                                |
| Public routes         | `/api/auth/login`, `/api/auth/register`, `/api/auth/status`, `/api/version`, static assets |
