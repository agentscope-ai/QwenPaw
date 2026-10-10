# Build a stored batch

Encode the approved reusable region in `scripts/<name>.batch.json`. Prefer one stored entrypoint; split it only when an intervening user or agent decision genuinely separates independent phases. A good Batch is a small, self-contained program whose inputs, actions, output, and failure meaning are clear to an agent seeing it for the first time.

## Compile the reusable region

Before writing JSON, state four things: caller inputs, actions and branches known in advance, artifacts produced, and the condition that means success. Keep genuinely open-ended user or agent judgment outside that boundary. Runtime data and observations may stay inside when the rule for acting on them is already known.

- Keep shared tool state in one complete tool-native action. Do not replay every snapshot, click, or intermediate call from the original conversation.
- Use a focused helper only for substantial deterministic parsing, transformation, sorting, deduplication, or assertion.
- Pass small values through step results. Pass large text or binary data through explicit artifact files.
- End with a compact result or assertion that distinguishes success from a partial run.
- Prefer the direct implementation. Add retries or compatibility paths only when the workflow actually requires them.

## Batch file and tool contract

Use a non-empty `actions` array. Each action has a static `tool_name` and an `arguments` object. The tool must be available when the workflow runs; make-skill does not require it to be globally registered during validation, so plugin, MCP, and session tools remain valid. The `.batch.json` suffix lets make-skill recognize and validate the file.

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

## Placeholder expansion

Placeholders are Batch data bindings in argument values, recursively inside objects and lists. Use only the brace-delimited forms below. In a shell `command`, use `$NAME` rather than `${NAME}` for ordinary shell variables because `${...}` is reserved for Batch placeholders.

| Form | Value source | Resolution time |
|---|---|---|
| `${args.name}` | A caller value from `run_tool_batch(args=...)`; dotted paths may read nested objects | Once after loading the file, before any action runs |
| `${steps.N.path}` | A field from an earlier zero-based action; loops use that action's latest result | Immediately before the consuming action |
| `${vars.name}` | Scalar Batch state created earlier by `set_var` | Immediately before the consuming action |

The execution model is:

```text
actions = resolve_args(load(file_path), args or {})  # missing reference: stop
for action in actions:
    arguments = resolve_steps_and_vars(action.arguments)
    run control action or Toolkit.call_tool(action.tool_name, arguments)
```

Every referenced `${args.*}` path is required. If the file contains no `${args.*}`, the caller may omit `args`. To use a target tool's optional parameter or default, omit that field; to give the Batch a fixed default, write the literal value instead of a placeholder.

A placeholder that is the complete string value preserves the resolved JSON type. A placeholder embedded in a larger string becomes text; non-string values are JSON-encoded. This permits placeholders in a shell `command`, code body, or script source, but Batch performs no quoting or escaping. Write the surrounding syntax so the expanded value has the intended meaning.

The expanded action still follows the target tool's normal invocation path, including its existing policy checks, approval flow, and sandbox boundary.

## Control flow and limits

- `set_var` creates or updates scalar `${vars.name}` values with `arguments.expr`, such as `i=0` or `i=${vars.i}+1`.
- `label` defines a jump target; `goto` jumps to it unconditionally or when `arguments.condition` is true. Use these for bounded branches, loops, or retries.
- Actions run sequentially; Batch is not parallel execution. Keep at most 50 static actions and never call `run_tool_batch` from inside a Batch.

## Failure and generated Skill contract

A failed Batch is ordinary actionable feedback. Preserve and report the failing action and tool error. The calling agent may inspect current state, correct the inputs or Skill, and rerun when appropriate. Never convert failure into apparent success or maintain a second step-by-step fallback that silently bypasses the Batch.

Promise only behavior that the Batch and its helpers actually enforce. If a failed run would leave final artifacts that contradict the stated contract, move the relevant checks before the final write or narrow the promise. Keep a fallback only for a known environment difference, describe its degraded behavior accurately, and do not call unequal checks equivalent.

The generated `SKILL.md` should state what the Batch handles, what remains agent-led, its task inputs, outputs, and success or failure contract. Put one complete invocation before narrative steps so the stored file is the primary entrypoint:

```text
run_tool_batch(
  file_path="<absolute-skill-dir>/scripts/<name>.batch.json",
  args={"source_file": "...", "output_file": "..."},
  stop_on_error=true
)
```

Use an absolute `file_path` and invoke the stored file; do not reconstruct its actions inline. Keep `args` limited to values the real Batch needs. Use `last_only=true` only when the final action preserves the useful result. Testing is a separate plan choice: `batch: true` does not require `smoke` or `eval`.
