# Rename PyPI Distribution Package: copaw → boostclaw

## TL;DR

> **Quick Summary**: Rename the PyPI distribution package from `copaw` to `boostclaw` so users install via `pip install boostclaw`. All internal Python module paths (`import copaw`), CLI command (`copaw`), environment variables (`COPAW_*`), config directories (`~/.copaw`), and Docker image names (`agentscope/copaw`) remain unchanged.
> 
> **Deliverables**:
> - `pyproject.toml` updated with `name = "boostclaw"`
> - All install scripts reference `boostclaw` package
> - All user-facing `pip install 'copaw[...]'` error messages updated
> - Console frontend PyPI URL and upgrade instructions updated
> - Build/pack scripts reference `boostclaw-*.whl` and `boostclaw-env.*`
> - All README and website docs `pip install` instructions updated
> - Build verification: `python -m build` produces `boostclaw-*.whl`
> 
> **Estimated Effort**: Short (< 2 hours of agent work)
> **Parallel Execution**: YES — 3 waves
> **Critical Path**: Task 1 (pyproject.toml) → Task 5 (build scripts) → Task 8 (build verification)

---

## Context

### Original Request
User wants to rename the distribution/install package from `copaw` to `boostclaw` so that `pip install boostclaw` works. The internal module name, CLI command, and all other internals stay as `copaw`.

### Interview Summary
**Key Discussions**:
- **Scope**: Distribution package name ONLY — not a full rename
- **CLI command**: Stays as `copaw` (user explicitly chose this)
- **Docker image**: Stays as `agentscope/copaw` (user chose to skip for now)
- **Archive names**: Rename `copaw-env.*` → `boostclaw-env.*` (user chose to rename)
- **Error messages**: Update all `pip install 'copaw[...]'` strings in Python source (auto-resolved — users need correct install commands)
- **Console PyPI URL**: Update `pypi.org/pypi/copaw/json` → `pypi.org/pypi/boostclaw/json` (auto-resolved — would 404 after rename)

### Research Findings
- ~2000+ occurrences of "copaw" across 70+ files, but only ~50 specific lines need changing
- Carefully categorized into 8 change categories (A through H)
- All target files read with exact line references confirmed

### Metis Review
**Identified Gaps** (all addressed):
- Python source error messages: CHANGE (users need correct pip install commands)
- Console frontend PyPI URL: CHANGE (would 404 after rename)
- Docker image name: SKIP for now (per user decision)
- Archive names: CHANGE to boostclaw-env.* (per user decision)

---

## Work Objectives

### Core Objective
Rename the PyPI distribution package from `copaw` to `boostclaw` across all user-facing references while preserving all internal module paths, CLI commands, and infrastructure names.

### Concrete Deliverables
- Updated `pyproject.toml` with `name = "boostclaw"`
- Updated install scripts (bash, PowerShell, batch)
- Updated Python source error messages (pip install instructions)
- Updated console frontend (PyPI URL + upgrade instructions)
- Updated build/pack scripts (wheel glob + archive names)
- Updated all README files (3 languages)
- Updated website documentation
- Build verification proof

### Definition of Done
- [ ] `python -m build` produces `dist/boostclaw-*.whl` and `dist/boostclaw-*.tar.gz`
- [ ] `pip install dist/boostclaw-*.whl` installs successfully
- [ ] `copaw --version` still works after install
- [ ] `import copaw` still works in Python
- [ ] `grep -r "pip install copaw" --include="*.py" --include="*.sh" --include="*.ps1" --include="*.bat" --include="*.tsx" --include="*.md" src/ scripts/ console/ README* website/` returns zero matches
- [ ] `grep -r "pip install 'copaw\[" --include="*.py" src/` returns zero matches

### Must Have
- `pyproject.toml` `name` field changed to `boostclaw`
- All `pip install copaw` and `pip install 'copaw[...]'` references in user-facing code updated
- Build scripts reference `boostclaw-*.whl`
- Archive names changed to `boostclaw-env.*`

