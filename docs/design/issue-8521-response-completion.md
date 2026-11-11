# Issue 8521: response completion integrity

## Scope and acceptance criteria

Implement the two confirmed response-handling defects discussed with the user.
Clipboard behavior and general UI performance are outside this change.

- [x] Reject an empty or whitespace-only final answer with an explicit error.
- [x] Preserve existing thinking-only continuation, cancellation, tool calls,
  and valid multimodal answers.
- [x] Retain the raw OpenAI/DashScope finish reason through streaming and
  non-streaming parsing, agent events, persistence, and Console SSE.
- [x] Keep partial output and show an incomplete-answer notice for `length`.
- [x] Verify controlled HTTP responses, wrapper cleanup/concurrency, runtime
  metadata, frontend rendering, and relevant regression suites.

## Minimal implementation

Use the existing provider compatibility classes, without editing AgentScope
or widening the dependency pin. A small shared compatibility mixin captures
raw completion reasons in request-local state and reattaches them after the
upstream accumulator. It does not rewrite cancellation or retry a response.

At the agent boundary, carry completion metadata onto model-end events and
the final persisted assistant message. Reject a terminal answer without
visible text or usable output only after existing stop handlers have run.
The existing error path reports the failure; no new automatic retry policy
is introduced. Pure thinking retains the existing bounded ReAct loop.

The runtime retains completion metadata separately from execution status.
A `length` response may finish execution normally while the Console shows
that its answer is incomplete. Never discard already generated content.
Cancellation and explicit transport failures keep their existing outcomes.

## Verification

Use the `QwenPaw` conda environment. Cover empty EOF, whitespace mixed with
thinking, ordinary text, thinking followed by text, output-cap truncation,
tool calls, data output, cancellation, transport errors, concurrent calls,
and persisted/reloaded warning metadata. Run the related Python and Console
tests plus formatting and static checks for the touched files.

## Verified results

- Added 35 backend regression cases against controlled OpenAI/DashScope HTTP
  responses and native AgentScope execution; all pass.
- Broader agents/providers/runtime regression: 5,592 passed, 9 skipped,
  2 deselected. The memory test directory and decision-compaction test module
  were excluded because this conda environment lacks existing ReMe modules
  (tag_index, compaction, and as_decision_model). The two deselected provider
  tests require the same unavailable ReMe integration. No dependency or
  unrelated implementation was changed to work around those failures.
- Console typecheck and 64 focused tests pass. Prettier and ESLint pass for
  the new helper; the touched Python files pass pre-commit including mypy,
  Black, flake8, and pylint.
- Google Chrome renders three controlled scenarios correctly: live
  truncation preserves partial text and shows a warning; the warning survives
  history loading; an empty final answer shows the existing error card.
  These browser fixtures were generated through the repaired provider and
  agent pipeline, without calling an external model. No page errors occurred.
- The browser fixture's temporary chat-title change was restored.

The change retains execution status and records answer completeness as
metadata. It covers the confirmed Chat Completions adapters; it does not
change clipboard shortcuts, general UI navigation, or the AgentScope pin.
