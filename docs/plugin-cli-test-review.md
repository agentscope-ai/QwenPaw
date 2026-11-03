# Plugin CLI test review

Status: staged for reviewer review. The test scope and cost still need reviewer
approval. SDK version and API `since` values separately require maintainer
approval, as marked in the implementation.

## Review principles

- Fix regressions introduced by this PR, including incompatibilities with
  existing tests. Do not hide them with weaker assertions, skips or xfails.
- Keep new tests necessary and lightweight. Reuse existing fixtures and test
  files, avoid duplicate matrices, and review the cost of real transactions.
- Record independently reproduced main-branch failures without expanding this
  PR to fix them. An unclassified failure remains unresolved.

## Scope and reviewer checklist

| File | Coverage to review |
|---|---|
| `tests/unit/plugins/test_cli_invocation.py` (new) | Command discovery, help, invocation, disable/uninstall, dependency admission, extension revocation, and SIGINT cleanup before session close. |
| `tests/unit/channels/test_channel_host.py` | Static discovery, old/new dependency declarations, public capabilities independent of the receiver, deferred SDK imports, and combined-plugin rollback and teardown. Original descriptor-only cases remain. |
| `tests/unit/plugins/test_manifest_dependencies.py` | Named dependency installation and declaration validation. Existing pure Python installation tests remain; one new combined-channel case uses real offline wheels. |
| `tests/unit/cli/test_providers_cmd.py` | Normalized plugin IDs target the requested server; offline connection changes invalidate old discovery/probe state and retain plugin fields. Uses local HTTP/encryption substitutes. |
| `tests/typing/plugin_sdk_author.py` | Public CLI/extension return types in the existing installed-SDK author check. No new CI job. |

- [ ] Confirm that each added scenario protects a changed behavior or a reproduced defect.
- [ ] Approve the real worker/installation cases and their runtime cost.
- [ ] Confirm Windows/Linux behavior; this local run used macOS and Python 3.11.
- [ ] Complete the existing installed-SDK author type check before claiming type validation passed.

## Cost and recorded validation

Compared with main at `401662d8cbd2`, the runtime suite adds 32 parameterized
scenarios. Their aggregate local testcase duration was approximately 70.4
seconds. The four-file suite, including existing tests, passed 189 tests in
163.39 seconds. These timings are observations, not cross-platform guarantees.

The main new costs are combined-worker rollback (about 13.2 seconds) and named
dependency installation (about 11.5 seconds). The SIGINT subprocess took about
2.8 seconds. The two Provider cases together took about 0.006 seconds.

The CLI dependency matrix was reduced from eight to six scenarios. The new
installation matrix was reduced to one combined-channel case, reusing existing
pure Python coverage. Extension contracts run independently of CLI installation.
Tests add no dependencies or CI jobs and require no real platform account or
paid model. Installation fixtures use local wheels without an index. The signal
test interrupts only its own child process and has a 15-second failure bound.

Recorded checks:

- Existing loading, reload, config, isolation and cleanup: 193 passed.
- Cloudpaw and install-lock recheck: 34 passed, two existing platform skips.
- Dependency/lifecycle recheck: 110 passed, one failure reproduced on main.
- An extra source-tree strict mypy scan was stopped after exceeding five
  minutes. It did not produce a passing result and is not a new CI step.
  Installed-artifact type validation and a fresh nightly run were not completed
  in this round.

The main-reproduced failure is
`tests/unit/plugins/test_loader_dep_probing.py::test_host_observation_reuses_only_scoped_raw_inputs`.
Both versions differed from the expected whitespace in a multiline
`Requires-Dist` value under the same interpreter. Baseline source and test files
were checked against main. The test and implementation were left unchanged.

## Reproduce the affected runtime suite

Use the project's normal test environment; these commands install nothing:

```sh
python -m pytest tests/unit/channels/test_channel_host.py tests/unit/plugins/test_manifest_dependencies.py tests/unit/plugins/test_cli_invocation.py tests/unit/cli/test_providers_cmd.py -q --durations=15
pre-commit run
```

Public author types use the existing
`scripts/check_plugin_sdk_artifacts.py` installed-artifact workflow. A passing
pre-commit run does not replace that strict check or establish a full nightly
pass.
