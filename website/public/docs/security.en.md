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

---

## Web Authentication

CoPaw supports optional web login authentication to protect the Console from unauthorized access. Authentication is **disabled by default** and must be explicitly enabled via the `COPAW_AUTH_ENABLED` environment variable. When disabled, CoPaw behaves identically to the default configuration — no login page, no token checks.

### How it works

1. Set `COPAW_AUTH_ENABLED=true` and start CoPaw.
2. On first visit, the Console shows a **registration page** — create your admin account (username + password).
3. After registering, subsequent visits show the **login page**.
4. Only **one account** can be registered per deployment (single-user model, designed for personal use).
5. After login, a signed token (valid for 7 days) is stored in the browser's localStorage. All API requests include this token automatically.
6. Requests from **localhost** (`127.0.0.1` / `::1`) bypass authentication entirely, so CLI commands (`copaw app`, `copaw chat`, etc.) continue to work without a token.

### Environment variables

| Variable              | Description                          | Required                     |
| --------------------- | ------------------------------------ | ---------------------------- |
| `COPAW_AUTH_ENABLED`  | Set to `true` to enable auth         | Yes                          |
| `COPAW_AUTH_USERNAME` | Pre-set admin username on first boot | Optional (auto-registration) |
| `COPAW_AUTH_PASSWORD` | Pre-set admin password on first boot | Optional (auto-registration) |

- `COPAW_AUTH_ENABLED=true` is the only variable required to turn on authentication.
- `COPAW_AUTH_USERNAME` and `COPAW_AUTH_PASSWORD` are optional. When both are set and no user has been registered yet, CoPaw automatically creates the admin account on startup — useful for Docker orchestration, Kubernetes, server management panels (1Panel, Portainer, CasaOS, etc.), and other automated deployments where interactive web registration is not practical.
- If the auto-registration variables are not set, the first user registers through the web UI on first visit (the original behavior).

### Enable authentication

#### Script install / pip install

Set the environment variable before starting. Add `COPAW_AUTH_USERNAME` and `COPAW_AUTH_PASSWORD` if you want the admin account created automatically.

**Linux / macOS:**

```bash
export COPAW_AUTH_ENABLED=true
# Optional: pre-set admin credentials for automated setup
# export COPAW_AUTH_USERNAME=admin
# export COPAW_AUTH_PASSWORD=mypassword
copaw app
```

To make it permanent, add the `export` lines to your `~/.bashrc`, `~/.zshrc`, or equivalent.

**Windows (CMD):**

```cmd
set COPAW_AUTH_ENABLED=true
rem Optional: pre-set admin credentials for automated setup
rem set COPAW_AUTH_USERNAME=admin
rem set COPAW_AUTH_PASSWORD=mypassword
copaw app
```

**Windows (PowerShell):**

```powershell
$env:COPAW_AUTH_ENABLED = "true"
# Optional: pre-set admin credentials for automated setup
# $env:COPAW_AUTH_USERNAME = "admin"
# $env:COPAW_AUTH_PASSWORD = "mypassword"
copaw app
```

#### Docker

Pass the environment variables with `-e`:

```bash
docker run -e COPAW_AUTH_ENABLED=true \
  -e COPAW_AUTH_USERNAME=admin \
  -e COPAW_AUTH_PASSWORD=mypassword \
  -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

> Remove the `COPAW_AUTH_USERNAME` and `COPAW_AUTH_PASSWORD` lines if you prefer to register through the web UI on first visit.

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

If you forget your password, use the CLI:

```bash
copaw auth reset-password
```

This command will:

1. Display the current registered username.
2. Prompt for a new password (hidden input, with confirmation).
3. Rotate the JWT signing secret, which **invalidates all existing sessions** — anyone currently logged in will be required to log in again with the new password.

For Docker deployments, run the command inside the container:

```bash
docker exec -it <container_name> copaw auth reset-password
```

> **Alternative**: You can also delete the `auth.json` file from `SECRET_DIR` (default `~/.copaw/.secret/`) and restart CoPaw. This removes the registered account entirely and allows you to re-register from scratch on the next visit.

### Logout

Click the **Logout** button at the bottom of the sidebar in the Console. This clears the token from localStorage and redirects to the login page.

If a token expires (after 7 days) or becomes invalid, the Console automatically redirects to the login page.

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
