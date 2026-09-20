# PR: make the context-window override explicit and show the effective value

> 用法：标题用下面 `## Title` 代码块的内容填 GitHub 的标题栏；正文粘贴从
> `## Description` 到文末的整段。模板要求 `## Description` 与 `## Evidence`
> 两个标题**逐字保留**（CI 的 "Real behavior proof" 检查按标题名匹配）。
> 本文件与 `docs/design/context-window-override-semantics.md` 随本 PR 一起提交
> （review 第四轮 P3-2），因此 "Documentation updated" 一栏成立。

## Title

**Recommended:**

```
fix(providers): make the context-window override explicit and show the effective value
```

**Alternatives:**

```
fix(providers): display the effective context window instead of the raw default
fix(console): show the resolved context window in the model config dialog
```

---

## Description

Relates to #7810.

(The issue is already closed — auto-closed by the repo bot — and was answered
in-thread with a user-side workaround: "change the value, then change it back
and save", which the reporter confirmed. This PR fixes the underlying defect:
the number the dialog shows is now the number that drives compaction.)

The model settings dialog showed a "Max Context Length" that could not take
effect: it rendered the raw `max_input_length` field (whose default is
`131072`) while the runtime resolves the window through a five-level
precedence chain, so for many models the number on screen had nothing to do
with the number that drove compaction.

### Problem

A user configured "Max Context Length" = 131072 and a compaction ratio of
0.5, expecting compaction around 65536 tokens. Instead requests grew to
~271k tokens and compaction appeared not to fire. Their own triage (and the
maintainer's reply in the thread) identified the workaround: change the
value to something else and change it back, then save — only then does the
number start to matter.

Concretely, with the pre-fix code:

| model | dialog showed | actually enforced | 0.5 ratio trigger |
| --- | --- | --- | --- |
| `gpt-5` | 131072 | 272000 | 136000 |
| `qwen3-max` | 131072 | 262144 | 131072 |
| `claude-sonnet-4-5` | 131072 | 200000 | 100000 |

The 272000 comes from the static pattern catalog, which is exactly the
"271k" the reporter observed.

### Root cause

Three compounding causes:

1. **Two sources of truth.** The dialog renders the stored field
   (`console/src/pages/Settings/Models/components/modals/ModelConfigEditor.tsx`),
   while the runtime calls `Provider.get_context_size()` →
   `context_windows.resolve_context_window()`, whose precedence is:
   explicit user value > provider-API auto-detected > provider/catalog value >
   static pattern catalog > 128k default.
2. **One field carrying three meanings.** `max_input_length` was at once the
   user-override slot, the carrier for provider/catalog data, and a "never
   configured" sentinel, with `max_input_length_configured` as the only way to
   tell them apart. So *a user who deliberately picked 131072* was
   indistinguishable from *nobody having configured anything* — the value was
   skipped and the catalog's 272000 won.
3. **Save-path gating.** The console only sends `max_input_length` when the
   input is dirty, which is why "modify, then save" was the only way to make
   the value stick.

Data context that explains a design detail below: the packaged model catalog
writes `ModelInfo`'s 128k field default as a placeholder for every window it
never collected. Measured over `providers/data/model_catalog.json`: **67 of
the 133 entries** that carry `max_input_length` store exactly `131072`, and for
**22 of those 67** the static pattern catalog resolves a *different* (larger)
window — `gpt-5` → 272000, `gpt-4.1` → 1047576, `o3` → 200000. The 272000 /
1047576 / 200000 figures are the *pattern-catalog* values; the catalog entry
itself only holds the placeholder. That is why the resolver had to treat
"stored value == default" as "not provided"; that rule is load-bearing, not
legacy cruft.

### Changes

**Backend**

- **Slot split instead of a magic default.** `ModelInfo.max_input_length`
  becomes `int | None` (`None` = inherit, matching the convention already used
  by `thinking_*`, `max_output_length`, `max_input_length_auto_detected`); a
  new `max_input_length_catalog` carries the provider/catalog-documented
  window; `max_input_length_configured` is removed. A user-chosen 131072 is now
  representable without a companion flag.
- **One resolution implementation.** `resolve_context_window_details()` returns
  the value *and* its provenance (`user` / `api` / `catalog` / `default`, typed
  as `ContextWindowSource`); `resolve_context_window()` is now a thin int
  wrapper. Resolution order is unchanged. Two deliberate deltas: the override
  branch gained a `> 0` guard (a written `0` would otherwise reach the
  compaction trigger and the usage percentage), and the "catalog value ==
  default means not provided" test moved out of the resolver into the catalog
  loading boundary (`providers/model_catalog.py`), where the placeholder
  actually originates.
- **Read-only projection, applied on every response path.**
  `effective_max_input_length` + `effective_max_input_length_source` are
  populated by one shared projection (`providers/provider.py`:
  `model_window_sources` / `project_model_window` / `project_model_windows`),
  used by `Provider.get_info()`, the hand-built Hub response, and the plugin
  registration list. It never writes to a live model and is stripped again on
  the snapshot write path (`provider_model_state.strip_derived_model_state`),
  so a client cannot round-trip a stale projection into a snapshot.
- **A discovered window now reaches configured models.**
  `resolve_window_from_info` reads the catalog slot from the configured entry
  and falls back to the discovery candidate, exactly like the API-detected
  slot, because a fetch reports its windows into the discovery entry's catalog
  slot (it must not write the override slot).
- **Provider-declared windows are catalog data, not user overrides.** The
  plugin registration boundary moves a window declared in a provider class's
  own default models (`get_default_models()`) into `max_input_length_catalog`.
  Previously such a declaration occupied the override slot, where it outranked
  an API-detected window and made the Console offer a "clear override" action
  the user never asked for.
- **Clearing an override is now expressible.** `PATCH
  /models/{provider}/{model}/config` accepts `max_input_length: null` to clear
  (absent = unchanged, `ge=1000` rejects non-positive values) and drops the
  field from `config_overrides`.
- **Snapshot migration v2 → v3** converts the legacy value+flag pair:
  explicit → kept as the user override; a data-provided value → the catalog
  slot; the 128k placeholder → dropped. Legacy snapshots keep resolving to the
  same window.
- **Discovery can no longer turn reported data into a user override.**
  OpenRouter's legacy write into the override slot is gone (its value is also
  written to `max_input_length_auto_detected`, so the outcome is unchanged),
  and fetch-reported windows are routed to the catalog slot.
