# Third-party Harness Skills/MCP Implementation Checklist

## Branch

- [x] Create `feat/third-party-agent-skills-mcp` from
  `feat/codex-third-party-agent`.
- [x] Record the approved direct-projection architecture.

## Common capability layer

- [x] Add provider-neutral runtime capability models.
- [x] Resolve channel-effective QwenPaw Skills.
- [x] Resolve enabled QwenPaw MCP DriverCards and credentials in memory.
- [x] Filter resolvable DriverPolicy scope before projection.
- [x] Keep secrets out of fingerprints, persistence, API responses, and logs.
- [x] Add extensible Harness capability declarations.
- [x] Add a provider-neutral read-only Skill discovery DTO and adapter API.

## Codex

- [x] Inject Skill roots through `skills/extraRoots/set`.
- [x] Isolate app-server clients by capability fingerprint.
- [x] Inject QwenPaw MCP through Codex runtime configuration.
- [x] Discover Codex-owned MCP with `codex mcp list --json`.
- [x] Mark discovered MCP as read-only and Codex-only.
- [x] Bridge Codex filesystem/network permission requests to QwenPaw
  approvals.
- [x] Discover Codex-owned Skills through app-server `skills/list`.

## Qoder

- [x] Materialize cross-platform local Plugin Skill snapshots.
- [x] Inject Plugin and Skill allowlist through Qoder SDK.
- [x] Inject QwenPaw MCP through `QoderAgentOptions.mcp_servers`.
- [x] Enable strict MCP configuration where supported.
- [x] Declare Provider MCP discovery unsupported until a stable API exists.
- [x] Discover Qoder Skills through `get_server_info().skills`.
- [x] Enable Qoder user/project/local/plugin Skills in QwenPaw sessions.

## UI

- [x] Show inherited QwenPaw Skills/MCP status for third-party Agents.
- [x] Group MCP by source and scope.
- [x] Show editable versus read-only state.
- [x] Show policy compatibility/degradation.
- [x] Add all locale keys and dark-mode styling.
- [x] Expose projected Skills/MCP panels in the third-party Agent sidebar.
- [x] Keep native workspace panels hidden when third-party capability data is
  missing or stale.
- [x] Filter nested sidebar group children using Harness capabilities.
- [x] Group Skills into QwenPaw-managed editable and Provider-owned read-only
  sections.
- [x] Hide all mutation and batch controls from Provider-owned Skills.
- [x] Add a read-only detail drawer for Provider-owned Skills.
- [x] Keep full Provider Skill names available through hover and details.
- [x] Compact the empty state and cap the responsive Provider Skill grid.
- [x] Keep the Skills page vertically scrollable across viewport sizes.
- [x] Use third-party Agent terminology in user-facing Skills/MCP copy instead
  of the model-oriented Provider term.

## Verification

- [x] Add common resolver unit tests.
- [x] Add Codex projection/discovery unit tests.
- [x] Add Qoder Skill/MCP projection unit tests.
- [x] Add portable path/copy cases for macOS, Linux, and Windows semantics.
- [x] Add secret-redaction tests.
- [x] Run targeted backend tests.
- [x] Run targeted frontend tests.
- [x] Run pre-commit only for changed files.
