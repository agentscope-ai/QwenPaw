---
name: opensandbox
description: Use the official OpenSandbox MCP client for isolated Linux sandbox execution only; it is not for Windows host command execution, PowerShell/CMD/bat/ps1 tasks, or Windows OS/PATH/process checks. Use when the user mentions sandbox/沙箱, sandbox business scenarios/沙箱业务场景, dangerous commands/危险命令, untrusted scripts/不可信代码, Linux environment checks/Linux 环境, dependency installation/环境依赖, cleanup/delete/migration/log-cleaning scripts, disposable command validation, or temporary web/API previews that should not touch host files or secrets.
---

# OpenSandbox MCP Usage Rules

Use this skill only when the `opensandbox` MCP client is enabled for the current
agent. The client runs the official `opensandbox_mcp.create_server()` through
the plugin launcher so QwenPaw can set `use_server_proxy` when needed. It
exposes sandbox lifecycle, command execution, endpoint, metrics, and text file
tools.

## Trigger First

Prefer this skill before local shell when the request contains or implies any
of these signals:

- Sandbox or isolation wording: sandbox, 沙箱, isolated execution, 隔离执行,
  remote sandbox, safe environment, do not run locally, sandbox business
  scenario, or 沙箱业务场景.
- Risky command wording: dangerous command, 危险命令, destructive command,
  cleanup, delete, remove, migration, log cleaner, recursive rewrite, archive
  extraction, unknown shell script, or command copied from the internet.
- Untrusted code wording: untrusted script, 不可信代码, generated script,
  vendor/community script, postinstall script, or first run of unfamiliar code.
- Linux/runtime wording: Linux environment, Linux 环境, `/etc/os-release`,
  shell compatibility, package availability, dependency install, 环境依赖,
  `pip install`, `npm install`, build tool, CLI validation, or Windows host
  needing Linux behavior.
- Disposable service wording: temporary web app, API preview, docs server,
  notebook, visualization, or any preview that should not expose a host service.

If both local shell and OpenSandbox could work, choose OpenSandbox when risk,
untrusted input, Linux-only behavior, dependency installation, or disposable
validation is part of the task. If the `opensandbox` MCP client is not enabled,
tell the user it must be enabled before this skill can execute sandbox work.

## Tool Map

Sandbox lifecycle:

- `sandbox_create`: create a sandbox and return a `sandbox_id`.
- `sandbox_connect`: attach to an existing sandbox by `sandbox_id`.
- `sandbox_get_info`: inspect sandbox metadata and state.
- `sandbox_list`: list available sandboxes.
- `sandbox_renew`: extend sandbox lifetime.
- `sandbox_healthcheck`: check sandbox health.
- `sandbox_get_metrics`: inspect resource metrics.
- `sandbox_get_endpoint`: get a URL for a port exposed inside the sandbox.
- `sandbox_kill`: terminate a sandbox.

Command tools:

- `command_run`: run a command inside a sandbox.
- `command_interrupt`: stop a running command.

Filesystem tools:

- `file_write`: write text into a sandbox path.
- `file_read`: read text from a sandbox path.
- `file_search`: search sandbox files by glob.
- `file_replace_contents`: replace text content in a sandbox file.
- `file_move`: move or rename files/directories.
- `file_delete`: delete files.
- `file_create_directories`: create directories.
- `file_delete_directories`: delete directories.

All OpenSandbox MCP tools operate on a `sandbox_id` returned by
`sandbox_create` or `sandbox_connect`. `file_read` and `file_write` are
text-oriented; for large files, use the tool schema's range or encoding options
when available, and avoid moving large binary data through text tools.

Do not confuse the workload image with `execd_image`. `execd_image`, for
example `opensandbox/execd:v1.0.16`, belongs in the `opensandbox-server`
`.sandbox.toml` `[runtime]` section. It is not an MCP client env var and is not
the same as `sandbox_create.image`.

## Image Allowlist