- `serialize_model_state` drops `config_overrides` names whose field no longer
  exists, so snapshots converge instead of carrying dead names.

**Console**

- The input is the override slot: empty when the model is unconfigured, with
  the effective value as placeholder and a hint line
  `Inherited · effective 272,000 · from built-in catalog`; when the model is
  overridden the value is shown together with a "Clear override" button.
  Dirty-gating is preserved — an untouched field is never sent.
- New i18n keys (en/zh; the other five locales fall back through
  `i18n.fallbackLng = "en"`, i.e. they show the English string, and the number
  is formatted with the active locale). The six new keys are registered in
  `console/src/locales/providerPlatformLocales.test.ts` so the zh/en coverage
  and the interpolation of the hint line are locked by a test.
- The Agent configuration page's fallback path prefers the projection over the
  raw field.

**Tests** — rewritten `test_context_windows.py` (slots, provenance, clearing,
non-positive values, projection equality, two resolver-asymmetry cases, an O(N)
guard that fails if the projection re-scans per model), 5 migration cases, 2
API-contract cases (`null` = clear, non-positive rejected), 4 console tests,
plugin cases (declared window lands in the catalog slot; the registration list
carries the projection; a plugin that only overrides the instance-level hook is
deliberately *not* projected), 2 snapshot cases (dead override names, no
persisted projection), a manager-level set → reload → clear → reload case, the
locale-contract registration, plus adaptations in the
catalog/manager/mimo/volcengine/llamacpp/ACP/model-factory tests.

