# Context-window PR review fixes

Scope: follow-up fixes for PR #7832, approved on 2026-09-20. Preserve the
single resolver, explicit override slot, read-only projection and v3 schema.

## Checklist

- [x] Hub defaults: use resolver provenance; test fallback, real 128k values,
  and create/update validation for unknown and known models.
- [x] Plugin hooks: isolate TypeError during list projection, log the plugin,
  and document the classmethod contract.
- [x] Console: restore the 131072 placeholder without a model projection;
  verify the Hub-style call and existing override behavior.
- [x] Discovery: normalize legacy 131072 placeholders at the input boundary;
  preserve explicit API/catalog values and user overrides.
- [x] Serialization: scope the index to the provider instance and honor
  get_model_info overrides; test isolation, cleanup and linear traversal.
- [x] Documentation: distinguish ordinary declarations, missing legacy flags
  and explicit overrides instead of claiming every snapshot changes rank.
- [x] Run focused backend/frontend tests and changed-file static checks.

## Decisions

Hub input limits are known exactly when the canonical resolution source is
not `default`; comparing the numeric value to 131072 is insufficient.

A malformed plugin class hook remains a plugin error. Listing providers
returns that registration without projection, while logging the failure.

Only the legacy discovery `max_input_length` carrier interprets 131072 as
missing data. A value explicitly supplied in the API or new catalog slot
retains its meaning. An explicit legacy placeholder clears stale discovery
catalog data; an omitted legacy field preserves existing metadata.

The serialization index is an optimization for the base lookup method, keyed
by the provider instance. Plugins overriding that method retain their own
lookup semantics, at the cost of the base-method shortcut.

Normal old snapshots explicitly stored `max_input_length_configured=False`.
The old restore helper inferred an override only when that flag was missing
or null and the value was non-default. Plugin default-model registration did
not use that helper. Migration continues to retain explicit true overrides.
The corrected PR text states the residual window change for flagless legacy
records only, instead of claiming every window is unchanged.

## Validation

Verification on 2026-09-20:

- `pytest tests/unit/providers` - 708 passed, 1 skipped.
- `pytest tests/unit/hub` - 200 passed, 7 skipped. One unrelated failure,
  `test_process_isolation.py::test_linux_command_mounts_python_base_prefix`,
  is a Windows `os.symlink` privilege error (WinError 1314) in a file this
  change does not touch; it also fails in isolation.
- `pytest tests/unit/app/routers` - 706 passed. Three unrelated environment
  failures: two worktree tests whose shell hooks need `touch`/`sleep` that the
  local Git shell does not provide, and
  `test_portability_imports_router.py::test_router_is_agent_scoped_and_localhost_only`,
  which asserts `APIRoute.original_router` and fails from the installed
  Starlette/FastAPI version. All three fail in isolation and touch no file
  changed here.
- Focused set (hub defaults, plugin registry, discovery, context windows,
  model state, model catalog, hub-managed provider, provider router) -
  137 passed.
- `vitest run ModelTokenFields/ModelConfigEditor/providerPlatformLocales` -
  31 passed.
- `black --line-length=79`, `flake8 --extend-ignore=E203`, `eslint` and
  `prettier --check` on the changed files - clean.

No PR publication or git commit is part of this change.
