# Post-Match Analysis Template

When the user asks about a **finished match**.

⚠️ Match results/stats from web search. Do not fabricate scores.

## ⚠️ MANDATORY FOOTER — Append Before Sending

1. Read `worldcup2026/user_favorites.json`. If it does not exist, create it from `references/tpl_user_favorites.json`.
2. For each flag below that is `false` (or missing), append the line under a `---` separator at the bottom. Each line on its own line, blank line between items, no bullet points:

| Flag is `false` | Append this line |
|-----------------|------------------|
| `features_activated.predictions` | `🎯 **Predictions:** Reply with a scoreline (e.g., "Mexico 2-1") to start your prediction streak!` |
| `features_activated.digest` | `📰 **Daily Digest:** Reply with your favorite teams and players to get a personalized digest every morning.` |
| `features_activated.video` | `🎬 **AI Video:** Reply "make a video of [Player/Team]" to generate a cinematic clip.` |

3. When a feature is successfully used, update `worldcup2026/user_favorites.json` to set that flag to `true` immediately.
4. Missing file or missing key = show the footer line for that feature.

## Steps

1.  **Score Prediction:** Read `worldcup2026/predictions.json` (`worldcup2026/` under workspace root). If the user predicted this match, calculate points and update the file *before* responding.
2.  **Output:** Present the match summary.

## Pre-Response Checklist

Verify these items before generating output:

- [ ] Read `worldcup2026/predictions.json` (`worldcup2026/` under workspace root) and score any user prediction first
- [ ] Include `xG` in the Match Stats table
- [ ] Include ⭐ **Player of the Match** section with reasoning
- [ ] Include 🔄 **Turning Point** as a dedicated section if there exists a turning point
- [ ] Include 🏆 **What It Means** as a dedicated section (group standings/bracket impact)
- [ ] Header must include: Group, Match #, Day, Date, Stadium, City
- [ ] Use ✅ emoji for FULL TIME header (not 🏁 or other)
- [ ] Do NOT add extra sections beyond the template (no cards, no assists, no narrative report unless explicitly requested)
- [ ] Stick to the exact template structure below

## Output Format

```markdown
# ✅ FULL TIME — [Team A] [X] - [X] [Team B]

> [Group] • Match #[N] • [Day], [Date] | 📍 [Stadium], [City]

---

## ⚽ Goals

| Minute | Player | Team |
|---|---|---|
| [X]' | [Scorer] | [Team] |

## 📊 Match Stats

| Stat | [Team A] | [Team B] |
|---|---|---|
| Possession | [X]% | [Y]% |
| xG | [X] | [Y] |

## ⭐ Player of the Match

> **[Player Name]** ([Team])
> [Reasoning]

---

## 🔄 Turning Point

[Moment the game shifted]

## 🏆 What It Means

[Group standings/Bracket impact]
```

## Prediction Score (If Applicable)

If a prediction was made, show the result:

```markdown
🎯 **Your prediction scored!**
| Match | Your Pick | Actual | Result | Points |
|---|---|---|---|---|
| [A] vs [B] | [Pick] | [Actual] | [Result] | **[Pts]** |
```

## Post-Match Prediction CTA

After the match summary (and any prediction score), include a closing prompt to keep the user engaged with the prediction system. Choose the variant below based on context:

### Variant A: Prediction was scored (user has a prediction record)

Read `worldcup2026/predictions.json` (`worldcup2026/` under workspace root) for the user's current record. Show:

```markdown
---

🎯 Your record so far: **🏆 [W]W–[L]L · [N] predictions · [P] points**
Want to predict the next match? Just reply with a scoreline — I'll score it after the final whistle.
```

### Variant B: No prediction was made for this match

```markdown
---

🎯 You didn't predict this one — no worries! Want to lock in a scoreline for the next match? Just reply with your pick and I'll score it after kickoff.
```

### Variant C: Brand new user (0 predictions total, first time seeing the system)

Use a slightly more explanatory tone:

```markdown
---

🎯 **I'm tracking World Cup score predictions if you want to play along!**
Just reply with a scoreline for any upcoming match (e.g. `Brazil 2-1` or `2-2` for a draw) — I'll score it right after the final whistle.
```

### Rules
- Pick the variant that matches the user's current state. Check `worldcup2026/predictions.json` (`worldcup2026/` under workspace root) for total predictions count.
- Append this after the post-match summary.
- Keep it brief. One or two lines max.
