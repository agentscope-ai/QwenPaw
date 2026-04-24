# Playbooks

## wrapper-regression

Use when the base model seems strong but the wrapped agent behaves much worse.

Focus on wrapper layering, duplicated context injection, hidden formatting or
fallback layers, and answer degradation after orchestration.

## memory-contamination

Use when old topics or stale artifacts bleed into current turns.

Focus on same-session artifact reentry, stale session reuse, weak memory
admission criteria, and aggressive distillation cadence.

## tool-discipline

Use when the agent should have used a tool but did not, or when tool evidence
was available but the conclusion drifted.

Focus on code-enforced versus prompt-enforced tool requirements, preflight
probes, tool-call skip paths, and stale evidence reuse.

## rendering-transport

Use when the answer seems correct internally but broken in delivery.

Focus on transport payload shape assumptions, deterministic fallback behavior,
and platform-layer mutations.

## hidden-agent-layers

Use when repair, retry, summarize, or recap loops are hidden in the stack.

Focus on hidden repair agents, recap loops, maintenance-worker synthesis paths,
and transport repair prompts.
