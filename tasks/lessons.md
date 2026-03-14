# Lessons

- When debugging packaging issues, do not patch files inside `dist/` as the final fix.
- Always apply code changes to source/build scripts first, then verify by rebuilding artifacts.
- If a temporary patch in built output is used for triage, explicitly replace it with source-level fixes before closing the task.

