# OMP Role Tool Configuration

When using spawn_subagent (single or batch mode) to dispatch sub-agents,
set the corresponding allowed_tools and skills parameters based on the
sub-agent's role.

**Canonical source of truth in code:**
`plugins/bundle/omp_workflows/shared/constants.py`
(`ROLE_ALLOWED_TOOLS`, `ROLE_SKILLS`, `TOOL_*` names) and
`shared/role_prompts.py` (`ROLE_PROMPTS`, `build_worker_prompt`,
`format_spawn_call`). Tool strings must match registered ToolRegistry
names — do not invent aliases.

## Role Definitions

### executor (Code Executor)
- **allowed_tools**: null (inherits all tools)
- **skills**: null (inherits all skills)
- **Boundary**: Implement features, run quality checks. Follow existing patterns.

### architect (System Architect)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "write_file", "ast_search", "execute_shell_command"]
- **skills**: []
- **Boundary**: Design interfaces and module boundaries, diagnose complex issues. No implementation code.

### analyst (Requirements Analyst)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "write_file", "execute_shell_command"]
- **skills**: []
- **Boundary**: Extract requirements, identify constraints, define acceptance criteria. No code.

### critic (Plan/Design Critic)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "ast_search"]
- **skills**: []
- **Boundary**: Review plans and designs, challenge assumptions. No plans, no code.

### security-reviewer (Security Reviewer)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "execute_shell_command", "ast_search"]
- **skills**: []
- **Boundary**: Identify vulnerabilities, injection vectors, auth weaknesses. No file modifications.

### code-reviewer (Code Reviewer)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "execute_shell_command", "ast_search"]
- **skills**: []
- **Boundary**: Review code quality, maintainability, convention adherence. No file modifications.

### qa-tester (QA Tester)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "execute_shell_command"]
- **skills**: []
- **Boundary**: Interactive CLI/service testing — start services and verify behavior.

### planner (Strategic Planner)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "write_file", "ast_search"]
- **skills**: []
- **Boundary**: Create implementation plans, define task breakdown and dependencies. No implementation code.

### explore (Code Explorer)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "ast_search"]
- **skills**: []
- **Boundary**: Read-only exploration. Map codebase structure and dependencies.

### debugger (Debugging Expert)
- **allowed_tools**: null (inherits all tools)
- **skills**: []
- **Boundary**: Root cause analysis, fix build/test failures. No new features.

### verifier (Adversarial Verifier)
- **allowed_tools**: ["read_file", "grep_search", "glob_search",
  "execute_shell_command", "ast_search"]
- **skills**: []
- **Boundary**: Verification only — no file modifications. Physical isolation via read-only tool set.

## Usage

```text
spawn_subagent(
    task="<role identity from ROLE_PROMPTS>\n\n## Task\n<task description>",
    allowed_tools=<ROLE_ALLOWED_TOOLS[role] or omit if null>,
    skills=<ROLE_SKILLS[role] or omit if null>,
    fork=True,         # if worktree isolation needed
    background=True,   # if background execution needed
)
```

When allowed_tools or skills is null, omit the parameter (uses default None).
For batch mode, pass `task=""` and put per-item role config in each batch dict.