### Must NOT Have (Guardrails)
- **DO NOT** rename `src/copaw/` directory
- **DO NOT** change any `import copaw` or `from copaw import` statements
- **DO NOT** change the CLI entry point `copaw = "copaw.cli.main:cli"`
- **DO NOT** change `[tool.setuptools.package-data] "copaw" = [...]`
- **DO NOT** change `copaw.__version__.__version__` version attribute reference
- **DO NOT** change any `COPAW_*` environment variables
- **DO NOT** change `~/.copaw` config paths
- **DO NOT** change Docker image name `agentscope/copaw`
- **DO NOT** change any GitHub URLs containing `CoPaw` or `copaw`
- **DO NOT** change branding text "CoPaw"
- **DO NOT** change test file imports
- **DO NOT** introduce any new files or abstractions
- **DO NOT** modify any logic — only string literals change

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: NO (existing tests don't cover distribution naming; adding tests for string literals is low value)
- **Framework**: pytest (existing)

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Build verification**: Use Bash — `python -m build`, inspect wheel name
- **Grep verification**: Use Bash — grep for stale `copaw` references in changed files
- **Import verification**: Use Bash — `python -c "import copaw"` after install

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — independent file groups):
├── Task 1: pyproject.toml metadata [quick]
├── Task 2: Install scripts (sh/ps1/bat) [quick]
├── Task 3: Python source error messages [quick]
├── Task 4: Console frontend (Sidebar.tsx) [quick]
├── Task 5: Build/pack scripts [quick]
├── Task 6: README files (3 languages) [quick]
└── Task 7: Website documentation [quick]

Wave 2 (After Wave 1 — build verification):
└── Task 8: Build & install verification [quick]

Wave FINAL (After ALL tasks — independent review, 4 parallel):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)

Critical Path: Task 1 → Task 8 → F1-F4
Parallel Speedup: ~80% faster than sequential (7 tasks in Wave 1 run simultaneously)
Max Concurrent: 7 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Blocks | Wave |
|------|-----------|--------|------|
| 1 | — | 8 | 1 |
| 2 | — | 8 | 1 |
| 3 | — | 8 | 1 |
| 4 | — | 8 | 1 |
| 5 | — | 8 | 1 |
| 6 | — | 8 | 1 |
| 7 | — | 8 | 1 |
| 8 | 1-7 | F1-F4 | 2 |
| F1 | 8 | — | FINAL |
| F2 | 8 | — | FINAL |
| F3 | 8 | — | FINAL |
| F4 | 8 | — | FINAL |

### Agent Dispatch Summary

- **Wave 1**: **7 tasks** — T1-T7 → all `quick`
- **Wave 2**: **1 task** — T8 → `quick`
- **Wave FINAL**: **4 tasks** — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

> Implementation tasks below. EVERY task has: Recommended Agent Profile + Parallelization + QA Scenarios.
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**

<!-- TASKS_START -->

