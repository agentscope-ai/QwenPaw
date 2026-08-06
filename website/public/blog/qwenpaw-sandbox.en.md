---
title: "Introducing the QwenPaw 2.0 Sandbox"
date: 2026-07-29
author: QwenPaw Team
tags: [Sandbox, SecurityIsolation, Landlock, Seatbelt, Windows]
cover: https://img.alicdn.com/imgextra/i4/O1CN01lN8QDc1ZB2kAtxHH5_!!6000000003155-2-tps-1536-1024.png
excerpt: "Sandbox is QwenPaw's built-in isolation layer: kernel-level filesystem isolation, sensitive-path blocking, environment scrubbing, and approval escalation on violations—so agents only see and change what they should."
---

# Introducing the QwenPaw 2.0 Sandbox

## 1. What Is Sandbox

Sandbox is QwenPaw's built-in security isolation layer. When an AI Agent runs Shell commands or executes code, Sandbox confines those commands to a controlled environment—commands can only access files and resources you allow, and cannot reach sensitive information on the system.

In short: **Sandbox ensures agents "only see what they should see, and only change what they should change" when executing commands.**

## 2. Design Philosophy

QwenPaw Sandbox is built around four core principles:

### 2.1 Comprehensive Protection

Sandbox provides **kernel-level** mandatory isolation, not application-layer soft limits. No matter how a command inside the sandbox tries to bypass restrictions (privilege escalation, path traversal, symlink following, etc.), the operating system kernel blocks unauthorized access at the lowest layer. Specifically, Sandbox protects against:

- **Unauthorized file reads** — Prevents commands from stealing sensitive files such as SSH keys, API tokens, and cloud credentials
- **Unauthorized file writes** — Prevents commands from tampering with system configuration, planting backdoors, or overwriting critical data
- **Environment variable leakage** — Clears secrets such as API keys from the process environment to prevent exposure via `env`/`printenv`
- **Process escape** — Limits process visibility and propagation via PID namespaces (Linux) or Job Objects (Windows)
- **Resource exhaustion via timeouts** — Forcefully terminates timed-out processes to prevent infinite loops or resource exhaustion attacks

These protections are enforced directly by the OS kernel (Linux Landlock LSM / mount namespaces, macOS Seatbelt kernel policies, Windows security tokens and ACLs). No user-space code can bypass them.

### 2.2 Flexible Filesystem Isolation

Sandbox divides filesystem permissions into three levels:

| Permission Level | Capability                                                  | Typical Use                                      |
| ---------------- | ----------------------------------------------------------- | ------------------------------------------------ |
| **No read**      | No read, write, or execute; path is completely inaccessible | Sensitive credential directories (e.g. `~/.ssh`) |
| **Read-only**    | Read and execute allowed; no write                          | System libraries, dependencies, reference docs   |
| **Read-write**   | Read, write, and execute allowed                            | Workspace, build output directories              |

Based on these three levels, Sandbox combines four parameters into flexible isolation policies:

1.  `allow_read_all` — Controls default read permission. When `True` (default), all files on the system are readable by default; when `False`, only explicitly declared paths are readable
2.  `workspace_dir` — Workspace directory with full read-write permission; the Agent's primary working area
3.  `mounts` — List of explicitly mounted extra paths; each path's `writable` flag independently controls read-only (readable) vs read-write (writable)
4.  `deny_paths` — Explicit deny list; regardless of other rules, these paths are always inaccessible (no read). Highest priority

This layered design supports everyday development with "permissive reads + precise write control," and can switch to strict whitelist mode by turning off `allow_read_all`.

### 2.3 User-Friendly

Security should not get in the way of productivity. In normal use, Sandbox is fully transparent to users and Agents—commands run automatically inside the sandbox with no extra confirmation, and output format is identical to direct execution, so users do not perceive the isolation layer.

When a command hits a security boundary, Sandbox does not simply error or silently drop the request. It follows a **"restrict first, escalate later"** strategy: first attempt execution in the restricted environment; if the command truly needs permissions beyond the sandbox, the system shows a clear violation explanation and risk notice, and the user decides whether to approve unsandboxed re-execution. This avoids both the security gaps of "allow everything by default" and the workflow friction of "deny everything."

