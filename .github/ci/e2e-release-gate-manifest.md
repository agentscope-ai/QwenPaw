# E2E release gate / watch manifests

Source of truth for the release-time E2E blocking sets (plan v1.6, item 1-6).

Maintainer decision 2026-09-09 (verbatim): "release e2e runs p0 only; p1/p2
can wait for the nightly run". That covers the SCOPE. Splitting the p0 set into
a blocking list and a report-only list was an implementation split proposed by
Qin Qiong the same day and only tacitly accepted -- it was never an explicit
maintainer decision, and the previous wording of this file claimed otherwise.

- `e2e-release-gate-tests.txt` — the blocking set. Red here fails the release
  gate (`e2e-release-gate` job in full-tests-nightly.yml, consumed by
  release.yml `full-test-gate`).
- `e2e-release-watch-tests.txt` — the watch set. **Blocking** since
  2026-09-18; red here now fails the release gate exactly like the gate list
  does. It was report-only (red was reported but never blocked) from
  2026-09-10 until then.

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
- 2026-09-18 Qin Qiong: promoted the watch set from report-only to **blocking**
  on maintainer instruction ("upgrade e2e to block level too, consistent with
  the other accumulated tests"). Both lists now fail the release gate on red;
  the nightly form is unaffected (both jobs carry `if: form == 'release'` and
  the summary conditions are FORM-guarded).
  Trigger: release run 35204357591 (2026-09-17) shipped artifacts while
  `e2e-release-watch` was red -- `Test Summary` did not include the watch set,
  so the gate stayed green.
  Known cost: as of nightly run 35252349107 (2026-09-17), 3 of the 7 watch
  cases are still red (`test_create_acp_drawer_form`,
  `test_chart_area_display`, `test_session_rename_pin_delete_switch`; all
  triaged as test-case rot from upstream #7502, not product defects). Until
  that fix lands upstream, releases will be blocked by them. The other 4
  (environments batch) are green.
- 2026-09-18 Qin Qiong: corrected the attribution wording in this file -- the
  p0-only scope is the maintainer's decision, the report-only split was mine
  and only tacitly accepted. See release.yml and full-tests-nightly.yml, which
  carried the same inaccurate "maintainer decision" claim.