## Type of Change

- [x] Bug fix
- [ ] New feature
- [x] Breaking change
- [ ] Documentation
- [x] Refactoring

Breaking-change scope — three items, all plugin-facing:

1. `ModelInfo.max_input_length_configured` is gone, and provider responses gain
   two read-only fields. Unknown constructor kwargs are ignored by pydantic, so
   plugin code passing the old flag does not raise; the persisted field is
   removed by an automatic snapshot migration (`PROVIDER_SNAPSHOT_SCHEMA_VERSION`
   2 → 3).
2. A window a provider class declares in `get_default_models()` is moved to
   `max_input_length_catalog`, so `ModelInfo.max_input_length` now reads `None`
   for it. Provider code that read the field to size its own serving (for
   example a local `num_ctx`) must read `max_input_length_catalog`, or — better
   — call `get_context_size()`, which returns the declared window and honors a
   user override on top of it. Note the declared window keeps the *same*
   precedence it had before this change (rank 3, below an API-detected value),
   so resolved windows are unchanged.
3. A plugin that overrides the instance-level hook
   `_context_catalog_enabled()` (the only hook available before this PR) and
   does not declare the class-level `context_catalog_enabled()` is no longer
   given a projected `effective_max_input_length` in the provider list: the
   class-level answer would contradict the instance-level one the runtime uses.
   The Console tolerates a missing projection (it shows the raw hint only), and
   the runtime resolution is untouched. Override the class-level hook to get
   the projection back.

## Component(s) Affected

- [x] Core / Backend (app, agents, config, providers, utils, local_models)
- [x] Console (frontend web UI)
- [ ] Channels
- [ ] Skills
- [ ] CLI
- [ ] Documentation (website)
- [x] Tests
- [ ] CI/CD
- [ ] Scripts / Deploy

## Checklist

- [ ] I ran `pre-commit run --all-files` locally and it passes
      — `pre-commit` itself cannot run in my environment (its cache is not
      writable: `PermissionError: [Errno 13] Permission denied:
      'C:\Users\王飞\.cache\pre-commit\repoegf6kta8\.pre-commit-hooks.yaml'`),
      so every hook that touches Python was reproduced individually with the
      version and arguments from `.pre-commit-config.yaml`:
      `black 23.3.0 --line-length=79` (clean), `flake8` with the repo
      `.flake8` (clean except the repo-wide pre-existing `E203` on untouched
      lines), `mypy` with the hook's `--disable-error-code` set (no findings in
      the changed modules), `pylint` with the hook's `--disable` list
      (10.00/10). The root prettier hook excludes `^console/`, so the Console
      files are covered by the separate `console format check` CI job instead
      (`eslint` clean on the changed test file).
      **A maintainer-side `pre-commit run --all-files` is still the gate.**
- [ ] If pre-commit auto-fixed files, I committed those changes and reran checks
      — nothing auto-fixed; `black --line-length=79 --check` reports all
      changed Python files unchanged.
- [x] I ran tests locally (`pytest` or as relevant) and they pass
- [x] Documentation updated (if needed) —
      `docs/design/context-window-override-semantics.md` (design, checklist,
      four rounds of review evidence and the invariants the next change should
      preserve) is part of this PR, together with this description. The website
      does not document `ModelInfo.max_input_length` (its `max_input_length`
      rows describe `AgentsRunningConfig`, see Additional Notes), so no
      `website/` change is needed.
- [ ] Ready for review

Channel section: not applicable (no channel changes).

## Testing

Automated:

```bash
export PYTHONPATH='<repo>/src;<repo>/packages/qwenpawmail-mcp/src'
pytest tests/unit/providers tests/unit/app/routers tests/unit/local_models \
       tests/unit/agents/test_acp_runtime_provider.py -q

cd console
node ./node_modules/vitest/vitest.mjs run \
  src/pages/Settings/Models/components/modals/ModelConfigEditor.test.tsx \
  src/pages/Settings/Models/components/modals/ModelTokenFields.test.tsx \
  src/locales/providerPlatformLocales.test.ts
node node_modules/eslint/bin/eslint.js <changed ts files>
```

