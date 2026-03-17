# Lessons

- When debugging packaging issues, do not patch files inside `dist/` as the final fix.
- Always apply code changes to source/build scripts first, then verify by rebuilding artifacts.
- If a temporary patch in built output is used for triage, explicitly replace it with source-level fixes before closing the task.
- When a user provides a new API spec, re-check every integrated endpoint and token flow against that spec before extending the existing implementation; do not assume the previously wired auth endpoints are still valid.

- Frontend change: Replace direct fetch with `getApiUrl("/proboost-auth/send-sms-code")`
- When auth APIs already accept `countryCode`, do not hardcode a single default in the login/register UI; expose the supported country-code list in the form and pass the selected value through every auth action.
