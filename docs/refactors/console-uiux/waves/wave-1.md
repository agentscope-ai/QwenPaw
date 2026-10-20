# Wave 1 Closeout

## Status

`CLOSED` on 2026-10-15, Asia/Shanghai.

| Field | Value |
|---|---|
| Goal | Resolve F1, F2, F3, F4, F5, F8, F11, and F12 |
| Base SHA | `c7702cc617690f1d0cd0318827c9aa635b3da3a8` |
| Initial review HEAD | `cff936b699d5936881be75c47b4b469d08f8bb3b` |
| Final SHA | `7df8c7819673e815b765cfaa760baad793e1e823` |
| Integration branch at the time | `feat/console-uiux-wave1` (now renamed to `feat/console-uiux-refactor`) |
| Independent reviewer | `01a13e66-462a-7292-a7fe-aafb5d3662d8` |
| Initial verdict | `APPROVE WITH FIXES` |
| Final verdict | `APPROVE` |
| Push / PR / release | Not requested and not verified |

## Commit map

| Finding / support | Commit | Subject |
|---|---|---|
| F1 | `28109b4cc9e0bd294484a64e68b92216b1fd4e52` | `fix(console): prevent stale tools requests overwriting agent state` |
| F5, Classic Console | `ec5cb20704c454caae327e3628e8af4c9f10f125` | `fix(console): deduplicate push message polling` |
| F11 | `21e8ff6be08872ceb3b00a4fc642c16e7f17a4bd` | `fix(settings): label the language selector` |
| F12 | `fbdf77bf8cc9f7e81ce7ea6c11c0c30247e76c3a` | `fix(models): name provider card actions` |
| F3 | `fe924da8e142254656f5bed7dbfcaa7cc6a8bf45` | `fix(settings): keep general controls inside cards` |
| F3 test formatting | `a61c5c64adb9854e317c341c64e626ba18cf3f14` | `style(tests): format settings regression tests` |
| F4 | `fd8801b03bf141530e962001c83b4c7ff0a84830` | `fix(chat): label composer icon actions` |
| F8 | `59fdd5041f8b8d0114cf4bcd3cc13b7418feef9e` | `fix(chat): use semantic tokens in queue panels` |
| F2 | `8b2317cb64bf535fc2b5e40623b861aa95b1e9f4` | `fix(chat): queue concurrent approvals` |
| F4 SDK lifecycle | `cff936b699d5936881be75c47b4b469d08f8bb3b` | `fix(chat): label sdk composer actions reliably` |
| F5 M1 repair | `57676c037c4874226cea42b9cb2995e3858707fb` | `fix(console): share desktop approval polling state` |
| F4 M2 repair | `7df8c7819673e815b765cfaa760baad793e1e823` | `fix(chat): enlarge mobile submit touch target` |

The full final range changes 41 files with 1,403 insertions and 301 deletions.
Task-level worktree identities for the initial Wave 1 implementation were not
recovered from the current evidence package; they are therefore not invented
here. The design lead thread is
`01a13e1d-d252-7813-aaad-cf4a94a63dd0`.

## Validation and review

Initial independent review at `cff936b6`:

- 12 targeted test files, 225 tests passed.
- Targeted ESLint: 0 errors and 18 existing hook warnings.
- `git diff --check` passed.
- Browser/runtime checks covered the key responsive breakpoints, accessible
  names, light/dark theme behavior, and input geometry.
- The reviewer found two Minor issues: the Desktop OS duplicate polling chain
  and the 390px submit/stop 32×32 hit target.

Final repair review at `7df8c781`:

- 5 targeted test files, 55/55 passed.
- Targeted ESLint and `git diff --check` passed.
- 390×844 browser runtime measured send, microphone, and attachment controls at
  44×44; stop behavior was covered by the targeted component contract.
- Production source had one `/console/push-messages` owner; Desktop OS consumed
  shared approval state while retaining its inbox query.
- Independent verdict: `APPROVE`. Wave 1 then became eligible for closure and
  its final SHA became the Wave 2 base.

No full build, format, or test run was performed.

## Returned fixes

- M1 mapped to F5 and was resolved by `57676c037`.
- M2 mapped to F4 and was resolved by `7df8c7819`.

`APPROVE WITH FIXES` did not close the Wave; closure occurred only after the
independent final `APPROVE`.

## Unverified and residual boundaries

- Real concurrent approvals were not available in the browser; F2 used a
  targeted fixture.
- True physical touch and screen-reader speech output were not executed.
- Queue/BackgroundTask custom-theme visuals had static/token and targeted-test
  evidence, not a complete browser fixture.
- Platform-native macOS/Linux/Windows execution was not run; the reviewer
  assessed low cross-platform risk statically for this React/CSS/header scope.
- Broader shared components, warning cleanup, and IA convergence were outside
  this Wave.

## Rollback boundary

Each functional change is represented by a focused commit. The two post-review
repairs are separately revertible, subject to preserving the dependent F4/F5
contracts and re-running their targeted tests.