Manual (Console → Settings → Models → `<provider>` → Models → Model Config):

1. Open a model that is in the built-in catalog with a window ≠ 128k
   (e.g. `gpt-5`): the input is empty, placeholder `272000`, hint reads
   `Inherited · effective 272,000 · from built-in catalog`, no clear button.
2. Type `131072` and Save: the value sticks and a "Clear override" button
   appears.
3. Click "Clear override" and Save: `GET /api/models` returns
   `max_input_length: null` with the effective window back to the inherited
   value, and the input returns to the placeholder state.

## Evidence

### 1. Backend suites, with a baseline diff (this Windows machine)

This machine has a stable set of pre-existing environment failures, so the same
command is run on the branch and on `origin/main`, and the `FAILED` sets are
diffed (normalised with `sed 's/ - .*//'`, then `diff`):

```bash
$ pytest tests/unit/providers tests/unit/app/routers \
         tests/unit/agents/test_acp_runtime_provider.py tests/unit/local_models -q \
    --ignore=tests/unit/providers/test_retry_chat_model.py \
    --deselect tests/unit/providers/test_gemini_provider.py::test_summary_thinking_override_is_concurrency_safe

branch (a2a4d9d1 + fourth-round fixes):  24 failed, 1468 passed, 2 skipped
baseline (origin/main ee0c08e7):         23 failed, 1432 passed, 2 skipped

$ diff <(sorted baseline FAILED) <(sorted branch FAILED)   # only on this branch
FAILED tests/unit/app/routers/test_tools_router_web_search_config.py::test_update_tool_config_keyless_provider_skips_credential_io

$ pytest "<that test>" -q       # three times
1 passed in 4.08s / 3.73s / 6.94s
```

The one extra failure is the load-induced flake this box is known for (it is on
the `test_update_tool_config_*_skips_credential_io` family, passes 3/3 in
isolation, and does not import any provider module this PR touches). The other
23 are identical on both sides: stale local `agentscope` checkout
(`InjectionConfig` missing), missing optional packages, and this account's
missing symlink privilege / non-ASCII temp path. The two exclusions fail or hang
on the baseline too (the gemini test deadlocks by design). The pass-count
difference is exactly the cases this PR adds.

Focused files (fourth round included):

```bash
$ pytest tests/unit/providers/test_context_windows.py \
         tests/unit/providers/test_provider_model_state.py \
         tests/unit/providers/test_model_catalog.py \
         tests/unit/providers/test_hub_managed_provider.py \
         tests/unit/providers/test_provider_manager.py \
         tests/unit/local_models/test_llamacpp_backend.py \
         tests/unit/app/routers/test_provider_context_window.py \
         tests/unit/agents/test_acp_runtime_provider.py \
         tests/unit/agents/test_create_model_and_formatter_override.py -q
346 passed, 1 skipped in 33.30s
```

### 2. Data-impact check: the resolver's outcome is unchanged

Computed over the packaged catalog (reproducible from `model_catalog.json` +
`context_windows.known_context_size`):

```
catalog entries carrying max_input_length: 133
of those, exactly 131072 (the placeholder):  67
placeholder entries whose static-pattern window differs (> 131072): 22
outcome unchanged with the new slots:        111
outcome would change only if the "== default means not provided" rule
were dropped:                                 22   (every one is a placeholder)
```

That is why the rule was moved rather than deleted. The 22 entries include
`gpt-5`, `gpt-5-mini/nano`, `gpt-4.1*`, `o3`, `qwen3.8-max` (DashScope),
`qwen3.7-plus` / `glm-5.2` / `qwen3-coder-next` (Aliyun plans) — all of which
keep their current windows.

### 3. Resolution contract, asserted in tests

