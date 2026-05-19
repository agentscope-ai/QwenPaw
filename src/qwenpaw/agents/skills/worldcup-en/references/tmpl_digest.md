# Daily Digest Workflow

Generates a personalized World Cup news digest tailored to the user's favorite teams and players.

⚠️ All news and match updates MUST come from web search — never from training data.

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

## File Setup

If `worldcup2026/user_favorites.json` does not exist, create it using `references/tpl_user_favorites.json` as the blueprint. Write it to `worldcup2026/` under workspace root.

## Activation

- **Scheduled:** Triggered daily via the environment's scheduling tool.
- **Manual:** User says "daily digest", "world cup digest", "today's world cup news", "catch me up".

## Data Gathering (Do ALL steps)

1. **Read user preferences** from `worldcup2026/user_favorites.json` (`worldcup2026/` under workspace root)
   - Favorite teams (list)
   - Favorite players (list)
   - If no preferences stored (empty arrays) → run generic digest (top matches, trending news)

2. **Search for today's matches** (web search):
   - `FIFA World Cup 2026 matches today`
   - Check if any favorite teams play today

3. **Search team-specific news** for each favorite team:
   - `"[Team] World Cup 2026 news today"`
   - Focus on: lineup changes, injuries, quotes, training updates

4. **Search player-specific news** for each favorite player:
   - `"[Player] World Cup 2026 news today"`
   - Focus on: performance, goals, assists, injuries, transfers

5. **Search trending World Cup topics:**
   - `World Cup 2026 top stories today`
   - Get 2-3 major headlines beyond favorites

## Output Format

```
⚽ World Cup Daily Digest — {DATE}

📅 Today's Matches
- {Team A} vs {Team B} — {time} {user_tz} @ {stadium}
- (or "No matches today")

🔴 Favorite Teams
### {Team Name} 🇽🇽
- {headline 1}
- {headline 2}
- {upcoming match if relevant}

### {Team Name} 🇾🇾
- ...

⭐ Favorite Players
### {Player Name} ({Team})
- {headline/update}

### {Player Name} ({Team})
- ...

🌍 Trending
- {top story 1}
- {top story 2}
- {top story 3}

---
Sources: {list sources}
```

## Rules

- **Keep it concise.** Max ~300 words total. Bullet points only.
- **If a favorite has no news today**, say "No new updates" — don't skip the section.
- **Always include today's match schedule** even if no favorites play.
- **Use flag emojis** next to team names.
- **Cite sources** at the bottom.
- **If no favorites configured**, fall back to: today's matches + top 3 World Cup stories.

## Scheduling Integration

To schedule daily digests, use the `cron` skill (`references/cron/SKILL.md`). Create a recurring job that triggers the digest query each morning in the user's timezone.
