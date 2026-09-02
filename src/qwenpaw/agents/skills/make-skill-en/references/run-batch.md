# Build a stored batch

Read this reference only after choosing `batch: true`. Encode the approved reusable region in `scripts/<name>.batch.json`. Prefer one stored entrypoint; split it only when an intervening user or agent decision genuinely separates independent phases. A good Batch is a small, self-contained program whose inputs, actions, output, and failure meaning are clear to an agent seeing it for the first time.

## Compile the reusable region

Before writing JSON, state four things: caller inputs, actions and branches known in advance, artifacts produced, and the condition that means success. Keep genuinely open-ended user or agent judgment outside that boundary. Runtime data and observations may stay inside when the rule for acting on them is already known.

- Keep shared tool state in one complete tool-native action. Do not replay every snapshot, click, or intermediate call from the original conversation.
- Use a focused helper only for substantial deterministic parsing, transformation, sorting, deduplication, or assertion.
- Pass small values through step results. Pass large text or binary data through explicit artifact files.
- End with a compact result or assertion that distinguishes success from a partial run.
- Prefer the direct implementation. Add retries or compatibility paths only when the workflow actually requires them.

## Batch file

Use a non-empty `actions` array. Each action names a registered tool and supplies its arguments. The `.batch.json` suffix lets make-skill recognize and validate the file.

```json
{
  "actions": [
    {
      "tool_name": "read_file",
      "arguments": {"file_path": "${args.source_file}"}
    },
    {
      "tool_name": "write_file",
      "arguments": {
        "file_path": "${args.output_file}",
        "content": "${steps.0.text}"
      }
    }
  ]
}
```

Ground tool names, arguments, and result fields in real tool contracts or observed successful calls. Inspect the tool descriptions or a recent result when uncertain; omit unknown details instead of inventing them.

## Data and control flow

Keep free-form executable fields such as a shell `command`, code body, or script source static; they must contain no `${args.*}`, `${steps.*}`, or `${vars.*}` binding. Prefer every other dynamic value as the complete value of a documented data parameter. If its surrounding text will be parsed as structure by another parser, insert it only when the tool explicitly performs the required encoding. A request/config file must be written structurally by a tool or receive dynamic values as complete data; hand-built serialized text is still templating. If no compact data boundary exists, leave parameter preparation or that phase agent-led.

- `${args.name}` supplies runtime inputs. Every referenced argument must be present in the invocation.
- `${steps.N.path}` reads a field from an earlier zero-based action. In a loop it resolves to that action's latest result.
- `set_var` creates or updates scalar `${vars.name}` values with `arguments.expr`, such as `i=0` or `i=${vars.i}+1`.
- `label` defines a jump target; `goto` jumps to it unconditionally or when `arguments.condition` is true. Use these for bounded branches, loops, or retries.
- Actions run sequentially; batch is not parallel execution. Keep at most 50 static actions and never call `run_tool_batch` from inside a batch.

## Failure and generated Skill contract

A failed Batch is ordinary actionable feedback. Preserve and report the failing action and tool error. The calling agent may inspect current state, correct the inputs or Skill, and rerun when appropriate. Never convert failure into apparent success or maintain a second step-by-step fallback that silently bypasses the Batch.

Promise only behavior that the Batch and its helpers actually enforce. If a failed run would leave final artifacts that contradict the stated contract, move the relevant checks before the final write or narrow the promise. Keep a fallback only for a known environment difference, describe its degraded behavior accurately, and do not call unequal checks equivalent.

The generated `SKILL.md` should state what the batch handles, what remains agent-led, its task inputs, its outputs, and the success or failure contract. Put one complete invocation before narrative steps so the stored file is the primary entrypoint:

```text
run_tool_batch(
  file_path="<absolute-skill-dir>/scripts/<name>.batch.json",
  args={"source_file": "...", "output_file": "..."},
  stop_on_error=true
)
```

Use an absolute `file_path` and invoke the stored file; do not reconstruct its actions inline. Keep `args` limited to values the real Batch needs, and include every referenced `${args.*}` value in the invocation. Use `last_only=true` only when the final action preserves the useful result. Testing is a separate plan choice: `batch: true` does not require `smoke` or `eval`.