`tests/unit/providers/test_context_windows.py` and
`test_provider_info_projection_matches_the_resolution` pin, per model:

| case | override | API | catalog | resolved | source |
| --- | --- | --- | --- | --- | --- |
| untouched `gpt-5` | – | – | – | 272000 | `catalog` |
| user override | 131072 | – | – | 131072 | `user` |
| catalog slot | – | – | 1000000 | 1000000 | `catalog` |
| API beats catalog | – | 200000 | 1000000 | 200000 | `api` |
| override beats API | 65536 | 200000 | 1000000 | 65536 | `user` |
| unknown model | – | – | – | 131072 | `default` |
| non-positive slot | 0 | – | – | 272000 | `catalog` (never reaches the trigger) |
| catalog slot only on the *discovered* entry | – | – | 512000 | 512000 | `catalog` |
| projection equality | every model in a provider response | | | `== get_context_size()` | |

### 4. Plugin boundary, asserted in tests

```
plugin declares max_input_length=400000  ->  override None, catalog 400000,
                                            resolved 400000 / catalog
plugin's own read of max_input_length    ->  None   (breaking change 2)
plugin's get_context_size(...)           ->  400000 (the accessor to use)
registration list response               ->  effective 400000 / catalog
legacy plugin, instance hook only        ->  no effective_* in the list
                                            (runtime still 131072 / default)
stored registration after the projection ->  effective_* still None
                                            (derived state is response-only)
```

### 5. Real running instance (backend + rebuilt Console)

Taken on an earlier head of this branch; the Console code and the resolution
path are unchanged since, so the behaviour still holds.

`GET /api/models` on a live server (models anonymised only by selection):

```
openai/gpt-5                  max_input_length=None  catalog=None      effective=272000  source=catalog
dashscope/qwen3.7-max         max_input_length=65536                   effective=65536   source=user
dashscope/qwen3.8-max         max_input_length=32768                   effective=32768   source=user
kimi-cn/kimi-k2.7-code        catalog=262144         api=262144        effective=262144  source=api
github-models/openai/gpt-4o   api=131072                               effective=131072  source=api
modelscope/Qwen3.5-122B-A10B  (nothing)                                effective=131072  source=default
```

Console (bundle rebuilt from this branch, served at `127.0.0.1:8088/settings/models`):

| model | input | placeholder | hint line | clear button |
| --- | --- | --- | --- | --- |
| `poke/gpt-5.6-luna` (inherited, catalog) | empty | `272000` | `Inherited · effective 272,000 · from built-in catalog` | absent |
| `poke/gpt-6-astra` (inherited, default) | empty | `131072` | `Inherited · effective 131,072 · from 128K default` | absent |
| `dashscope/qwen3.7-max` (override) | `65536` | `65536` | base hint only | present |

Clear-override round trip in the same session: click "Clear override" → input
empties and Save becomes enabled → Save → `GET /api/models` returns

```
dashscope/qwen3.7-max: max_input_length=None effective=1000000 source=catalog
```

