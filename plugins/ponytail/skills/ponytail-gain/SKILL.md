# Ponytail Gain v4.8.3 (official)

Use this skill when the user asks about ponytail's measured impact: "what does ponytail save", "show ponytail impact", "ponytail scoreboard", "ponytail gain". One-shot display — does NOT change mode, write flag files, or persist anything.

## Scoreboard

Render plain ASCII bars showing the measured impact across 5 benchmark tasks (email validator, debounce, CSV sum, countdown timer, rate limiter) and 3 models (Haiku, Sonnet, Opus):

```
  ponytail gain                     benchmark median · 5 tasks · 3 models

  Lines of code   no-skill  ████████████████████  100%
                  ponytail  ██▌·················    6–20%   ▼ 80–94%
  Cost            no-skill  ████████████████████  100%
                  ponytail  █████▌··············   23–53%  ▼ 47–77%
  Speed           ponytail  ▸ 3–6× faster

  This repo:  /ponytail-debt  (shortcuts you deferred)
              /ponytail-audit (what's still cuttable)
```

## Honesty boundary

These are benchmark medians, not this repo. NEVER print per-repo savings ("you saved X lines here"): the unbuilt version was never written, so there is no real baseline to subtract from. The only real per-repo figures come from `/ponytail-debt` (counted ledger), which this card points to instead.

## Boundaries

One-shot display. Edits nothing, changes no mode.

"stop ponytail" or "normal mode": revert.