- [ ] 1. Update pyproject.toml package metadata

  **What to do**:
  - Change `name = "copaw"` to `name = "boostclaw"` on line 2
  - Change self-referential optional-dependencies:
    - Line 66: `"copaw[local]",` → `"boostclaw[local]",`
    - Line 70: `"copaw[local]",` → `"boostclaw[local]",`
    - Line 77: `"copaw[local,ollama,llamacpp]",` → `"boostclaw[local,ollama,llamacpp]",`
  - **DO NOT** change line 33 (`copaw.__version__.__version__`) — module reference
  - **DO NOT** change line 41 (`"copaw" = [`) — setuptools package-data section
  - **DO NOT** change line 53 (`copaw = "copaw.cli.main:cli"`) — CLI entry point

  **Must NOT do**:
  - Change any module path references (lines 33, 41, 53)
  - Change any `[tool.setuptools]` package references
  - Change the `[project.scripts]` entry point name

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Single file, 4 line changes, straightforward string replacement
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4, 5, 6, 7)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:

  **Pattern References**:
  - `pyproject.toml:1-80` — Full project metadata section; lines 2, 66, 70, 77 are exact change targets

  **WHY Each Reference Matters**:
  - Executor must see surrounding context to avoid changing module references on nearby lines (33, 41, 53)

  **Acceptance Criteria**:
  - [ ] `grep -n '^name = ' pyproject.toml` → shows `name = "boostclaw"`
  - [ ] Lines 33, 41, 53 still contain `copaw` (module references preserved)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Distribution name changed correctly
    Tool: Bash
    Preconditions: pyproject.toml exists at repo root
    Steps:
      1. Run: grep -n '^name = ' pyproject.toml
      2. Assert output contains: 2:name = "boostclaw"
      3. Run: grep -n 'boostclaw\[' pyproject.toml
      4. Assert output shows lines 66, 70, 77 with boostclaw references
    Expected Result: 4 lines changed to boostclaw, remaining copaw references are module paths
    Failure Indicators: name = "copaw" still present, or module references changed to boostclaw
    Evidence: .sisyphus/evidence/task-1-pyproject-name.txt

  Scenario: Module references preserved (guardrail check)
    Tool: Bash
    Preconditions: pyproject.toml has been edited
    Steps:
      1. Run: sed -n '33p' pyproject.toml
      2. Assert output contains: copaw.__version__
      3. Run: sed -n '41p' pyproject.toml
      4. Assert output contains: "copaw"
      5. Run: sed -n '53p' pyproject.toml
      6. Assert output contains: copaw = "copaw.cli.main:cli"
    Expected Result: All 3 module reference lines unchanged
    Failure Indicators: Any of these lines contain "boostclaw"
    Evidence: .sisyphus/evidence/task-1-module-refs-preserved.txt
  ```

  **Commit**: YES (groups with Tasks 2-7)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: `pyproject.toml`

---

- [ ] 2. Update install scripts (sh/ps1/bat)

  **What to do**:
  - `scripts/install.sh`:
    - Line 234: `PACKAGE="copaw"` → `PACKAGE="boostclaw"`
    - Line 236: `PACKAGE="copaw==$VERSION"` → `PACKAGE="boostclaw==$VERSION"`
  - `scripts/install.ps1`:
    - Line 314: `$package = "copaw"` → `$package = "boostclaw"`
    - Line 315: `$package = "copaw==$Version"` → `$package = "boostclaw==$Version"`
  - `scripts/install.bat`:
    - Line 423: `set "_PACKAGE=copaw"` → `set "_PACKAGE=boostclaw"`
    - Line 436: `set "_PACKAGE=copaw%ARG_VERSION%"` → `set "_PACKAGE=boostclaw%ARG_VERSION%"`
  - **DO NOT** change any other `copaw` references in these files (CLI commands, config paths, branding)

  **Must NOT do**:
  - Change `copaw init`, `copaw app`, `copaw uninstall` CLI command references
  - Change `~/.copaw` config path references
  - Change any branding text "CoPaw"

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 3 files, 6 line changes total, simple string replacement
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4, 5, 6, 7)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `scripts/install.sh:230-240` — PACKAGE variable assignment; lines 234, 236 are targets
  - `scripts/install.ps1:310-320` — $package variable; lines 314, 315 are targets
  - `scripts/install.bat:420-440` — _PACKAGE variable; lines 423, 436 are targets

  **WHY Each Reference Matters**:
  - Each file has many copaw occurrences (CLI commands, paths, branding) — executor must change ONLY the PACKAGE variable lines

  **Acceptance Criteria**:
  - [ ] `grep -n 'PACKAGE.*boostclaw' scripts/install.sh` → shows lines 234, 236
  - [ ] `grep -n 'package.*boostclaw' scripts/install.ps1` → shows lines 314, 315
  - [ ] `grep -n 'PACKAGE=boostclaw' scripts/install.bat` → shows lines 423, 436
  - [ ] `grep 'copaw init' scripts/install.sh` → still returns matches (CLI preserved)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Install scripts reference boostclaw package
    Tool: Bash
    Preconditions: All 3 install scripts exist
    Steps:
      1. Run: grep -n 'PACKAGE="boostclaw' scripts/install.sh
      2. Assert 2 matches (lines ~234, ~236)
      3. Run: grep -n '\$package = "boostclaw' scripts/install.ps1
      4. Assert 2 matches (lines ~314, ~315)
      5. Run: grep -n '_PACKAGE=boostclaw' scripts/install.bat
      6. Assert 2 matches (lines ~423, ~436)
    Expected Result: All 6 package variable lines reference boostclaw
    Failure Indicators: Any PACKAGE variable still says copaw
    Evidence: .sisyphus/evidence/task-2-install-scripts.txt

  Scenario: CLI command references preserved
    Tool: Bash
    Preconditions: Install scripts edited
    Steps:
      1. Run: grep -c 'copaw init' scripts/install.sh
      2. Assert count > 0
      3. Run: grep -c 'copaw app' scripts/install.sh
      4. Assert count > 0
      5. Run: grep -c '\.copaw' scripts/install.sh
      6. Assert count > 0 (config path preserved)
    Expected Result: CLI commands and config paths unchanged
    Failure Indicators: grep returns 0 for any CLI command reference
    Evidence: .sisyphus/evidence/task-2-cli-refs-preserved.txt
  ```

  **Commit**: YES (groups with Tasks 1, 3-7)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: `scripts/install.sh`, `scripts/install.ps1`, `scripts/install.bat`

---