### 2.4 Native and Lightweight

Sandbox uses each operating system's native kernel-level isolation (Linux kernel namespaces, macOS kernel policies, Windows security tokens), not a cross-platform emulation layer. At startup, the system automatically detects platform capabilities and selects the best approach—users do not need to worry about underlying differences. When isolation is unavailable, it gracefully degrades to manual approval rather than silently skipping protection.

Unlike VMs or Docker containers, Sandbox does not start an extra OS instance or daemon, nor does it require building images or allocating virtual disks. It applies constraints directly in the host process via kernel security primitives, so:

- **Very low startup cost** — Extra latency < 50ms on Linux/macOS; no waiting for containers to start
- **Direct local filesystem access** — Commands in the sandbox operate on host files directly (within authorized scope), with no file copying or volume sync
- **No resource overhead** — No extra memory, CPU, or disk to maintain an isolation environment
- **Zero upfront dependencies** — Windows and macOS work out of the box; Linux only needs a lightweight package (`bubblewrap`) or native kernel support (Landlock)

---

## 3. Protections Provided by Sandbox

### 3.1 Filesystem Isolation

| Protection                   | Description                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| Workspace write limits       | Commands in the sandbox can only write to the current workspace directory and explicitly declared paths |
| Sensitive path blocking      | Directories such as `~/.ssh`, `~/.aws`, and `~/.gnupg` are fully blocked inside the sandbox             |
| System directories read-only | System paths such as `/usr`, `/lib`, and `/etc` are readable but not writable                           |
| Flexible mounts              | Policy rules can grant read or read-write access to specific directories                                |

### 3.2 Environment Variable Protection

The sandbox automatically clears the following environment variables to prevent the Agent from leaking your credentials:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_ACCESS_KEY_ID`

When commands run inside the sandbox, these variables are set to empty strings.

### 3.3 Default Sensitive Path Deny List

The following paths are denied by default inside the sandbox:

| Path                     | What It Protects                       |
| ------------------------ | -------------------------------------- |
| `~/.ssh`                 | SSH private keys and configuration     |
| `~/.aws`                 | AWS credentials                        |
| `~/.gnupg`               | GPG keys                               |
| `~/.kube`                | Kubernetes configuration               |
| `~/.config/gcloud`       | Google Cloud credentials               |
| `~/.azure`               | Azure CLI credentials                  |
| `~/.docker/config.json`  | Docker authentication                  |
| `~/.env`                 | Generic environment variable files     |
| `~/.claude`              | Claude Code configuration and memory   |
| `~/Library/Keychains`    | macOS Keychain                         |
| `~/.git-credentials`     | Git credentials                        |
| `~/.gitconfig`           | Git configuration (may contain tokens) |
| `~/.npmrc` / `~/.yarnrc` | npm/yarn auth tokens                   |
| `~/.pypirc`              | PyPI API tokens                        |
| `~/.netrc`               | Generic login credentials              |
| `~/.vault-token`         | HashiCorp Vault token                  |
| `~/.terraformrc`         | Terraform configuration                |
| `~/.config/nix`          | Nix configuration                      |

### 3.4 Network Access

The current Sandbox provides coarse control over network access inside the sandbox:

- **Allow all network connections** — Suitable for everyday development commands that need the network (`pip`, `git`, `npm`, `curl`, etc.)
- **Block network entirely** — Commands in the sandbox cannot establish any inbound or outbound connections

Network is allowed by default because many common development commands depend on connectivity; blocking everything would severely hurt usability. Future versions plan domain- or IP-based fine-grained filtering to further narrow network permissions without disrupting normal use.

## 4. When Sandbox Takes Effect

### 4.1 Trigger Conditions

Sandbox applies when all of the following are true:

1.  **Global switch is on** — `security.sandbox_enabled = true`
2.  **Platform supports sandbox** — The current OS can provide isolation
3.  **Command is not explicitly allowed or denied by policy** — The command does not match any existing ALLOW/DENY rule

When all three conditions hold, the command runs transparently inside the sandbox—**no extra user confirmation and no approval prompt**.

### 4.2 Relationship with Governance Policy

QwenPaw's security decisions proceed in multiple phases:

```plaintext
Command arrives
  │
  ├─ Phase 0: Tool type check (internal tools pass; unknown tools rejected)
  ├─ Phase 1: Deep security scan (dangerous patterns; CRITICAL level rejected outright)
  ├─ Phase 1.5: Dangerous command keyword detection (sudo rm -rf /, fork bomb, etc. → reject)
  ├─ Phase 2: Rule matching (builtin_rules + user_rules; first match wins)
  │     ├─ ALLOW match → execute directly (no sandbox)
  │     ├─ DENY match → reject
  │     └─ ASK match → show approval card
  └─ Phase 3: No rule match (Fallback)
        └─ Shell command → SANDBOX_FALLBACK → execute in sandbox