i.e. the model really returns to inheritance (this was then restored to the
user's original 65536 on disk and re-verified as `65536 / user`).

Screenshots taken during that run (attachable to the PR):

```
C:\Users\王飞\.zcode\cli\artifacts\sess_7c5b3cda-0745-4a75-9139-5c204709841b\call_00_39JVvDjwmp7uDLqcNNOY4976-tool-result-7bb17921-534e-426b-8fe8-e1a24bd99d77.png
C:\Users\王飞\.zcode\cli\artifacts\sess_7c5b3cda-0745-4a75-9139-5c204709841b\call_00_Swj02IpwZWMmMrBJZkur3828-tool-result-9584b35d-3f8f-4907-9ed5-57460cca2295.png
```

### 6. Console checks

```bash
$ node ./node_modules/vitest/vitest.mjs run \
    src/pages/Settings/Models/components/modals/ModelConfigEditor.test.tsx \
    src/pages/Settings/Models/components/modals/ModelTokenFields.test.tsx \
    src/locales/providerPlatformLocales.test.ts
Test Files  3 passed (3)
     Tests  30 passed (30)     # 7 model-config (3 pre-existing + 4 new),
                               # 3 context-length field, 20 locale-contract
                               # (10 pre-existing + 10 for the new keys)

$ node node_modules/eslint/bin/eslint.js src/locales/providerPlatformLocales.test.ts
(no output)

$ npm run build
✓ built in 5m 5s
[verify-monaco-css] OK - Monaco stylesheet present in 85 CSS file(s).
Precompressed 390 Console assets.
Initial bundle: 9.52 MiB raw, 2.38 MiB Brotli across 8 assets.
```

`tsc -b --noEmit` still reports 147 errors, all inside `src/pages/Chat/**`
(they come from a stale `@agentscope-ai/chat` in `node_modules`: installed
`1.1.73-beta` vs required `1.2.0-beta.*`; present on the baseline too). Zero
errors in the files this PR touches, and `npm install` + `npm run build`
passes once the dependency is at the pinned version.

### 7. Formatting / lint on the changed files

```bash
$ black --line-length=79 --check <changed Python files>   # pinned 23.3.0
All done! ✨ 🍰 ✨
<all files> would be left unchanged.

$ flake8 <changed Python files>                            # repo .flake8
(no output except the repo-wide pre-existing E203 on untouched lines)

$ mypy --ignore-missing-imports <hook's --disable set> <changed modules>
(no findings in the changed modules)

$ pylint <hook's --disable list> <changed Python files>
Your code has been rated at 10.00/10
```

Notes for anyone reproducing the format step locally: `black` **23.3.0** (the
pinned version) must be used — a newer black defaults to 88 columns and rewraps
unrelated code. If your checkout has `core.autocrlf=true`, the working tree is
CRLF while the committed blobs are LF, so `prettier --check` flags every file
including untouched ones; run it against the LF content (`git show :<path>`) or
trust the `console format check` job.

## Additional Notes

- **Not in this PR** (documented as follow-ups in
  `docs/design/context-window-override-semantics.md`, section 12):
  1. making the catalog's 131072 placeholder expressible (needs a catalog
     generator change; the 67-entry/22-impact list is in the design doc);
  2. whether the snapshot should keep pinning a catalog value over a newer
     packaged catalog;
  3. local models: `qwenpaw-local` does not opt out of the static catalog the
     way Ollama does, and `--ctx-size` is not fed back as the window;
  4. surfacing inherited values for `thinking_*` / `generate_kwargs` (same
     family of gap, no wrong numbers today);
  5. the *third* source of the same concept: `AgentsRunningConfig.max_input_length`
     (documented in `website/public/docs/config.en.md` as "Maximum input length
     for the model context window") is only read by `runtime/commands/daemon.py`
     as a display fallback when the resolved value is unavailable. It does not
     affect compaction, but the name invites the same confusion this PR fixes.
- Translations: only `en`/`zh` were added; the other five locales fall back to
  the English strings through `i18n.fallbackLng = "en"` (measured coverage of
  those files is 60–90%, so they are maintained asynchronously). The new keys
  are registered in `providerPlatformLocales.test.ts`, which is the repo's
  contract for interpolated user-visible text.
- A local incident worth flagging for reviewers reproducing the UI test: the
  backend used for verification shut down mid-way, so the "restore the original
  value" save never landed; the state was restored directly in the provider
  snapshot and re-verified offline. Recorded in the design doc, section 10.6.
- Review history: the branch carries four rounds of review fixes. The first
  three (slot semantics, Hub path / plugin signature / snapshot pinning,
  plugin-declared windows and the read-path projection) and the fourth
  (list-vs-runtime divergence for legacy plugin hooks, disclosed
  `max_input_length` read-back change, this description's data figures and
  checkbox accuracy, locale contract) are all recorded — reproduction steps,
  attribution and re-tests — in sections 13–16 of the design doc.
