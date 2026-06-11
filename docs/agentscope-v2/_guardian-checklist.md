# Guardian Checklist — rules the `agentscope-guardian` enforces

This is the hard-rule layer the [`agentscope-guardian`](../../.claude/skills/agentscope-guardian/SKILL.md)
applies to every proposed change to **qwenpaw** (`src/qwenpaw/**`) or any code that
uses **AgentScope**. Read it together with the specific KB file for the area touched.

---

## 0. Version — ALWAYS VERIFY FIRST (overrides naive doc-matching)

> **User note (2026-06-10):** the user reported **updating the API to v2 (agentscope 2.x)**.
> Do NOT take this on faith and do NOT assume the version. **Verify before every change:**
> ```
> .venv/Scripts/python.exe -c "import agentscope; print(agentscope.__version__)"
> ```
> Also check the pin: `grep agentscope pyproject.toml`.
>
> **Status (updated 2026-06-10):** the venv was upgraded to **`agentscope 2.0.1`** and
> `pyproject.toml` now pins `agentscope==2.0.1` (`agentscope-runtime` stays `1.1.6`, which allows
> `>=1.0.14`). **Re-verify anyway** — don't trust this line blindly.
>
> - Installed is now **2.x** → this KB (`docs/agentscope-v2/`) is the **direct** reference; use it as-is.
> - **But the qwenpaw code still contains 1.x usages that break on 2.0** and need migration. Known
>   breakages at upgrade time: `agentscope.agent.ReActAgent` (removed — 2.0 unifies on `Agent`),
>   `agentscope.token` (module gone), `agentscope.agent._react_agent` (private API gone). Affected:
>   `agents/react_agent.py`, `agents/model_factory.py`, `agents/context/agent_context.py`, `app/_app.py`.
>   When you touch those, migrate to the 2.0 API per this KB — do not reintroduce 1.x symbols.

- **Resolution order when checking an AgentScope symbol:**
  1. How is it used **today** in `src/qwenpaw/`? (`grep -rn "<symbol>" src/qwenpaw/`) — match the established pattern.
  2. What does the **installed** library actually expose?
     `.venv/Scripts/python.exe -c "import agentscope, inspect; ..."` to confirm the real signature.
  3. What does this **KB** (v2 docs) say it *should* be?
  - If 1/2 and 3 disagree, **flag the divergence** and prefer what is installed/used,
    unless the change is explicitly a v2 migration.

## 1. API existence & signature

- ❌ REJECT any class/function/argument that does not exist in (a) installed lib or
  (b) this KB. Never invent or "remember" an API — verify.
- ❌ REJECT wrong argument names, types, or order vs. the confirmed signature.
- ✅ Required constructor/config args must be present (e.g. an `Agent` needs at least
  `name`, `system_prompt`, `model`; a chat model needs a `credential` + `model`).

## 2. No deprecated / legacy patterns

From `faq-and-changelog.md` (1.0 → 2.0 breaks) — flag if introduced:

- Legacy 0.x/1.x message construction where the unified `Msg` / typed content blocks
  (`TextBlock`, `ToolCallBlock`, `ToolResultBlock`, `DataBlock`, `ThinkingBlock`,
  `HintBlock`) are the v2 way.
- Old multi-class agent hierarchies where v2 uses the single **`Agent`** class with
  `reply` / `reply_stream`.
- Direct/global model construction where v2 splits **Credential** + **ChatModel**.
- Streaming consumed as raw text where v2 emits **`AgentEvent`s** accumulated via
  `Msg.append_event` (start/delta/end per block).
- `ToolUseBlock` (legacy) vs. v2 `ToolCallBlock`.

## 3. Area-specific must-checks

- **Agent / context** (`agent.md`, `context.md`): context compression is configured via
  `ContextConfig` (`trigger_ratio`, `reserve_ratio`, `tool_result_limit`, compression
  prompt/template/schema); offloading via the `Offloader` protocol. Don't hand-roll
  truncation that bypasses these.
- **Model** (`model.md`): pick the right `*ChatModel` for the provider; pass
  `parameters` (temperature/max_tokens/parallel_tool_calls/thinking_*) correctly;
  structured output goes through `generate_structured_output` / `structured_model`.
- **Tool** (`tool.md`): new tools subclass `ToolBase` (or wrap via `FunctionTool`),
  registered through `Toolkit`; set `is_read_only`, `is_concurrency_safe`,
  `is_external_tool`, `is_state_injected` honestly — the permission system and
  scheduler rely on them. MCP via `MCPClient` + `Stdio/HttpMCPConfig`.
- **Permission** (`permission-system.md`): rules are `PermissionRule`
  (`tool_name`, `rule_content`, `behavior`, `source`); modes ALLOW/DENY/ASK/PASSTHROUGH.
  Don't bypass `check_permissions` for tools that touch the host/filesystem.
- **Message/Event** (`message-and-event.md`): one assistant turn = exactly one `Msg`
  rebuilt from its event stream; respect the start→delta→end ordering and
  `ToolResultEndEvent.state` (SUCCESS/ERROR/INTERRUPTED/DENIED/RUNNING).
- **Middleware** (`middleware.md`): subclass `MiddlewareBase`, override only the needed
  hook(s), pass via `Agent(middlewares=[...])`. Keep the onion order in mind.
- **REST** (`api-reference/*`): every documented endpoint currently requires the
  `x-user-id` header (temporary auth) and the right `agent_id`/`session_id` params.
  Match request/response models exactly; SSE endpoints stream `AgentEvent`s.

## 4. Consistency & safety

- Prefer the pattern already used elsewhere in `src/qwenpaw/` for the same concept.
- Don't widen tool permissions or dangerous-path access without explicit reason.
- Don't introduce a second way to do something the codebase already does one way.
- Secrets/credentials never hardcoded (credentials flow through the credential layer
  / env, e.g. `DASHSCOPE_API_KEY`).

## 5. Verdict rules

- Any item in §1–§3 violated → **REJECT** with the corrected API + minimal example.
- Divergence found in §0 → APPROVE only with an explicit note on which API line the
  change targets; otherwise REJECT and ask.
- Clean → **APPROVE**, then run
  `python scripts/agentscope_guardian_approve.py "<file>"` and give exact "HOW" steps.