- [ ] 3. Update Python source pip install error messages

  **What to do**:
  - Update all user-facing `pip install 'copaw[...]'` error/hint messages to `pip install 'boostclaw[...]'`:
    - `src/copaw/cli/providers_cmd.py` lines 684, 736, 772: `copaw[local]` → `boostclaw[local]`
    - `src/copaw/local_models/manager.py` line 135: `copaw[local]` → `boostclaw[local]`
    - `src/copaw/local_models/backends/llamacpp_backend.py` line 62: `copaw[llamacpp]` → `boostclaw[llamacpp]`
    - `src/copaw/local_models/backends/mlx_backend.py` line 71: `copaw[mlx]` → `boostclaw[mlx]`
    - `src/copaw/providers/ollama_provider.py` line 38: `copaw[ollama]` → `boostclaw[ollama]`
    - `src/copaw/providers/ollama_manager.py` line 56: `copaw[ollama]` → `boostclaw[ollama]`
    - `src/copaw/app/routers/local_models.py` line 139: `copaw[local]` → `boostclaw[local]`
    - `src/copaw/app/routers/ollama_models.py` lines 173, 285: `copaw[ollama]` → `boostclaw[ollama]`
  - **DO NOT** change any `import copaw`, `from copaw import`, or module path references

  **Must NOT do**:
  - Change any import statements
  - Change any module references or function calls
  - Change any environment variable names

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 8 files, ~11 line changes, all identical pattern (pip install string)
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4, 5, 6, 7)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/copaw/cli/providers_cmd.py:680-775` — Three pip install hints in CLI provider commands
  - `src/copaw/local_models/manager.py:130-140` — Local model manager install hint
  - `src/copaw/local_models/backends/llamacpp_backend.py:58-65` — llama.cpp backend install hint
  - `src/copaw/local_models/backends/mlx_backend.py:67-75` — MLX backend install hint
  - `src/copaw/providers/ollama_provider.py:35-42` — Ollama provider install hint
  - `src/copaw/providers/ollama_manager.py:52-60` — Ollama manager install hint
  - `src/copaw/app/routers/local_models.py:135-145` — Local models router install hint
  - `src/copaw/app/routers/ollama_models.py:170-180,280-290` — Ollama models router install hints (2 locations)

  **WHY Each Reference Matters**:
  - Each file has many `copaw` references (imports, module paths) — executor must change ONLY the pip install string literals

  **Acceptance Criteria**:
  - [ ] `grep -rn "pip install 'copaw\[" --include="*.py" src/` → 0 matches
  - [ ] `grep -rn "pip install 'boostclaw\[" --include="*.py" src/` → 11 matches across 8 files

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: All pip install strings updated in Python source
    Tool: Bash
    Preconditions: All 8 Python files have been edited
    Steps:
      1. Run: grep -rn "pip install 'copaw\[" --include="*.py" src/
      2. Assert: 0 matches
      3. Run: grep -rn "pip install 'boostclaw\[" --include="*.py" src/
      4. Assert: 11 matches across 8 files
    Expected Result: All pip install strings reference boostclaw, zero stale copaw
    Failure Indicators: Any grep for copaw[ returns matches in pip install strings
    Evidence: .sisyphus/evidence/task-3-pip-install-strings.txt

  Scenario: Import statements preserved (guardrail check)
    Tool: Bash
    Preconditions: Python source files edited
    Steps:
      1. Run: grep -rn "from boostclaw\|import boostclaw" --include="*.py" src/
      2. Assert: 0 matches (no boostclaw imports anywhere)
    Expected Result: Zero boostclaw import statements exist
    Failure Indicators: Any import/from boostclaw found
    Evidence: .sisyphus/evidence/task-3-imports-preserved.txt
  ```

  **Commit**: YES (groups with Tasks 1, 2, 4-7)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: All 8 Python files listed above

---