Use only the known available workload image:

```text
opensandbox/code-interpreter:v1.0.2
```

When creating a sandbox, pass this exact image to `sandbox_create.image`. Other
images are not supported. Do not invent, infer, or try alternative images such
as `python:3.12`, `python:3.11`, `ubuntu`, `debian`, `node`, `busybox`,
`alpine`, or a package-specific image.

If the user requests another image, or if `sandbox_create` returns an image
allowlist error, reply exactly:

```text
not support image, pls use "opensandbox/code-interpreter:v1.0.2" instead.
```

If a task appears to need a different runtime, still start from
`opensandbox/code-interpreter:v1.0.2` and inspect what is available inside the
sandbox. If the required runtime or package is missing, report that limitation
instead of creating a new sandbox with an unverified image.

## Default Workflow

1. Create or connect to a sandbox.
   - If the user gave a `sandbox_id`, use `sandbox_connect` or
     `sandbox_get_info`.
   - Otherwise call `sandbox_create` and keep the returned `sandbox_id`.
   - Always use this default workload profile:

```text
image: opensandbox/code-interpreter:v1.0.2
entrypoint: ["/opt/opensandbox/code-interpreter.sh"]
env: {"PYTHON_VERSION": "3.11"}
resource: {"cpu": "500m", "memory": "512Mi"}
timeout_seconds: 600
ready_timeout_seconds: 120
```

2. Prepare files inside the sandbox.
   - Use `file_create_directories` for paths such as `/workspace`.
   - Use `file_write` for text scripts, configs, fixtures, or small source
     files that the command needs.
3. Run the command with `command_run`.
   - Use Linux paths such as `/workspace/script.py`.
   - Do not put Windows host paths inside sandbox commands.
4. For services, call `sandbox_get_endpoint` for the exposed port and return the
   URL to the user.
5. For follow-up commands in the same task, reuse the same `sandbox_id`.
6. When the task is finished, call `sandbox_kill` unless the user asked to keep
   the sandbox alive. If the work is long-running, renew the sandbox before it
   expires.

## Good Uses

Prefer OpenSandbox for:

- First run of untrusted or unfamiliar scripts, including scripts generated by
  an agent or copied from a vendor/community source.
- Scripts that perform file cleanup, log rotation, bulk deletion, archive
  extraction, recursive rewrite, migration, or dependency installation.
- Linux behavior checks from a Windows host, such as shell syntax, package
  availability, filesystem layout, or `/etc/os-release`.
- Disposable Python dependency experiments: `pip install`, build tools, or
  package-manager diagnostics inside the existing code-interpreter image. For
  `npm`, `node`, or other runtimes, first check whether the runtime already
  exists in the sandbox; do not switch images just to try them.
- Running tests against small copied fixtures when the host project should not
  be touched.
- Starting a temporary web app, API server, docs server, or visualization when
  the required runtime exists in `opensandbox/code-interpreter:v1.0.2`, then
  returning a preview endpoint.
- Generating throwaway data, reports, or archives inside an isolated runtime.
- Inspecting how a command behaves without granting it host credentials,
  browser sessions, SSH keys, or direct project access.

## Avoid By Default

Do not default to OpenSandbox when the task requires:

- Direct access to the host project tree, host build cache, local virtualenv, or
  Windows path such as `D:\projects\...`.
- Editing repository files in place. Use local file tools for host edits.
- Local credentials, SSH keys, cloud tokens, browser cookies, GUI sessions, USB
  devices, or host-only services.
- A large binary dataset, a whole repository upload, `node_modules`, `.venv`,
  `.git`, caches, build artifacts, or private `.env` files.
- Verifying the host OS, host PATH, host processes, or local tool installation.
- Returning artifacts directly into the host filesystem. The official MCP file
  tools operate inside the sandbox; host export requires a separate supported
  transfer path or user-assisted retrieval.

