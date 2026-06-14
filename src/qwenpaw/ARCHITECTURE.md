---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-runtime-root
element_kind: RuntimeRoot
element_path: src/qwenpaw
---

## Implementation Architecture Contract

### Responsibility
- Own the Python runtime root for QwenPaw.
- Contain the stable backend slices that realize routing, agents, channels, config, security, providers, and shared utilities.
- Expose stable sub-elements rather than forcing callers to reason from individual files.
- Keep the `src/qwenpaw/security` child contract as the owner of the `sec-e2e-024` audit-foundation acceptance boundary while transport/orchestration remains in `app/`.
- Keep the `src/qwenpaw/security` child contract as the owner of the `sec-e2e-024`, `sec-e2e-025`, `sec-e2e-027`, and `sec-e2e-021` audit-foundation acceptance boundaries while transport/orchestration remains in `app/`.

### Out Of Scope
- Owning the browser console bundle under console/.
- Owning the documentation website under website/.
- Owning test entrypoints outside repository-facing verification contracts.

### Children
- path: cli
  kind: OperatorCli
  role: local operator command surface mounted by the qwenpaw console script
- path: app
  kind: RuntimeApp
  role: API routers, runtime orchestration, channels, approvals, and app lifecycle glue
- path: agents
  kind: AgentRuntime
  role: agent runtime behavior, skill system integration, and coding-mode logic
- path: config
  kind: ConfigurationModel
  role: configuration schemas, loaders, persistence helpers, and working-dir bound config logic
- path: security
  kind: SecurityAuditFoundation
  role: stable security boundary for high-risk tool guard enforcement, trusted context provenance, local audit-chain semantics, and Security Center projection/query seams

### Dependency Direction
- app may orchestrate agents, config, providers, security, and channels, but those lower slices should not depend on console/ or website/ implementation details.
- app captures request, session, and channel metadata, but `security/` owns the stable acceptance semantics for trusted provenance, durable confirmation evidence, and evidence-chain reconstruction.
- cli remains a child stable element and should consume runtime services through explicit surfaces instead of re-owning backend state.

### Explicit Testcase Entrypoints
- tests/unit/routers/test_settings.py::test_put_then_get_roundtrip
- tests/unit/routers/test_git.py::test_git_helper_uses_shared_command_runner
- tests/integration/security/test_audit_foundation.py::test_end_to_end_non_repudiation_evidence_chain
- tests/integration/security/test_audit_foundation.py::test_audit_integrity_self_healing_lockdown
- tests/integration/security/test_audit_foundation.py::test_lease_expiry_blocks_untrusted_rejoin_until_gap_sync
- tests/integration/security/test_audit_foundation.py::test_prompt_injection_cannot_bypass_high_risk_tool_guard

### Supporting Non-Explicit Tests
- tests/unit/cli/test_cli_agents.py
- tests/unit/cli/test_cli_task.py---
contract_type: implementation-architecture-element
contract_version: 1
scope: stable-element
element_name: qwenpaw-runtime
element_kind: ProductRuntime
element_path: src/qwenpaw
---

## Implementation Architecture Contract

### Responsibility
- Own the Python runtime for QwenPaw, including API routers, agent orchestration, channel runtime, configuration, providers, security, and packaged CLI entrypoints.
- Expose the stable operator CLI from `cli/` and stable backend HTTP router composition from `app/routers/`.

### Out Of Scope
- Owning the browser console implementation.
- Owning the external documentation website.
- Owning validator schema scripts.

### Children
- path: app
  kind: backend-http-runtime
  role: FastAPI application runtime, routers, and runtime orchestration
- path: cli
  kind: operator-cli-surface
  role: Click-based operator command surface bundled with the Python package
- path: agents
  kind: agent-runtime
  role: agent behaviors, skill system, model routing, and execution mixins
- path: config
  kind: runtime-configuration
  role: typed config models and config loading utilities
- path: security
  kind: security-runtime
  role: tool guard, file guard, and security support services

### Explicit Testcase Entrypoints
- testcase_name: cli-version-surface
  entry_path: ../../tests/unit/cli/test_cli_version.py::test_cli_version_option_outputs_current_version
  control_point: invoke the root Click CLI with `--version`
  observation_point: command exits successfully and prints the packaged version string
- testcase_name: cli-task-command-surface
  entry_path: ../../tests/unit/cli/test_cli_task.py::test_task_command_registered_in_cli
  control_point: invoke the root Click CLI with `task --help`
  observation_point: the registered task flags remain visible on the CLI help surface
- testcase_name: backend-settings-language-roundtrip
  entry_path: ../../tests/unit/routers/test_settings.py::test_put_then_get_roundtrip
  control_point: perform PUT then GET on `/api/settings/language` through the mounted FastAPI router
  observation_point: the GET response returns the language value persisted by the preceding PUT request
- testcase_name: backend-git-helper-shared-runner
  entry_path: ../../tests/unit/routers/test_git.py::test_git_helper_uses_shared_command_runner
  control_point: call the router helper `_git(...)` with a patched shared command runner
  observation_point: the helper delegates the expected git command and execution kwargs to the shared runner

### Notes
- The CLI and backend runtime are kept in one stable element because both surfaces ship from the Python package and share config, orchestration, and runtime support modules.
- Current evidence for `sec-e2e-024`, `sec-e2e-025`, `sec-e2e-027`, and `sec-e2e-021` is intentionally split across `app/agent_context.py`, `app/approvals/service.py`, `app/inbox_trace_store.py`, `agents/tools/delegate_external_agent.py`, `security/tool_guard/`, and deployment bootstrap assets under `deploy/`; Coding/Repair must converge those seams behind `src/qwenpaw/security/ARCHITECTURE.md` and `deploy/ARCHITECTURE.md` without moving the explicit entrypoints.

## Integrity Protection Delivery Addendum

### Responsibility
- Keep `security/` as the owning child element for Integrity Protection backend settings projection and extension bridges.
- Keep `app/` responsible for HTTP/SSE routing and lifecycle integration only; it must not redefine persona baseline, health check, or rule-integrity business rules.
- Keep `cli/` as the owner of existing `qwenpaw doctor` and `qwenpaw doctor fix` behavior consumed by the health-check orchestrator.
- Health Check structured doctor coverage projection is implemented in `extension/health_check/projection.py` and re-exported through `security/integrity_protection.py`; it reuses `cli/doctor_checks.py` and `cli/doctor_connectivity.py` without parsing CLI stdout.

### Dependency Direction
- `app/routers` may expose Integrity Protection APIs backed by `security/` services.
- `security/` may call or wrap stable CLI/doctor service functions where needed, but scan and fix phases must remain separate.
- Runtime code must not import from `console` or from `tests/integration/security`.

### Explicit Testcase Entrypoints
- tests/integration/security/test_integrity_protection.py::test_integrity_security_menu_default_off
- tests/integration/security/test_integrity_protection.py::test_persona_drift_alert_restore_accept
- tests/integration/security/test_integrity_protection.py::test_health_check_scan_and_confirmed_fix
- extension/rule_integrity/tests/test_integration_entry.py::test_rule_integrity_entry_visible
- tests/integration/security/test_integrity_protection.py::test_security_i18n_and_healthcheck_progress_carousel
- tests/integration/security/test_integrity_protection.py::test_healthcheck_full_doctor_coverage_projection