- [ ] 4. Update console frontend (Sidebar.tsx)

  **What to do**:
  - `console/src/layouts/Sidebar.tsx`:
    - Line 45: `https://pypi.org/pypi/copaw/json` → `https://pypi.org/pypi/boostclaw/json`
    - Line 81: `pip install --upgrade copaw` → `pip install --upgrade boostclaw`
    - Line 110: `pip install --upgrade copaw` → `pip install --upgrade boostclaw`
    - Line 139: `pip install --upgrade copaw` → `pip install --upgrade boostclaw`
  - **DO NOT** change any React import paths or component references

  **Must NOT do**:
  - Change any import statements or component references
  - Change any branding text "CoPaw" in the UI

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Single file, 4 line changes, string replacement in TSX
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 5, 6, 7)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `console/src/layouts/Sidebar.tsx:40-145` — Version check fetch URL (line 45) and upgrade instruction messages (lines 81, 110, 139)

  **WHY Each Reference Matters**:
  - The PyPI URL on line 45 would 404 after package rename; upgrade instructions must match new package name

  **Acceptance Criteria**:
  - [ ] `grep -n 'boostclaw' console/src/layouts/Sidebar.tsx` → shows lines 45, 81, 110, 139
  - [ ] `grep -n 'pypi/copaw\|upgrade copaw' console/src/layouts/Sidebar.tsx` → 0 matches

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Console frontend references boostclaw
    Tool: Bash
    Preconditions: Sidebar.tsx has been edited
    Steps:
      1. Run: grep -n 'pypi/boostclaw' console/src/layouts/Sidebar.tsx
      2. Assert: 1 match at line ~45
      3. Run: grep -n 'upgrade boostclaw' console/src/layouts/Sidebar.tsx
      4. Assert: 3 matches at lines ~81, ~110, ~139
      5. Run: grep -n 'pypi/copaw\|upgrade copaw' console/src/layouts/Sidebar.tsx
      6. Assert: 0 matches
    Expected Result: All 4 references point to boostclaw
    Failure Indicators: Any stale copaw PyPI/upgrade reference remains
    Evidence: .sisyphus/evidence/task-4-sidebar-tsx.txt
  ```

  **Commit**: YES (groups with Tasks 1-3, 5-7)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: `console/src/layouts/Sidebar.tsx`

---

- [ ] 5. Update build/pack scripts

  **What to do**:
  - `scripts/pack/build_common.py`:
    - Line 54: `.glob("copaw-*.whl")` → `.glob("boostclaw-*.whl")`
    - Line 149: `f"copaw[full] @ {wheel_uri}"` → `f"boostclaw[full] @ {wheel_uri}"`
  - `scripts/pack/build_win.ps1`:
    - Line 10: `"copaw-env.zip"` → `"boostclaw-env.zip"`
  - `scripts/pack/build_macos.sh`:
    - Line 10: `"copaw-env.tar.gz"` → `"boostclaw-env.tar.gz"`

  **Must NOT do**:
  - Change any module path references in these scripts
  - Change any file paths referencing `src/copaw/`

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 3 files, 4 line changes, string replacement
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3, 4, 6, 7)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `scripts/pack/build_common.py:50-60` — Wheel glob pattern (line 54)
  - `scripts/pack/build_common.py:145-155` — Wheel install reference (line 149)
  - `scripts/pack/build_win.ps1:8-12` — Archive name (line 10)
  - `scripts/pack/build_macos.sh:8-12` — Archive name (line 10)

  **WHY Each Reference Matters**:
  - After pyproject.toml rename, `python -m build` produces `boostclaw-*.whl` — glob and install ref must match
  - Archive names are user-visible distribution artifacts

  **Acceptance Criteria**:
  - [ ] `grep -n 'boostclaw' scripts/pack/build_common.py` → shows lines 54, 149
  - [ ] `grep -n 'boostclaw' scripts/pack/build_win.ps1` → shows line 10
  - [ ] `grep -n 'boostclaw' scripts/pack/build_macos.sh` → shows line 10
  - [ ] `grep -n 'copaw-\*\|copaw\[full\]\|copaw-env' scripts/pack/build_common.py scripts/pack/build_win.ps1 scripts/pack/build_macos.sh` → 0 matches

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Build scripts reference boostclaw artifacts
    Tool: Bash
    Preconditions: All 3 build/pack scripts edited
    Steps:
      1. Run: grep -n 'boostclaw' scripts/pack/build_common.py
      2. Assert: 2 matches (wheel glob + install ref)
      3. Run: grep -n 'boostclaw-env' scripts/pack/build_win.ps1
      4. Assert: 1 match
      5. Run: grep -n 'boostclaw-env' scripts/pack/build_macos.sh
      6. Assert: 1 match
      7. Run: grep -n 'copaw-\*\|copaw-env\|copaw\[full\]' scripts/pack/build_common.py scripts/pack/build_win.ps1 scripts/pack/build_macos.sh
      8. Assert: 0 matches (no stale references)
    Expected Result: All artifact references point to boostclaw
    Failure Indicators: Any stale copaw artifact reference remains
    Evidence: .sisyphus/evidence/task-5-build-scripts.txt
  ```

  **Commit**: YES (groups with Tasks 1-4, 6-7)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: `scripts/pack/build_common.py`, `scripts/pack/build_win.ps1`, `scripts/pack/build_macos.sh`

---