```

**Key point**: Sandbox handles the **gray area**—commands that are neither explicitly allowed nor explicitly forbidden. Commands already explicitly allowed by rules do not enter the sandbox.

### 4.3 Behavior When Sandbox Is Unavailable

When the sandbox is unavailable (unsupported platform or global switch off):

- Commands that would have entered the sandbox instead **show an approval prompt (ASK)**; the user manually decides whether to allow execution
- Phase 0–2 protections (secret file detection, dangerous command blocking) are unaffected

---

## 5. How to Enable Sandbox

### 5.1 Via Configuration File

Set in `config.json`:

```json
{
  "security": {
    "sandbox_enabled": true
  }
}
```

### 5.2 Via Console UI

On the QwenPaw Console Security settings page, toggle the Sandbox switch.

### 5.3 Confirm Sandbox Status

Startup logs show platform detection results:

```plaintext
ResourceGovernor: sandbox capability: bubblewrap available with user namespaces

```

Or when unavailable:

```plaintext
ResourceGovernor: sandbox not available — bwrap not found on PATH.
SANDBOX_FALLBACK will escalate to ASK.

```

---

## 6. Supported Platforms and Isolation Methods

Sandbox automatically detects the current OS and selects the strongest available isolation method:

| OS          | Isolation Method                | Requirements                                | Characteristics                                                                          |
| ----------- | ------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Linux**   | Bubblewrap (preferred)          | Install `bwrap` + user namespaces supported | Sensitive directories are completely invisible (not permission denied—they do not exist) |
| **Linux**   | Landlock (fallback)             | Linux kernel 5.13+                          | Kernel-level filesystem rules; no extra install                                          |
| **macOS**   | Seatbelt                        | Built-in `sandbox-exec`                     | Kernel policy language; zero config                                                      |
| **Windows** | AppContainer / Restricted Token | Windows 10+; administrator privileges       | Native Windows security mechanisms                                                       |

Users do not choose manually; the system automatically uses the best option available on the current platform.

### Platform Installation Guide

**Linux (recommended: install Bubblewrap)**:

```bash
# Debian/Ubuntu
sudo apt install bubblewrap

# Fedora/RHEL
sudo dnf install bubblewrap

# Arch
sudo pacman -S bubblewrap

```

**macOS**: No installation needed; `sandbox-exec` is built in.

**Windows**: Run QwenPaw as administrator.

---

## 7. Sandbox Violation Handling

### 7.1 What Is a Violation

When a command inside the sandbox tries to access a forbidden path or perform a blocked operation, a **Sandbox Violation** occurs.

For example, when a command tries to read `~/.ssh/id_rsa`:

- Under Bubblewrap: path does not exist (`No such file or directory`)
- Under other backends: permission denied (`Permission denied`)

### 7.2 What the User Sees

When a violation is detected, QwenPaw shows an approval card:

```plaintext
⚠️ Sandbox Violation — Approve Unsandboxed Execution?

Sandbox violation: Permission denied: /home/user/.ssh/id_rsa

If you approve, this command will be re-executed without sandbox isolation (with full host access).
Kernel-level filesystem restrictions will no longer apply.

[Approve] [Deny]

