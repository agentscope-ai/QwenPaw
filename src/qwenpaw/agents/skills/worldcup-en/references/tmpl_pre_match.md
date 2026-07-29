# Pre-Match Analysis Template

When the user asks about an **upcoming match**, gather the following info and present it in this format.

Schedule/venue from local files. Injuries, form, odds, weather MUST come from web search — never from training data.

## ⚠️ MANDATORY FOOTER — Append Before Sending

**⚠️ Pre-match responses already include a prediction CTA from `guide_predictions.md`. Skip the predictions footer line for pre-match responses.**

1. Read `worldcup2026/user_favorites.json`. If it does not exist, create it from `references/tpl_user_favorites.json`.
2. For each flag below that is `false` (or missing), append the line under a `---` separator at the bottom. Each line on its own line, blank line between items, no bullet points:

| Flag is `false` | Append this line |
|-----------------|------------------|
| `features_activated.predictions` | `🎯 **Predictions:** Reply with a scoreline (e.g., "Mexico 2-1") to start your prediction streak!` |
| `features_activated.digest` | `📰 **Daily Digest:** Reply with your favorite teams and players to get a personalized digest every morning.` |
| `features_activated.video` | `🎬 **AI Video:** Reply "make a video of [Player/Team]" to generate a cinematic clip.` |

3. When a feature is successfully used, update `worldcup2026/user_favorites.json` to set that flag to `true` immediately.
4. Missing file or missing key = show the footer line for that feature.

## Required Sections

1.  **Team Form:** Last 5 results table (W/D/L).
2.  **Head-to-Head:** Historical record table.
3.  **Venue:** Stadium, City, Altitude (crucial!), Capacity.
4.  **Weather:** Match-day conditions.
5.  **Injury/Suspension Watch:** Table of key absentees.
6.  **Key to Watch:** One tactical storyline.
7.  **Prediction:** Win probabilities and predicted scoreline. (2-3 sentence reasoning).
8.  **Prediction CTA:** See `guide_predictions.md` for the exact CTA box templates and rules.

## Output Format

```markdown
# 🏟️ [Team A] vs [Team B]

> [Group] • Match #[N] • [Day], [Date] at [Time] [User TZ] ([Time] Local)
> 📍 [Stadium], [City] — Altitude: [X]m • Capacity: [N]

---

## 📈 Recent Form (Last 5)

| [Team A] Fixture | Result | [Team B] Fixture | Result |
|---|---|---|---|
| vs [Opponent] | [Score] | vs [Opponent] | [Score] |
| ... | ... | ... | ... |

## ⚔️ Head-to-Head

**All-time:** [Team A] [X] wins · [Y] draws · [Team B] [Z] wins

| Date | Competition | Result |
|---|---|---|
| [Date] | [Comp] | [Score] |

---

## 🏥 Injuries & Suspensions

| Team | Player | Status |
|---|---|---|
| [Team A] | [Name] | [Out/Doubtful] |

## 🔑 Key to Watch

[One paragraph on the main tactical storyline]

---

## 📊 Prediction

| [Team A] | Draw | [Team B] |
|:---:|:---:|:---:|
| [X]% | [Y]% | [Z]% |

**Predicted score:** [X]-[Y]
[Reasoning based on form, tactics, conditions]
```

Append the Prediction CTA box from `guide_predictions.md` immediately after the prediction section.
