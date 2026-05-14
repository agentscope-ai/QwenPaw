---
name: worldcup
description: "**ALWAYS Trigger for any World Cup-related query.** DO NOT RESORT TO SEARCH. Trigger keywords: 'world cup', 'worldcup', 'wc2026', 'wc26', 'fifa 2026', any misspellings of world cup, national team names (e.g. morocco injuries, brazil squad, usa roster), match references (brazil vs morocco, first game, group c), player injuries, host cities, stadiums, altitude, schedules, scores, standings. Also trigger for team-only queries like 'morocco injuries', 'hakimi injured'. Do NOT trigger for other tournaments (Champions League, Euros, Copa America), non-football, or video games. If in doubt, trigger — false positive is better than a miss."
metadata:
  qwenpaw:
    emoji: "⚽"
---

## ⛔ BOOTSTRAP — READ FIRST

**🚨 FAILURE MODE:** If `worldcup2026/.bootstrapped` does not exist and you answer a World Cup query anyway, you are reading from empty `group_stage: []` arrays. Every match lookup will return nothing. Your response will be **incomplete, wrong, and the user will call you out**. This has happened before. Do not repeat it.

**⛔ RULE:** If `worldcup2026/.bootstrapped` is missing, bootstrap first. Not after. Not "while answering." **First.** Any answer before bootstrap is complete is a bug.

**Bootstrap steps** (only if `worldcup2026/.bootstrapped` is missing):
1. Check for `worldcup2026/schedule.json`, `worldcup2026/stadiums.json`, `worldcup2026/user_favorites.json`, `worldcup2026/predictions.json` in `worldcup2026/` under workspace root.
2. For each missing file, copy `references/tpl_*.json` → `worldcup2026/` under workspace root (e.g. `tpl_schedule.json` → `worldcup2026/schedule.json`).
3. **IMMEDIATELY strip `_` keys.** Read each copied file, delete every top-level key starting with `_` (e.g. `"_delete_after_bootstrap"`, `"_instructions"`, `"_example"`), then write it back.
4. **Populate `worldcup2026/schedule.json` and `worldcup2026/stadiums.json` with real data via web search.**
   - **`worldcup2026/schedule.json`:** Flat array. Every match: `{"match_id", "date", "time_et", "home", "away", "group", "venue", "city"}`. Knockout: `"match"` with descriptive text. Match IDs from FIFA.com (1=opener, 104=Final, 73–104=knockout).
   - **`worldcup2026/stadiums.json`:** Dictionary keyed by FIFA venue name. Each: `{"name", "city", "country", "tz", "capacity", "altitude_m"}`.
5. **⚠️ VERIFICATION GATE** — After populating, verify with actual code. Do not eyeball it:
   - `len(worldcup2026/schedule.json["group_stage"]) == 72`
   - `sum(len(worldcup2026/schedule.json["knockout"][r]) for r in schedule.json["knockout"]) == 32`
   - `len(worldcup2026/stadiums.json) == 16`
   - **ALL PASS →** `touch worldcup2026/.bootstrapped` and proceed to the query.
   - **ANY FAIL →** return to step 4. Do NOT create `worldcup2026/.bootstrapped`. Do NOT proceed to the query.

Do not answer the user until bootstrap is complete. If you catch yourself typing an answer before verification passes, stop. Bootstrap first.

# World Cup Match Companion

A modular skill for all World Cup needs. Routing logic lives here; templates and guides are in `references/`.

## 📦 File Architecture

**Workspace root files** (user-specific, self-maintained):
- `worldcup2026/schedule.json` — match fixtures (auto-populated, flat array of 104 matches)
- `worldcup2026/stadiums.json` — venue data (dictionary keyed by FIFA name)
- `worldcup2026/user_favorites.json` — favorite teams/players, feature flags
- `worldcup2026/predictions.json` — user's score predictions

**Skill `references/` templates** (shipped with skill, read-only):
- `references/tpl_schedule.json`
- `references/tpl_stadiums.json`
- `references/tpl_user_favorites.json`
- `references/tpl_predictions.json`

## 🧭 Query Classification

**⛔ STEP 0 — BEFORE CLASSIFYING:** Check if `worldcup2026/.bootstrapped` exists. If NOT, go back to the **BOOTSTRAP** section above and complete it. Do not classify the query, do not read templates, do not answer — bootstrap first. If `worldcup2026/.bootstrapped` exists, proceed to step 1.

