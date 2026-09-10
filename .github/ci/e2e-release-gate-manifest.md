# E2E release gate / watch manifests

Source of truth for the release-time E2E blocking set (plan v1.6, item 1-6,
maintainer-approved 2026-09-09: "release e2e runs p0 only; p1/p2 stay nightly").

- `e2e-release-gate-tests.txt` — the blocking set. Red here fails the release
  gate (`e2e-release-gate` job in full-tests-nightly.yml, consumed by
  release.yml `full-test-gate`).
- `e2e-release-watch-tests.txt` — the report-only set. Red here is reported
  (release report + next-morning triage) but never blocks the release.

## Provenance

Both lists derive from the nightly e2e-p0 selection of 2026-09-09
(run 34382616145, job 102570938268, 71 selected node ids pulled from the job
log). The 7 cases that were red that night (environments batch under repair by
Li Shizhen + three new reds pending triage) went to the watch list; the 64
cases with a 12-night zero-red history went to the gate list.

## Entry / exit rules (no automatic mutation)

- A gate case that goes red and is triaged as **test-case rot** moves to the
  watch list; it returns to the gate list after 3 consecutive green nights.
- A gate case that goes red and is triaged as a **product defect** STAYS in
  the gate list — it is doing its job of blocking the release.
- Every move is recorded here (who / when / why) and in the release report.
  There is no automated add/remove: automation without review is silent
  set-shrinking, which is how green gets faked.

## Change log

- 2026-09-10 Qin Qiong: initial lists (64 gate / 7 watch) from run 34382616145.