- [ ] 6. Update README files (3 languages)

  **What to do**:
  - Update all `pip install copaw` and `pip install 'copaw[...]'` instructions in:
    - `README.md`
    - `README_zh.md`
    - `README_ja.md`
  - Specific patterns to change:
    - `pip install copaw` → `pip install boostclaw`
    - `pip install 'copaw[llamacpp]'` → `pip install 'boostclaw[llamacpp]'`
    - `pip install 'copaw[mlx]'` → `pip install 'boostclaw[mlx]'`
    - `pip install 'copaw[ollama]'` → `pip install 'boostclaw[ollama]'`
    - `pip install 'copaw[local]'` → `pip install 'boostclaw[local]'`
    - `pip install --upgrade copaw` → `pip install --upgrade boostclaw`
    - `pip install -e .` stays unchanged (source install, no package name)
    - `pip install -e ".[dev,full]"` stays unchanged
  - **DO NOT** change branding text "CoPaw"
  - **DO NOT** change GitHub URLs (`agentscope-ai/CoPaw`)
  - **DO NOT** change Docker image name `agentscope/copaw`
  - **DO NOT** change PyPI badge URLs (these are shields.io links, they'll auto-redirect or be updated separately)
  - **DO NOT** change `copaw init`, `copaw app`, or other CLI command references
  - **DO NOT** change documentation site URLs (`copaw.agentscope.io`)

  **Must NOT do**:
  - Change branding, GitHub URLs, Docker refs, CLI commands, doc site URLs, or badge URLs
  - Change install-from-source instructions (`pip install -e .`)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 3 files, pattern-based string replacement, but must be careful to avoid false positives
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-5, 7)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `README.md:1-350` — Full README; search for `pip install copaw` and `pip install 'copaw[`
  - `README_zh.md` — Chinese README; same patterns
  - `README_ja.md` — Japanese README; same patterns

  **WHY Each Reference Matters**:
  - READMEs contain many copaw references (branding, URLs, CLI commands) — only `pip install` lines should change
  - Badge URLs like `pypi.org/project/copaw/` are shields.io redirect URLs, not direct PyPI API calls — leave them

  **Acceptance Criteria**:
  - [ ] `grep -n 'pip install copaw' README.md README_zh.md README_ja.md` → 0 matches
  - [ ] `grep -n "pip install 'copaw\[" README.md README_zh.md README_ja.md` → 0 matches
  - [ ] `grep -n 'pip install boostclaw' README.md` → multiple matches
  - [ ] `grep -c 'CoPaw' README.md` → still > 0 (branding preserved)
  - [ ] `grep -c 'copaw init' README.md` → still > 0 (CLI commands preserved)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: README pip install instructions updated
    Tool: Bash
    Preconditions: All 3 README files edited
    Steps:
      1. Run: grep -rn 'pip install copaw' README.md README_zh.md README_ja.md
      2. Assert: 0 matches
      3. Run: grep -rn "pip install 'copaw\[" README.md README_zh.md README_ja.md
      4. Assert: 0 matches
      5. Run: grep -c 'pip install boostclaw' README.md
      6. Assert: count >= 1
    Expected Result: All pip install references use boostclaw
    Failure Indicators: Any pip install copaw reference remains
    Evidence: .sisyphus/evidence/task-6-readme-pip-install.txt

  Scenario: README branding and CLI commands preserved
    Tool: Bash
    Preconditions: README files edited
    Steps:
      1. Run: grep -c 'CoPaw' README.md
      2. Assert: count > 10 (branding preserved)
      3. Run: grep -c 'copaw init' README.md
      4. Assert: count >= 1 (CLI preserved)
      5. Run: grep -c 'copaw app' README.md
      6. Assert: count >= 1
      7. Run: grep -c 'agentscope/copaw' README.md
      8. Assert: count >= 1 (Docker preserved)
    Expected Result: All non-pip-install copaw references preserved
    Failure Indicators: Branding or CLI references changed to boostclaw
    Evidence: .sisyphus/evidence/task-6-readme-preserved.txt
  ```

  **Commit**: YES (groups with Tasks 1-5, 7)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: `README.md`, `README_zh.md`, `README_ja.md`

---

- [ ] 7. Update website documentation pip install references

  **What to do**:
  - Scan all `.md` files under `website/public/docs/` for:
    - `pip install copaw` → `pip install boostclaw`
    - `pip install 'copaw[...]'` → `pip install 'boostclaw[...]'`
    - `pip install --upgrade copaw` → `pip install --upgrade boostclaw`
  - Use `grep -rn "pip install copaw\|pip install 'copaw" website/public/docs/` to find all occurrences first
  - **DO NOT** change branding text, CLI command references, config path references, or documentation URLs

  **Must NOT do**:
  - Change `copaw init`, `copaw app`, or other CLI command references
  - Change `~/.copaw` config path references
  - Change documentation site URLs
  - Change branding text "CoPaw"

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Pattern-based string replacement across markdown files; scan-then-replace workflow
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-6)
  - **Blocks**: Task 8 (build verification)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `website/public/docs/` — Directory of documentation markdown files
  - `website/public/docs/quickstart.en.md` / `quickstart.zh.md` — Likely has pip install instructions
  - `website/public/docs/models.en.md` / `models.zh.md` — Likely has pip install extras instructions
  - `website/public/docs/intro.en.md` / `intro.zh.md` — Likely has pip install instructions
  - Note: Docs use `*.en.md` / `*.zh.md` naming convention — grep the whole directory to catch all

  **WHY Each Reference Matters**:
  - Executor must grep first to find all occurrences, then change only pip install strings
  - Website docs are rendered publicly — stale install instructions would confuse users

  **Acceptance Criteria**:
  - [ ] `grep -rn 'pip install copaw' website/public/docs/` → 0 matches
  - [ ] `grep -rn "pip install 'copaw\[" website/public/docs/` → 0 matches
  - [ ] `grep -rn 'copaw init' website/public/docs/` → still > 0 (CLI preserved)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Website docs pip install instructions updated
    Tool: Bash
    Preconditions: Website doc files edited
    Steps:
      1. Run: grep -rn 'pip install copaw' website/public/docs/
      2. Assert: 0 matches
      3. Run: grep -rn "pip install 'copaw\[" website/public/docs/
      4. Assert: 0 matches
      5. Run: grep -rn 'pip install boostclaw' website/public/docs/
      6. Assert: count >= 1
    Expected Result: All pip install references in docs use boostclaw
    Failure Indicators: Any stale pip install copaw reference remains
    Evidence: .sisyphus/evidence/task-7-website-docs.txt

  Scenario: Website docs CLI and branding preserved
    Tool: Bash
    Preconditions: Website doc files edited
    Steps:
      1. Run: grep -rc 'copaw init\|copaw app' website/public/docs/ | grep -v ':0$'
      2. Assert: at least 1 file still has CLI commands
      3. Run: grep -rc 'CoPaw' website/public/docs/ | grep -v ':0$'
      4. Assert: multiple files still have branding
    Expected Result: CLI commands and branding unchanged in docs
    Failure Indicators: CLI or branding references changed to boostclaw
    Evidence: .sisyphus/evidence/task-7-website-docs-preserved.txt
  ```

  **Commit**: YES (groups with Tasks 1-6)
  - Message: `build(dist): rename PyPI package from copaw to boostclaw`
  - Files: All modified files under `website/public/docs/`

