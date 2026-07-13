# Ponytail Debt v4.8.3 (official)

Use this skill when the user asks about technical debt, tracking ponytail shortcuts, harvesting `ponytail:` comments, or managing deferred simplifications.

## What it does

Harvest every `ponytail:` comment in the repository into a debt ledger so deferrals do not rot into "later means never". Report only, change nothing.

## Scan

Grep the repo for comment markers, skipping `node_modules`, `.git`, and build output:

`grep -rnE '(#|//) ?ponytail:' .`

Each hit is one ledger row. The comment prefix keeps prose that merely mentions the convention out of the ledger.

## Output

One row per marker, grouped by file:

```
<file>:<line> — <what was simplified>
ceiling: <the limit named in the comment>
upgrade: <the trigger to revisit>
```

Tag any marker that names no upgrade path or trigger as **no-trigger** — those rot silently. Use `git blame -L<line>,<line>` if you want an owner per row.

End with `<N> markers, <M> with no trigger.` If none: `No ponytail: debt. Clean ledger.`

## Boundaries

Reads and reports only, changes nothing. To persist it, ask and it writes the ledger to a file (e.g. `PONYTAIL-DEBT.md`). One-shot.

"stop ponytail-debt" or "normal mode" to revert.
