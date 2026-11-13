# Issue #8683: responsive file preview

## Agreed scope

Fix the file preview in portrait tablet browsers without changing the file
workspace architecture or adding dependencies. The user approved this plan
on 2026-11-13.

- Use an overlay at tablet widths so the chat pane cannot push preview
  controls outside the visible area. Preserve desktop resizing and its
  saved widths.
- Add an accessible Lucide fullscreen/restore control. Fullscreen stays
  inside the page, fills the viewport, and does not require the browser
  Fullscreen API. Escape restores the preview before closing it on a
  subsequent press. The preview contents stay mounted during the toggle.
- Keep copy, download, and close available. Reduce nested preview padding
  and adapt the header/footer to narrow screens and long filenames.
- Verify fullscreen behavior, existing file operations, desktop resizing,
  and portrait tablet/mobile layouts.

## Checklist

- [x] Inspect the issue and locate the drawer layout and preview styles.
- [x] Agree on the change plan with the user.
- [x] Establish a passing baseline: 86 tests across three related files.
- [x] Add regression tests and confirm they fail before the fix (3 failures).
- [x] Implement responsive layout and fullscreen/restore behavior.
- [x] Run relevant tests, TypeScript, lint, and formatting checks.
- [x] Verify tablet/mobile/desktop layouts and record the results.
- [x] Complete the production build and bundled asset checks.

## Validation results

- Regression first: the three new fullscreen tests failed before the fix;
  the existing 14 drawer tests still passed.
- Related regression suite: 296 tests passed across 20 test files, covering
  the complete files-workspace feature, file preview, and typography.
- `npx tsc -b --noEmit`: passed.
- Targeted ESLint, Prettier checks, and `git diff --check`: passed.
- Browser verification used Chromium 147.0.7727.15 with the actual drawer,
  Markdown preview, shared theme, and chat layout styles. File API responses
  were stubbed in the fixture. This was browser viewport simulation, not a
  physical Android device test.
- Eight reduced-motion layouts passed: 1600x1000, 1024x1366, and 800x1280
  with the sidebar both expanded and collapsed, plus 390x844 and 320x640.
  Every header action remained visible and clickable, touch targets were
  at least 44px wide, and the page had no horizontal overflow.
- Fullscreen filled the viewport in every case. With a 240px sidebar at
  800px viewport width, the document grew from 560px to 800px. Escape
  restored the previous layout; a second Escape closed the preview.
- Standard-motion checks passed at desktop, portrait tablet, and 320px
  mobile sizes. Live resizing from desktop to tablet and back preserved
  fullscreen behavior and the saved 480px desktop drawer width. No browser
  page errors were observed.
- `npm run build`: passed, including TypeScript, Vite production bundling,
  Monaco stylesheet verification, precompression of 557 assets, and the
  initial bundle check. Vite reported chunk-size and mixed static/dynamic
  import warnings; the build and all asset checks completed successfully.