---

- [ ] 8. Build and install verification

  **What to do**:
  - Run `python -m build` and verify the output wheel is named `boostclaw-*.whl`
  - Install the wheel in a temporary venv and verify:
    - `copaw --version` still works (CLI entry point preserved)
    - `python -c "import copaw"` still works (module name preserved)
  - Run comprehensive grep to verify zero stale references across entire scope
  - This is the gate task — all Wave 1 tasks must pass before this runs

  **Must NOT do**:
  - Make any file changes — this is a verification-only task
  - Push to PyPI or any registry

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Verification commands only, no code changes
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential after Wave 1)
  - **Blocks**: Final Verification Wave (F1-F4)
  - **Blocked By**: Tasks 1, 2, 3, 4, 5, 6, 7 (all Wave 1 tasks)

  **References**:
  - `pyproject.toml` — Build config (already modified by Task 1)
  - All files modified by Tasks 1-7

  **WHY Each Reference Matters**:
  - This task validates the cumulative effect of all Wave 1 changes

  **Acceptance Criteria**:
  - [ ] `python -m build` → produces `dist/boostclaw-*.whl` and `dist/boostclaw-*.tar.gz`
  - [ ] `pip install dist/boostclaw-*.whl` → installs successfully
  - [ ] `copaw --version` → prints version
  - [ ] `python -c "import copaw"` → no error
  - [ ] Comprehensive grep → zero stale `pip install copaw` references in scope

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Build produces boostclaw wheel
    Tool: Bash
    Preconditions: All Wave 1 tasks complete, pyproject.toml has name = "boostclaw"
    Steps:
      1. Run: rm -rf dist/
      2. Run: python -m build
      3. Run: ls dist/
      4. Assert: Files matching boostclaw-*.whl and boostclaw-*.tar.gz exist
      5. Assert: No files matching copaw-*.whl exist
    Expected Result: dist/ contains boostclaw-versioned wheel and sdist
    Failure Indicators: Build fails, or output still named copaw-*
    Evidence: .sisyphus/evidence/task-8-build-output.txt

  Scenario: Install and CLI verification
    Tool: Bash
    Preconditions: Wheel built successfully
    Steps:
      1. Run: python -m venv /tmp/boostclaw-test-venv
      2. Run: /tmp/boostclaw-test-venv/bin/pip install dist/boostclaw-*.whl
      3. Run: /tmp/boostclaw-test-venv/bin/copaw --version
      4. Assert: Version string printed (e.g., "0.0.7")
      5. Run: /tmp/boostclaw-test-venv/bin/python -c "import copaw; print(copaw.__version__)"
      6. Assert: Version string printed
      7. Run: rm -rf /tmp/boostclaw-test-venv
    Expected Result: Package installs, CLI works, module imports work
    Failure Indicators: pip install fails, copaw command not found, import error
    Evidence: .sisyphus/evidence/task-8-install-verify.txt

  Scenario: Comprehensive stale reference check
    Tool: Bash
    Preconditions: All files modified
    Steps:
      1. Run: grep -rn 'pip install copaw' --include='*.py' --include='*.sh' --include='*.ps1' --include='*.bat' --include='*.tsx' --include='*.md' src/ scripts/ console/src/ README*.md website/public/docs/
      2. Assert: 0 matches
      3. Run: grep -rn "pip install 'copaw\[" --include='*.py' src/
      4. Assert: 0 matches
      5. Run: grep -rn 'copaw-\*.whl\|copaw-env\|copaw\[full\]' scripts/pack/
      6. Assert: 0 matches
    Expected Result: Zero stale distribution name references anywhere in scope
    Failure Indicators: Any grep returns matches
    Evidence: .sisyphus/evidence/task-8-stale-refs.txt
  ```

  **Commit**: NO (verification only, no file changes)

---

<!-- TASKS_END -->

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (grep for `boostclaw` in each target file). For each "Must NOT Have": search codebase for forbidden changes — reject with file:line if found. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m build` to verify clean build. Review all changed files for: accidental logic changes, broken string formatting, misplaced replacements (module path changed instead of distribution name). Check no `import boostclaw` or `from boostclaw` was introduced. Verify no `.py` files have `boostclaw` where `copaw` module reference was intended.
  Output: `Build [PASS/FAIL] | Changed Files [N clean/N issues] | False Positives [CLEAN/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Run `python -m build` — verify wheel is named `boostclaw-*.whl`. Install the wheel in a venv. Verify `copaw --version` works. Verify `python -c "import copaw; print(copaw.__version__)"` works. Grep all changed files to confirm zero stale `pip install copaw` or `pip install 'copaw[` references. Save evidence screenshots/outputs.
  Output: `Build [PASS/FAIL] | Install [PASS/FAIL] | CLI [PASS/FAIL] | Import [PASS/FAIL] | Grep [CLEAN/N stale] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (`git diff`). Verify 1:1 — everything in spec was changed, nothing beyond spec was changed. Specifically verify: no `src/copaw/` directory rename, no import statement changes, no `COPAW_*` env var changes, no `~/.copaw` path changes, no Docker image name changes, no GitHub URL changes, no branding changes. Flag any unaccounted changes.
  Output: `Tasks [N/N compliant] | Guardrail Violations [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Single commit after all Wave 1 tasks**: `build(dist): rename PyPI package from copaw to boostclaw` — all changed files
- Pre-commit verification: `python -m build` succeeds, grep confirms no stale references

---

## Success Criteria

### Verification Commands
```bash
python -m build                    # Expected: dist/boostclaw-*.whl, dist/boostclaw-*.tar.gz
pip install dist/boostclaw-*.whl   # Expected: successful install
copaw --version                    # Expected: prints version (CLI still works)
python -c "import copaw"           # Expected: no error (module still works)
grep -rn "pip install copaw" --include="*.py" --include="*.sh" --include="*.ps1" --include="*.bat" --include="*.tsx" --include="*.md" src/ scripts/ console/src/ README*.md  # Expected: 0 matches
grep -rn "pip install 'copaw\[" --include="*.py" src/  # Expected: 0 matches
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] `python -m build` produces `boostclaw-*.whl`
- [ ] `copaw` CLI still works
- [ ] `import copaw` still works
- [ ] Zero stale `pip install copaw` references in scope
