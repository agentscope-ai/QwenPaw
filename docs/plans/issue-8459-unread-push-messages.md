# Issue #8459: Easier access to unread push messages

Issue: https://github.com/agentscope-ai/QwenPaw/issues/8459

## Agreed scope

The user approved this plan on 2026-10-29. Add an accessible “Unread only”
toggle to the push-message toolbar, keeping the initial view on all messages.
Reuse the existing `unread_only` API parameter so older unread messages are
queried directly instead of being hidden behind the latest 200 messages.
Keep agent/source filters, read actions, batch selection, and pagination
consistent when the toggle changes. Reuse the existing Ant Design controls,
Lucide icons, Less modules, and theme tokens.

No backend changes are needed. The existing query still returns at most 200
matching events; this change does not introduce server-side pagination.

## Checklist

- [x] Read the issue and inspect the frontend and existing API support.
- [x] Agree on the implementation plan with the user.
- [x] Add the unread toggle and localized empty-state text.
- [x] Query unread events on the server and prevent stale requests from
      replacing the current filter's results.
- [x] Reset pagination and batch selections when switching the filter;
      immediately hide messages marked read in the unread view.
- [x] Add regression tests for filtering, historical unread messages,
      request races, read updates, pagination, and empty/loading states.
- [x] Run the relevant tests, formatting/lint checks, type checks, and build.
- [x] Verify the checkbox/text alignment reported by the user across
      desktop, phone, landscape, tablet, and light/dark themes.

## Verification

- The six relevant Vitest files pass: **129 tests, zero failures**. The
  suites cover the page, inbox data hook, trace viewer, message cards,
  console API, and event helpers.
- ESLint passes for all four changed TypeScript/TSX files. Prettier passes
  for the changed TypeScript/TSX, Less, and all seven locale JSON files.
- `npm run build` passes, including TypeScript checks, the production
  build, Monaco stylesheet verification, asset precompression, and the
  initial-bundle check.
- Playwright checks pass using the real inbox page and providers with
  isolated synthetic API responses. The fixture contains 200 recent read
  events and two older unread events. This verifies keyboard toggling,
  historical unread retrieval, viewing/marking messages read, marking all
  read, and returning to the full list.
- Browser checks cover 1440×1000, 375×812 (light and dark), 812×375, and
  768×1024. There is no horizontal overflow or page JavaScript error.
  Checkbox/text vertical centers differ by **0 px** in every case; the
  label retains a 40 px desktop and 44 px mobile touch target.
- The user reported text/checkbox misalignment in the first implementation.
  Explicit inline-flex centering fixes the default baseline alignment after
  increasing the hit-area height. Checked and unchecked screenshots were
  visually inspected.

Browser results, screenshots, and the final build log are saved outside the
repository in
`/Users/zz/.codex/visualizations/2026/10/29/01a1854e-63fc-76b0-a8e0-91a3948ff901/issue-8459/`.
The temporary browser verification entry point was removed from the console.
Browser verification uses mocked API fixtures rather than a live backend.
