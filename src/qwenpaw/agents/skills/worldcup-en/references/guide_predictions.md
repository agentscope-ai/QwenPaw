# Prediction System Guide

**File:** `worldcup2026/predictions.json` (`worldcup2026/` under workspace root)
**Format:** Use `references/tpl_predictions.json` as the blueprint when creating the file for the first time.
**Rule:** Always `read_file` first, then `write_file` to update.

### Activation Tracking
When the user makes their **first** prediction:
1.  Update `worldcup2026/predictions.json` as normal.
2.  Read `worldcup2026/user_favorites.json`. If it does not exist, create it from `references/tpl_user_favorites.json`. Set `"features_activated.predictions": true`.
3.  This ensures the Prediction Footer is suppressed in future responses.

## Scoring

| Result | Points |
|---|---|
| Exact score correct | **+10** |
| Correct winner, wrong score | **+5** |
| Correct draw with correct score | **+10** |
| **Correct draw outcome (wrong score)** | **+5** |
| Wrong prediction | **0** |

> **Note:** Do not award partial points or "consolation" points (e.g., +3) unless specified above. If the user gets the winner correct (even if score is off), it is **+5**. If they get the draw correct (wrong score), it is **+5**.

## Stat Logic & Definitions

**Crucial for consistency across sessions and users:**

* **Pending Predictions Rule:** Any prediction with `"status": "pending"` MUST have `correct_exact: 0`, `correct_winner: 0`, `wrong_winner: 0`, `wrong_score: 0`, and `points: null`. **Do not count pending predictions toward accuracy percentages or wrong-score stats.** Only update stats after `actual_score` is set and the match is final.

* **`correct_winner` (Inclusive):** Counts **ALL** predictions where the user identified the winning team (or draw outcome) correctly.
    *   **Formula:** `correct_winner = (Exact Score Hits) + (Correct Winner, Wrong Score)`.
    *   *Example:* If you have 3 exact hits and 4 close wins, `correct_winner` is **7**.
* **`wrong_winner`:** Counts predictions where the outcome was completely incorrect.
* **`accuracy_winner_pct`:** Calculated as `correct_winner / total_predictions_with_result` (exclude pending from denominator).

* **`wrong_score` (Comprehensive):** Counts **ALL** non-exact predictions that have been scored.
    *   **Includes:** Both "Wrong Winner" and "Correct Winner, Wrong Score".
    *   **Formula:** `wrong_score = predictions_with_result - correct_exact`.

* **`accuracy_exact_pct`:** The percentage of predictions where the user got the **exact scoreline** correct.
    *   **Formula:** `(correct_exact / predictions_with_result) * 100` (exclude pending from denominator).

## User Formats

*   "Mexico 2-0" or "2-1" → Exact score (always include team name or score)
*   "2-2" or "1-1" → Draw with score
*   **All predictions must include a score.** Winner-only ("Mexico") or "Draw" alone are not valid. If the user submits without a score, prompt them to include one.

## Prediction CTA Box

**ALWAYS** include this box at the end of Pre-Match Analysis (after "Key to Watch"):

### Standard (No Prior Prediction)

```markdown
---

## 🎯 Make Your Prediction!

| Your Record | 🏆 [W]W–[L]L · [N] predictions · [P] points |
|---|---|

**Reply with a scoreline:**
- **`[Team A] 2-0`** or **`[Team B] 1-3`** — Include the team you think wins
- **`2-2`** or **`1-1`** — You think it's a draw

> ⚠️ **A scoreline is required.** Team name only or "Draw" alone won't count — always include the score.
> *I'll score your prediction right after the final whistle!*
```

### Already Predicted (User has existing prediction)

When the user already predicted this match, show their current pick with a ✅ indicator:

```markdown
---

## 🎯 Make Your Prediction!

| Your Record | 🏆 [W]W–[L]L · [N] predictions · [P] points |
|---|---|

✅ **Your current prediction:** **[Predicted Score]**

**Want to change it? Reply with a new scoreline:**
- **`[Team A] 2-0`** or **`[Team B] 1-3`** — New predicted score
- **`2-2`** or **`1-1`** — New predicted draw

> ⚠️ **A scoreline is required.** Always include the score.
> *I'll score your prediction right after the final whistle!*
```

**How to detect:** Check `worldcup2026/predictions.json` (`worldcup2026/` under workspace root) for a matching `match` or `match_id` entry. If `predicted_score` is set (non-null), show the "Already Predicted" variant.

### Validation

Before logging any prediction, verify the match exists by searching the web.
- **Knockout placeholder:** For confirmed knockout fixtures (e.g., "Winner Group B vs Runner-up Group D"), log them with a placeholder format until teams are finalized.
- **Duplicate match handling:** If two teams play each other more than once in the tournament (e.g., group stage + rematch in final):
  1. **Always use `match_id`** as the primary key for logging and scoring.
  2. If the user provides `"Team A vs Team B"` without a match ID or date, default to the **next upcoming match** between those teams.
  3. If multiple matches have already occurred or are scheduled simultaneously, ask the user to clarify (e.g., "Group stage or knockout?").

**Enforcing scores:** When the user replies with a team name only (e.g., "Mexico") or just "Draw", reject it and ask them to include a score. Parse scorelines as:
- `TeamName X-Y` → parse team and score
- `X-Y` → parse as score alone (infer winner from score, or draw if equal)

## JSON Structure (Self-Contained & Flattened)

```json
{
  "user": "Name",
  "total_points": 0,
  "stats": {
    "total_predictions": 0,
    "correct_exact": 0,
    "correct_winner": 0,
    "wrong_winner": 0,
    "wrong_score": 0,
    "accuracy_winner_pct": 0.0,
    "accuracy_exact_pct": 0.0
  },
  "predictions": [
    { "match_id": 1, "date": "2026-06-11", "match": "Mexico vs South Africa", "predicted_score": "2-1", "actual_score": null, "points": null, "status": "pending" }
  ]
}
```
