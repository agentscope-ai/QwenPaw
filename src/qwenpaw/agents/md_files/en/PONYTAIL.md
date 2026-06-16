---
summary: "Ponytail coding philosophy — YAGNI Ultra, minimum code, zero bloat"
read_when:
  - Writing, editing, or reviewing code
  - Designing architecture or abstractions
  - Adding dependencies or tools
  - Evaluating whether new code is needed at all
---

## Ponytail Decision Ladder (every code task)

Before writing *any line of code*, step through this ladder top-to-bottom:

```
❓ Is this really needed? ── No → Stop. YAGNI wins.
   │
   ✅ Yes → Can stdlib / platform native do it? ── Yes → Use stdlib.
   │
   ✅ No → Existing installed dependency? ── Yes → Use it.
   │
   ✅ No → Can one line solve it? ── Yes → One line.
   │
   ✅ No → Only now write: minimum viable, zero abstraction that isn't demanded
```

### Levels

| Level | Behaviour |
|-------|-----------|
| `ultra` (default) | YAGNI extremist: no abstraction unless required, no new dependencies |
| `full` | YAGNI but lightweight abstractions allowed if clearly justified |
| `lite` | Hints only: YAGNI reminders, no hard rules |
| `off` | Disabled completely |

### Ponytail Ultra Rules

1. **YAGNI extremist** — If it's not needed yet, don't write it. Unsure? Don't write it.
2. **Stdlib & native platform first** — Python stdlib, OS API, platform built-ins. Check stdlib before `pip install`.
3. **One line before fifty lines** — `list.sort(key=...)` instead of 15-line custom sort.
4. **No abstraction unless required** — No class, interface, factory, or pattern until ≥3 usages exist.
5. **`// ponytail:` comment for every shortcut** — Every intentional decision to write less / skip validation / use a hack must carry a `// ponytail:` comment with **ceiling** (the shortcut's limit) and **upgrade path** (when and how to fix it).
6. **Never cut corners on security / validation / data-loss** — Ponytail means *less code*, not *unsafe code*.

### Comment Convention

```python
# ponytail: ceiling=100 records, upgrade=replace with db query pagination
results = session.query(User).limit(100).all()
```

- `ceiling`: when this shortcut breaks
- `upgrade`: replacement code when ceiling is exceeded
- Missing `// ponytail:` = violation, needs review

### Code Review Checklist (`ponytail-review`)

- [ ] Any abstraction not justified? (1 usage → no class)
- [ ] Could stdlib do this?
- [ ] Could one line suffice? (listcomp, walrus, built-in functions)
- [ ] Does every shortcut have a `// ponytail:` comment?
- [ ] Are security / validation / data-loss corners being cut?
- [ ] Is the new dependency truly necessary?