* **Team-only queries:** If the query mentions a specific team *without* referencing a specific match (e.g. "USA squad", "Brazil injuries", "How is South Korea doing?"), it is a **general topic**. Look up the team's fixtures in `worldcup2026/schedule.json` to include in the response, then use `tmpl_general.md`. (This lookup ensures `worldcup2026/schedule.json` is bootstrapped — same mechanism that works for match queries.)
* **Match-specific queries:** If the query references a specific match, opening game, final, or fixture (e.g. "first game," "second match," "opener," "final," "game 3," "Brazil vs Morocco," "USA's first match") — it is a **match-specific query**. Ordinal rule: queries like "the second match" or "game 2" resolve to a specific fixture in `worldcup2026/schedule.json`, then use the match template. Default to pre-match/post-match/live templates.
* **General info:** For pure info requests (e.g. "how many groups?", "what cities host?", "who won in 2018?", "is Bolivia in the World Cup?"), first look up the topic in `worldcup2026/schedule.json` and `worldcup2026/stadiums.json` — this ensures the bootstrap has run. Then use `tmpl_general.md`.

1.  **Classify the query:**
    *   **Video request ("make a video of...", "generate video")?** → Read `references/tmpl_video.md`, then follow it.
    *   **Daily digest / "catch me up" / "today's news"?** → Read `references/tmpl_digest.md`, then follow it.
    *   **Specific upcoming match?** → Read `references/tmpl_pre_match.md`, then follow it.
    *   **Live match?** → Read `references/tmpl_live.md`, then follow it.
    *   **Finished match?** → Read `references/tmpl_post_match.md` + check `worldcup2026/predictions.json`, then follow it.
    *   **General topic (injuries, groups, etc.)?** → Look up the team/country in `worldcup2026/schedule.json` to find their fixtures. Then read `references/tmpl_general.md`, then follow it.
    *   **Prediction without match context?** → Ask which match.

2.  **Checklists:**
    *   **Match-specific:** Verify timezones (User + Local), cross-check injuries from 2+ sources via web search, include Prediction CTA (Pre-Match only).
    *   **General Query:** Answer directly. **NO** forced templates. Cite sources.
    *   **⚠️ Data sources:** Schedule/venue data comes from local files (`worldcup2026/schedule.json`, `worldcup2026/stadiums.json`). Everything else — injuries, form, odds, weather, breaking news — MUST come from web search, never from training data or memory.

## ⚠️ Footer

The footer (predictions, digest, video CTAs) is defined in each output template. See the "MANDATORY FOOTER" section in `references/tmpl_general.md`, `references/tmpl_pre_match.md`, etc. SKILL.md no longer duplicates this — templates are the single source of truth.

## Reference Files

**Workspace root** (dynamic user data):
* `worldcup2026/schedule.json` (all 104 matches), `worldcup2026/stadiums.json` (16 venues keyed by FIFA name).
* `worldcup2026/predictions.json` (user predictions), `worldcup2026/user_favorites.json` (favorites & flags).
* **Search web for:** Live scores, form, injuries, odds, weather, breaking news, **and schedule updates**.

**Skill `references/`** (static templates & guides):
* `references/tpl_*.json` — empty templates for bootstrapping.
* `references/tmpl_*.md` — output templates for pre-match, post-match, live, digest, video, general.
* `references/guide_predictions.md` — prediction system rules.

## 🔁 Hybrid Cache + Search (Auto-Update Logic)

**`worldcup2026/schedule.json` (`worldcup2026/` under workspace root) is a cache, not a static file.** Follow this flow for every schedule lookup:

1. **Read `worldcup2026/schedule.json`** — Check if the requested match exists.
2. **If found** → Use the cached data. Proceed.
3. **If NOT found** → The match may be a knockout fixture or newly confirmed:
    a. Search the web: `"FIFA World Cup 2026 [TeamA] vs [TeamB] schedule date venue"`
    b. Also search: `"World Cup 2026 knockout bracket confirmed matches"`
    c. If confirmed, **update `worldcup2026/schedule.json`** by appending the new match(es). Update the `"meta": {"last_updated": "YYYY-MM-DD"}` field.
    d. Proceed with the newly cached data.
4. **Never reject a prediction** just because the match isn't in `worldcup2026/schedule.json` — use the web search fallback first. Only reject if web search also cannot confirm the match.

**Schedule refresh rule:** If `"last_updated"` in `worldcup2026/schedule.json` is older than 7 days, proactively search for any newly confirmed knockout fixtures and update the file before answering.

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

### Export

The `worldcup/` skill folder contains templates and guides. Users export this folder. Each user gets their own `worldcup2026/` data files on first run via bootstrap.

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
