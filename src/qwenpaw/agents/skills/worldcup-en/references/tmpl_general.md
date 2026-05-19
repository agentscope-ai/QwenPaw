# General Query Workflow

When the user asks about World Cup topics **without referencing a specific match**.

## ⚠️ MANDATORY FOOTER — Append Before Sending

1. Read `worldcup2026/user_favorites.json`. If it does not exist, create it from `references/tpl_user_favorites.json`.
2. For each flag below that is `false` (or missing), append the line under a `---` separator at the bottom of your response. Each line on its own line, blank line between items, no bullet points:

| Flag is `false` | Append this line |
|-----------------|------------------|
| `features_activated.predictions` | `🎯 **Predictions:** Reply with a scoreline (e.g., "Mexico 2-1") to start your prediction streak!` |
| `features_activated.digest` | `📰 **Daily Digest:** Reply with your favorite teams and players to get a personalized digest every morning.` |
| `features_activated.video` | `🎬 **AI Video:** Reply "make a video of [Player/Team]" to generate a cinematic clip.` |

3. When a feature is successfully used, update `worldcup2026/user_favorites.json` to set that flag to `true` immediately so it stops appearing.
4. Missing file or missing key = show the footer line for that feature.

## Guidelines

1.  **Answer directly.** Give the requested info clearly. Do **NOT** use match templates (no H2H, no venue cards, no prediction CTA).
2.  **Cite sources.** For injuries or breaking news, note the source.
3.  **⚠️ Web search required.** All data — schedule, venue, injuries, form, squad news — MUST come from web search, never from training data or memory.
4.  **Contextual follow-up.** If relevant, mention an upcoming match and offer a breakdown.
    *   *Example:* "Morocco's next match is vs Brazil on June 12. Want a full pre-match breakdown?"
## Query Types

*   **Injuries/Squad:** Name, injury type, recovery status, source.
*   **Group Info:** Teams, match dates, venues.
*   **Venue:** Stadium, city, capacity, altitude, timezone.
*   **Historical Stats:** Records, past results.
*   **Bracket/Standings:** Current standings, knockout path.