```

- **Approve**: The command is re-executed without sandbox restrictions
- **Deny**: The command is blocked; the Agent receives failure feedback

### 7.3 Design Rationale

Sandbox violation handling embodies **"restrict first, escalate later"**:

1.  Execute in the sandbox by default to prevent accidental leakage
2.  If the command truly needs more permissions, escalate via user approval
3.  The user decides with full context

---

## 8. Execution Levels and Sandbox

QwenPaw's governance system has four execution levels:

| Level               | Behavior                                              | Sandbox Role                                |
| ------------------- | ----------------------------------------------------- | ------------------------------------------- |
| **OFF**             | Tool guard fully disabled; all calls execute directly | Not used                                    |
| **AUTO**            | Only flagged calls require approval                   | Unmatched commands enter sandbox            |
| **SMART** (default) | Low risk auto-allowed; high risk requires approval    | Unmatched commands enter sandbox            |
| **STRICT**          | All tool calls require manual approval                | Not applicable (all commands need approval) |

In `AUTO` and `SMART` modes, Sandbox acts as a **safety net**—letting the Agent run everyday commands efficiently while ensuring sensitive areas are not touched.

---

## 9. Sandbox Permission Compilation Logic

Sandbox permissions are not fixed; they are **dynamically compiled** from your project policy rules:

1.  **Workspace directory** — Always read-write (where the Agent works)
2.  **Coding project directory** — Always read-write (if different from workspace)
3.  **Paths referenced in rules**:

    - File read tool rules (Read/ViewImage, etc.) → path mounted read-only
    - File write tool rules (Write/Edit/Append) → path mounted read-write

4.  **Sensitive paths** — Always blocked regardless of other rules (see Section 3.3)
5.  **Environment variables** — Keys on the deny list are cleared

This means: if you add a rule allowing the Agent to read `/data/datasets/`, commands inside the sandbox automatically get read-only access to that directory as well.

---

## 10. Windows Platform Notes

### 10.1 Implementation Challenges

Process isolation on Windows is a known hard problem in the Code Agent space. Mainstream frameworks (such as Codex and Claude Code) still have incomplete Windows sandbox support. The core challenge: Windows primarily isolates files by modifying file/directory ACLs (Access Control Lists), and ACL changes have two properties:

1.  **Persistence** — ACL changes are written to NTFS metadata and survive reboots; they must be explicitly reverted
2.  **High time cost** — Setting inheritable ACEs on large directories requires recursive propagation to all child objects (e.g. a Python conda environment can take 60+ seconds)

### 10.2 Two Implementation Modes

To reduce ACL modifications, we provide two implementations, chosen automatically based on `allow_read_all`:

**1. AppContainer mode** (`allow_read_all=False`)

For strict isolation. Uses Windows native AppContainer; ACLs are set per allowed path. AppContainer processes cannot access user files by default, so ACLs are only needed for **paths to allow**—a smaller set.

**2. Write Restricted Token mode** (`allow_read_all=True`, default)

For everyday development. Uses the `CreateRestrictedToken` API to create a token with the `WRITE_RESTRICTED` flag. With this token, directory access is writable but not readable by default, reducing the number of ACL changes required.

### 10.3 Creation Flow and Reuse

On Linux/macOS, sandbox creation is very cheap (< 50ms) and can be created fresh on each Shell invocation. On Windows, first-time creation is heavier:

1.  Create an AppContainer Profile or local user account
2.  Set ACLs on workspace and mount paths (duration depends on directory size)
3.  Configure Windows Firewall rules (when network is restricted)

Windows therefore provides a **configuration fingerprint reuse** mechanism: the system computes a SHA256 fingerprint from `workspace_dir`, `mounts`, `deny_paths`, `network_allow`, and related parameters, and generates a deterministic sandbox name (`qwenpaw_<fingerprint>`). Subsequent calls with the same configuration reuse the existing Profile and ACLs, skipping creation—runtime cost comparable to Linux/macOS. Recreation is needed only when configuration changes (e.g. workspace switch, mount path change).

### 10.4 Cleanup

**Automatic cleanup (normal exit)**:

When the QwenPaw process exits, a cleanup function registered via `atexit` automatically:

1.  Reverts all filesystem ACLs that were set
2.  Removes Windows Firewall block rules
3.  Deletes local user accounts (Restricted Token mode)
4.  Removes user Profile directories
5.  Deletes metadata JSON files on disk

The cleanup function is idempotent and safe to call multiple times. It also skips sandbox instances owned by other still-running QwenPaw processes.

**When automatic cleanup does not run**:

`atexit` cleanup does not run in these cases:

- Process killed with `SIGKILL` (`taskkill /F`)
- Exit via `os._exit()`
- Terminal closed directly

**Recovery after failed cleanup**:

When automatic cleanup fails, leftover sandbox artifacts (ACLs, user accounts, firewall rules) remain on the system. They are cleaned up when QwenPaw is started again and exits normally. You can also clean up manually:

```bash
python scripts/cleanup_windows_sandbox.py

