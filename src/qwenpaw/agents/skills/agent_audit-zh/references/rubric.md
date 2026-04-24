# Audit Rubric

Use this rubric when producing `agent_check_report.json`.

## 1. Context cleanliness

- Is the same information injected through multiple layers?
- Are model-generated summaries fed back as context?
- Is session history carrying stale facts forward?
- Are current-session artifacts re-entering the same turn?

## 2. Tool discipline

- Are tools merely available, or actually required in code?
- Can the model skip tools and still answer?
- Does the runtime bind final answers to current-turn evidence?

## 3. Failure handling

- Does a send or render failure trigger another hidden agent?
- Is there a deterministic fallback path?
- Are failures visible and attributable?

## 4. Memory admission

- Can assistant self-talk become long-term memory?
- Are user corrections weighted more than assistant assertions?
- Is there a stable-window or evidence gate before distillation?

## 5. Answer shaping

- Is the final response derived from structured evidence?
- Does formatting add noise or rewrap already-correct answers?
- Does platform rendering leak raw markdown or transform meaning unpredictably?

## 6. Hidden agent layers

- Are there hidden repair, retry, summarize, or recap agents?
- Do these layers have explicit contracts and schemas?

## Severity heuristics

- `critical`: confidently wrong operational behavior
- `high`: repeated corruption of otherwise good evidence
- `medium`: correctness often survives, but the system is fragile
- `low`: mostly maintainability or cosmetic concerns
