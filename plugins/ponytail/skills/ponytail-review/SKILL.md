# Ponytail Review v4.8.3 (official)

Use this skill when the user asks to review code, a diff, or a PR for over-engineering, or when the agent produces code that needs checking against Ponytail rules. Call `ponytail_review` proactively — before coding — to catch violations early.

## When to invoke

1. **Before coding** — call `ponytail_lint_prompt` with your plan/sketch.
2. **After coding** — call `ponytail_review` on each new/modified file.
3. **During PR review** — call `ponytail_review` on every changed file.
4. **When you see a violation** — reference the specific rule and suggest the Ponytail-compliant alternative.

## Format (official v4.8.3)

One line per finding: `L<line>: <tag> <what>. <replacement>.`
or `<file>:L<line>: ...` for multi-file diffs.

Tags:

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` hand-rolled thing the standard library ships. Name the function.
- `native:` dependency or code doing what the platform already does. Name the feature.
- `yagni:` abstraction with one implementation, config nobody sets, layer with one caller.
- `shrink:` same logic, fewer lines. Show the shorter form.

### Examples

❌ "This EmailValidator class might be more complex than necessary, have you considered whether all these validation rules are needed at this stage?"

✅ `L12-38: stdlib: 27-line validator class. "@" in email, 1 line, real validation is the confirmation mail.`

✅ `L4: native: moment.js imported for one format call. Intl.DateTimeFormat, 0 deps.`

✅ `repo.py:L88: yagni: AbstractRepository with one implementation. Inline it until a second one exists.`

✅ `L52-71: delete: retry wrapper around an idempotent local call. Nothing replaces it.`

✅ `L30-44: shrink: manual loop builds dict. dict(zip(keys, values)), 1 line.`

## What the tool checks

| Check | Rule | Severity | What it looks for |
|-------|------|----------|-------------------|
| Line count | YAGNI | Warning >500 lines, Info >200 | Bloated files |
| Imports | Stdlib First | Warning | `pandas` when `csv` works, `requests` when `urllib` works |
| Single-method class | No Abstraction | Warning | `class Foo:` with 1 public method → make it a function |
| Empty function/class | Dead Code | Info/Warning | `def x(): pass` — remove if unused |
| Nesting depth | Complexity | Warning >5, Error >8 | Deeply nested if/for/try blocks |
| Wrapper function | YAGNI | Info | Function that just calls another function |
| Comment ratio | Comments | Info | >40% comments? Delete noise. |
| Missing `ponytail:` | Ponytail Comment | Warning | Hack/FIXME without documented ceiling |

## Scoring

End with the only metric that matters: `net: -<N> lines possible.`

If there is nothing to cut, say `Lean already. Ship.` and stop.

## Boundaries

Scope: over-engineering and complexity only. Correctness bugs, security holes, and performance are explicitly out of scope. Route them to a normal review pass, not this one. A single smoke test or `assert`-based self-check is the ponytail minimum, not bloat — never flag it for deletion.

"stop ponytail-review" or "normal mode": revert to verbose review style.
