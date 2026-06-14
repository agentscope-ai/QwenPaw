---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-operator-cli
element_kind: OperatorCli
element_path: src/qwenpaw/cli
---

## Implementation Architecture Contract

### Responsibility
- Own the click-based local operator command surface exposed through the qwenpaw entrypoint.
- Keep command discovery rooted in main.py with lazy subcommand loading for bounded startup cost.
- Delegate business behavior to runtime helpers instead of embedding backend orchestration inside the CLI shell.

### Out Of Scope
- Owning HTTP router behavior under src/qwenpaw/app.
- Owning frontend operator UX under console/.

### Stable Files
- path: main.py
  role: root click group and lazy command registration surface
- path: agents_cmd.py
  role: multi-agent operator command family
- path: task_cmd.py
  role: headless task execution command family
- path: doctor_cmd.py
  role: operator-facing doctor command that renders read-only diagnostics and delegates repairs to doctor_fix_runner.py
- path: doctor_checks.py
  role: reusable read-only doctor check semantics that Coding/Repair may project into backend Health Check results without parsing CLI text
- path: doctor_connectivity.py
  role: opt-in --deep channel connectivity notes and local LLM deep diagnostics

### Explicit Testcase Entrypoints
- tests/unit/cli/test_cli_version.py::test_cli_version_option_outputs_current_version
- tests/unit/cli/test_cli_agents.py::test_agents_list_uses_shared_tool_helper
- tests/unit/cli/test_cli_task.py::test_task_command_registered_in_cli

### Notes
- The current repository state keeps command modules mostly flat under this directory, while startup cost is constrained by LazyGroup-based deferred imports in main.py.
- For `ip-e2e-007-healthcheck-full-doctor-coverage`, this element owns doctor semantics consumed by `extension/health_check/projection.py` and `fix.py`. Reusable helpers live in `doctor_checks.py` and `doctor_connectivity.py`; projection must not scrape `click.echo` output from `doctor_cmd.py`.
- Deep connectivity remains opt-in. `doctor_connectivity.py` is used only when the Health Check scan API receives `deep=true` (Console UI currently calls `deep=false` only).