```

This script scans all metadata files under `~/.qwenpaw/`, identifies orphan sandboxes (owner process no longer exists), and runs the full cleanup flow.

---

## 11. FAQ

### Q: Commands feel slower after enabling Sandbox?

First sandbox creation may take a few seconds (especially on Windows when setting ACLs). Subsequent runs add very little overhead (Linux/macOS < 50ms).

### Q: "Permission denied" but I'm sure the path is safe?

The path is not on the sandbox accessible list. Options:

1.  Add a policy rule explicitly allowing access to that path (the command will bypass the sandbox and run directly)
2.  Choose "Approve" on a sandbox violation to run unsandboxed for that invocation

### Q: How secure is it with Sandbox off?

Sandbox is one layer in the security stack. With it off, you still have:

- Phase 0–2 protections (secret file detection, dangerous command blocking, rule matching)
- Commands that would have entered the sandbox instead show an approval prompt for your manual decision

### Q: My Linux system has neither Bubblewrap nor Landlock—what then?

If neither is available, the sandbox degrades to `NONE` mode. Commands that would have entered the sandbox then show an approval prompt (they are not executed unconditionally). Installing `bubblewrap` is recommended for the best isolation experience.

### Q: Can commands in the sandbox access the network?

The current version allows full network access by default because common operations like `pip install`, `git clone`, and `npm install` need connectivity. Finer network control is planned for future versions.

### Q: Can Sandbox stop the Agent from running `rm -rf /`?

Extremely dangerous commands like this are rejected in Phase 1.5 (dangerous command keyword detection), **before Sandbox is involved**. Sandbox protects commands that look normal but might touch sensitive data.

---

## 12. Feature Summary

| Feature                                     | Status       | Notes                                                                              |
| ------------------------------------------- | ------------ | ---------------------------------------------------------------------------------- |
| Filesystem read/write isolation             | ✅ Supported | Whitelist mode; only authorized paths accessible                                   |
| Automatic sensitive path blocking           | ✅ Supported | 20+ common credential paths blocked by default                                     |
| Environment variable scrubbing              | ✅ Supported | API keys and similar values cleared automatically                                  |
| Command timeout force-kill                  | ✅ Supported | Default 60s; process killed on timeout                                             |
| Violation detection and approval escalation | ✅ Supported | Clear user confirmation on violations                                              |
| Cross-platform auto-adaptation              | ✅ Supported | Linux/macOS/Windows auto-select best isolation                                     |
| REPL code forced sandboxing                 | ✅ Supported | Model-generated code must run in sandbox                                           |
| Policy rule integration                     | ✅ Supported | Sandbox permissions compiled dynamically from governance rules                     |
| Configuration fingerprint reuse             | ✅ Supported | Same config skips rebuild (Windows)                                                |
| Global on/off switch                        | ✅ Supported | Toggle anytime; fail-safe design                                                   |
| Fine-grained network control                | 🚧 Partial   | Linux Landlock v4 supports port-level control; other platforms all-on/all-off only |
| Process count / memory limits               | 🚧 Limited   | Native support on Windows Job Object only                                          |
| Domain-level network filtering              | 📋 Planned   | Requires proxy layer support                                                       |
