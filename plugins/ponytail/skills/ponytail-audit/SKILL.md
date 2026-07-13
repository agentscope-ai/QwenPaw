# Ponytail Audit v4.8.3 (official)

Use this skill when the user asks to audit the whole repo for over-engineering, simplify the codebase, find dead code, or do a Ponytail compliance sweep. One-shot — scan the whole tree, rank findings biggest cut first.

## Tags

Same as ponytail-review:

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` hand-rolled thing the standard library ships. Name the function.
- `native:` dependency or code doing what the platform already does. Name the feature.
- `yagni:` abstraction with one implementation, config nobody sets, layer with one caller.
- `shrink:` same logic, fewer lines. Show the shorter form.

## Hunt for

- Deps the stdlib or platform already ships
- Single-implementation interfaces
- Factories with one product
- Wrappers that only delegate
- Files exporting one thing
- Dead flags and config
- Hand-rolled stdlib

## Output

One line per finding, ranked: `<tag> <what to cut>. <replacement>. [path]`

End with `net: -<N> lines, -<M> deps possible.` Nothing to cut: `Lean already. Ship.`

## Boundaries

Scope: over-engineering and complexity only. Correctness bugs, security holes, and performance are out of scope. Route them to a normal review pass. Lists findings, applies nothing. One-shot.

"stop ponytail-audit" or "normal mode" to revert.
