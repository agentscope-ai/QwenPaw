---
name: opensandbox
description: Decide when to use the OpenSandbox plugin for isolated command execution. Use it when a command should run in a Linux sandbox instead of the host, especially for untrusted scripts, dependency experiments, network command checks, or Linux runtime checks from a Windows host.
---

# OpenSandbox Usage Rules

Use this skill to decide whether a command should run in OpenSandbox when
QwenPaw has the `execute_opensandbox_command` tool enabled.

OpenSandbox provides an isolated Linux sandbox. It is useful for exploring
commands safely and running disposable experiments. The current MVP does not
automatically mount or sync the host project directory into the sandbox, so do
not default to OpenSandbox for tasks that need host project files.

## Good Uses

Prefer `execute_opensandbox_command` when the user needs to:

- Run untrusted, unfamiliar, or model-generated shell commands.
- Try dependency installs, package-manager behavior, or disposable CLI
  experiments.
- Check Linux runtime behavior from a Windows host.
- Run commands that should not touch the host file system.
- Run simple environment checks such as `echo`, `pwd`, `uname -a`,
  `cat /etc/os-release`, `python3 --version`, or tool availability checks.
- Test network-related commands while reducing impact on the host environment.
- Reproduce shell behavior in a clean environment.

## Avoid By Default

Do not default to OpenSandbox when the command must:

- Read, edit, build, or test files in the host project directory.
- Depend on Windows host paths such as `D:\projects\...`.
- Use local credentials, SSH keys, browser sessions, GUI apps, hardware
  devices, or host-only services.
- Generate artifacts that must appear directly in the host project directory.
- Preserve state across multiple commands, unless the user accepts that the
  current MVP creates a fresh sandbox for each call.
- Answer host-specific questions such as the Windows version, host `PATH`,
  local process list, or host tool installation state.

In these cases, use a local shell tool if it is available and allowed by the
safety policy. If no local shell tool is available, explain that the current
OpenSandbox MVP needs file sync or directory mounting before it can operate on
host project files.

## Decision Rules

Before choosing a shell tool, apply these rules in order:

1. If the task focuses on the host machine or host project files, do not use
   OpenSandbox unless the user explicitly asks for sandbox execution.
2. If the task is risky, untrusted, Linux-specific, or only needs a disposable
   runtime, use `execute_opensandbox_command`.
3. If the user says "use sandbox", "run in OpenSandbox", "isolated execution",
   "do not run locally", or similar, use `execute_opensandbox_command`.
4. If the local shell is disabled and OpenSandbox is the only available shell
   tool, use OpenSandbox, but warn the user when the task needs host file
   access that this MVP cannot directly access host files.

## Command Style

Start with simple Linux commands when validating the sandbox:

```bash
echo Hello from OpenSandbox && pwd
```

Then gather environment details as needed:

```bash
cat /etc/os-release
uname -a
python3 --version
```

Do not pass Windows paths as `cwd` to the sandbox. Use `/workspace` unless the
user has explicitly configured file sync or directory mounting.

## Response Requirements

After running a sandbox command, tell the user:

- The command ran in OpenSandbox.
- The sandbox id, if the tool output includes one.
- The exit code.
- The important stdout or stderr.
- Any relevant limitation of the zero-core MVP, especially that host directory
  sync is not automatic.

## Safety Notes

OpenSandbox can reduce host risk, but it does not make destructive commands or
credential-exposing commands automatically safe. Be especially careful with
commands that download and execute remote scripts, print environment variables,
or access credentials.
