---
name: worldcup
description: "**ALWAYS Trigger for any World Cup-related query.** DO NOT RESORT TO SEARCH. Trigger keywords: 'world cup', 'worldcup', 'wc2026', 'wc26', 'fifa 2026', any misspellings of world cup, national team names (e.g. morocco injuries, brazil squad, usa roster), match references (brazil vs morocco, first game, group c), player injuries, host cities, stadiums, altitude, schedules, scores, standings. Also trigger for team-only queries like 'morocco injuries', 'hakimi injured'. Do NOT trigger for other tournaments (Champions League, Euros, Copa America), non-football, or video games. If in doubt, trigger — false positive is better than a miss."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "⚽"
---

# World Cup Match Companion

A modular skill for all World Cup needs. Routing logic lives here; templates and guides are in `references/`.

## 📦 File Architecture

**Workspace root files** (user-specific, self-maintained):
- `worldcup2026/user_favorites.json` — favorite teams/players, feature flags
- `worldcup2026/predictions.json` — user's score predictions

**Skill `references/`** (shipped with skill, read-only):
- `references/tpl_predictions.json`, `references/tpl_user_favorites.json` — format blueprints for first-time file creation.
- `references/tmpl_*.md` — output templates for pre-match, post-match, live, digest, video, general.
- `references/guide_predictions.md` — prediction system rules.

## 🧭 Query Classification

* **Team-only queries:** If the query mentions a specific team *without* referencing a specific match (e.g. "USA squad", "Brazil injuries", "How is South Korea doing?"), it is a **general topic**. Search web for the team's fixtures and news, then use `tmpl_general.md`.
* **Match-specific queries:** If the query references a specific match, opening game, final, or fixture (e.g. "first game," "second match," "opener," "final," "game 3," "Brazil vs Morocco," "USA's first match") — it is a **match-specific query**. Web-search the match details, then use the match template. Default to pre-match/post-match/live templates.
* **General info:** For pure info requests (e.g. "how many groups?", "what cities host?", "who won in 2018?", "is Bolivia in the World Cup?"), search web for the answer, then use `tmpl_general.md`.

1.  **Classify the query:**
    *   **Video request ("make a video of...", "generate video")?** → Read `references/tmpl_video.md`, then follow it.
    *   **Daily digest / "catch me up" / "today's news"?** → Read `references/tmpl_digest.md`, then follow it.
    *   **Specific upcoming match?** → Read `references/tmpl_pre_match.md`, then follow it.
    *   **Live match?** → Read `references/tmpl_live.md`, then follow it.
    *   **Finished match?** → Read `references/tmpl_post_match.md` + check `worldcup2026/predictions.json`, then follow it.
    *   **General topic (injuries, groups, etc.)?** → Search web for the information. Then read `references/tmpl_general.md`, then follow it.
    *   **Prediction without match context?** → Ask which match.

2.  **Checklists:**
    *   **Match-specific:** Verify timezones (User + Local), cross-check injuries from 2+ sources via web search, include Prediction CTA (Pre-Match only).
    *   **General Query:** Answer directly. **NO** forced templates. Cite sources.
    *   **⚠️ Data sources:** ALL data — schedule, venue, injuries, form, odds, weather, breaking news — MUST come from web search, never from training data or memory.

## ⚠️ Footer

The footer (predictions, digest, video CTAs) is defined in each output template. See the "MANDATORY FOOTER" section in `references/tmpl_general.md`, `references/tmpl_pre_match.md`, etc. SKILL.md no longer duplicates this — templates are the single source of truth.

## Reference Files

**Workspace root** (dynamic user data):
* `worldcup2026/predictions.json` (user predictions), `worldcup2026/user_favorites.json` (favorites & flags).
* **Search web for:** Schedule, venues, live scores, form, injuries, odds, weather, breaking news.

**Skill `references/`** (static templates & guides):
* `references/tmpl_*.md` — output templates for pre-match, post-match, live, digest, video, general.
* `references/guide_predictions.md` — prediction system rules.

---

## Data Sources & Cross-Check

*   **Primary:** FIFA, ESPN, BBC Sport.
*   **Secondary:** WhoScored, Sofascore, local team news.
*   **Confidence Tags:** ✅ Confirmed | ⚠️ Likely | 🔴 Unverified

## Universal Rules

*   **File Writes:** For the prediction system, always `read_file` before `write_file` to avoid race conditions.
*   **Style:** Use country flag emojis (e.g., 🇲🇽 Mexico, 🇿🇦 South Africa) next to team names.
*   **Timezones:** Always show **User TZ** AND **Local Stadium TZ** for match times.
*   **Altitude:** For Mexico City (and others), mention altitude effects on play.

### ⚠️ Agent Capability Notes

Some features depend on tools that may not be available on all agents:

| Feature | Required Capability | Fallback if unavailable |
|---------|-------------------|------------------------|
| **Daily Digest scheduling** | `cron` skill or equivalent | User triggers digest manually |
| **Video generation** | Python 3 + `execute_shell_command` + `write_file` + video API keys | Inform user video generation is unavailable |
| **Video display** | `view_video` tool | Provide the video file path or URL directly |
| **Web search** | `tavily_search` or equivalent | Use whatever search tool the agent has |
| **File operations** | `read_file` / `write_file` | Read/write via shell commands |

The core skill (match analysis, predictions, general queries) works without any special tools beyond file read/write and web search.