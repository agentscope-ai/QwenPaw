# Live Score Template

When the user asks for a **live score** or "update me".

⚠️ Live scores MUST come from web search — never from training data or memory.

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

## Output Format

```markdown
# ⚽ LIVE — [Team A] [X] - [X] [Team B]

> [Group] • [Match #] • [minute]' | 📍 [Stadium]

---

## ⚽ Goal Timeline

| Minute | Event | Player |
|---|---|---|
| [X]' | ⚽ | [Scorer] ([Team]) |
| [X]' | 🟨 | [Player] ([Team]) |

## 📊 Match Stats

| Stat | [Team A] | [Team B] |
|---|---|---|
| Possession | [X]% | [Y]% |
| Shots | [X] | [Y] |
| On target | [X] | [Y] |

---

*Want me to check again? Just ask.*
```