If the user asks to run a command against host files, decide whether the needed
inputs are small text files. If yes, read only the required local text files
through allowed local file access, then recreate them in `/workspace` with
`file_write`. If the inputs are large, binary, secret-bearing, or directory
heavy, explain that the current official MCP integration does not provide a
QwenPaw host upload bridge and ask for a smaller input set or another approved
transfer method.

## File Rules

- Treat the sandbox filesystem and host filesystem as separate.
- Keep sandbox work under `/workspace` unless the user requests another sandbox
  path.
- Write code and fixtures into sandbox paths before running commands.
- Use sandbox paths in command strings, for example
  `python3 /workspace/log_cleaner.py /workspace/test.log`.
- Never pass a Windows path as `cwd` or as a command argument expecting sandbox
  access.
- Keep copied content minimal: prefer one script and a few fixtures over a
  directory.
- Do not copy secrets, `.env*`, private keys, tokens, credentials, browser
  profiles, VCS metadata, dependency caches, or large generated logs into the
  sandbox unless the user explicitly approves and the security policy allows it.
- For large text files, prefer range reads/writes where the tool schema
  supports them. For large binary files or directories, ask for user assistance
  or wait for a dedicated host upload/download feature.

## Command Rules

- Use POSIX/Linux shell commands by default.
- Use explicit working directories, for example `cd /workspace && python3 app.py`.
- Keep commands focused and inspectable. Avoid combining unrelated risky actions
  into one long shell string.
- For package installation or remote downloads, make the command and destination
  clear in the response.
- For long-running services, start the service with `command_run`, then request
  an endpoint with `sandbox_get_endpoint`.
- If a command is still running unexpectedly, use `command_interrupt` before
  killing the whole sandbox.

## Connectivity Failures

If sandbox creation reaches `Running` but health checks, `command_run`, or
`file_*` fail with direct endpoint/network errors, treat it as a client
connectivity problem rather than an OS or shell problem.

In particular, if the error mentions direct sandbox endpoint access or suggests
`ConnectionConfig(..., use_server_proxy=True)`, stop retrying normal command
execution and tell the user to enable server proxy mode for the OpenSandbox
client. This is common when QwenPaw runs on Windows while `opensandbox-server`
and sandbox workloads run in WSL2 + k3s or Kubernetes.

Do not keep creating additional sandboxes with `skip_health_check=True` unless
the user explicitly asks to debug server provisioning. If a failed attempt left
a sandbox running, call `sandbox_kill` and report the `sandbox_id` that was
cleaned up.

## Example: Run A Log Cleaner Safely

When the user wants to test a log-cleaning script without touching host logs:

1. `sandbox_create`.
2. `file_create_directories` for `/workspace/logs`.
3. `file_write` `/workspace/log_cleaner.py` with the script text.
4. `file_write` representative log fixtures such as
   `/workspace/logs/syslog` and `/workspace/logs/auth.log`.
5. `command_run`:

```bash
cd /workspace && python3 log_cleaner.py logs
```

6. Use `file_read` or `file_search` to inspect expected outputs.
7. Report the sandbox id, command, exit code, stdout/stderr, and changed
   sandbox files. Kill the sandbox unless the user wants to inspect it later.

## Response Requirements

After using OpenSandbox, tell the user:

- The work ran in OpenSandbox, not on the host.
- The `sandbox_id`.
- The command or operation performed.
- Exit code and important stdout/stderr for command runs.
- Any endpoint URL, sandbox path, or artifact path produced.
- Whether the sandbox was killed or intentionally kept alive.
- Any limitation that affected the result, especially text-only file transfer
  or lack of automatic host directory sync.

## Safety Notes

OpenSandbox reduces host risk but does not make every action safe. Be careful
with remote install scripts, credential exposure, fork bombs, cryptocurrency
miners, data exfiltration, destructive shell commands, and commands that create
unexpected network services. Use the normal QwenPaw approval and guardrail
behavior before invoking MCP tools.
