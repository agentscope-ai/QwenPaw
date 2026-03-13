## Learnings

> Conventions, patterns, and wisdom accumulated during this plan's execution.

---

### Initial Context

**Plan Objective**: Rename PyPI distribution package from `copaw` to `boostclaw` — distribution name ONLY. All internal module paths, CLI commands, env vars, config paths, Docker image names remain as `copaw`.

**User Decisions**:
- CLI command stays as `copaw`
- Docker image stays as `agentscope/copaw`
- Archive names change to `boostclaw-env.*`
- Error messages with pip install instructions updated
- Console frontend PyPI URL updated

**Critical Guardrails**:
- DO NOT rename `src/copaw/` directory
- DO NOT change any imports (`import copaw`, `from copaw import`)
- DO NOT change CLI entry point in pyproject.toml
- DO NOT change env vars (`COPAW_*`)
- DO NOT change config paths (`~/.copaw`)
- DO NOT change branding text "CoPaw"
- DO NOT change GitHub URLs
- DO NOT change test file imports

## Task 1: pyproject.toml Distribution Name Rename

### What was done
- Changed 4 lines in pyproject.toml: lines 2, 66, 70, 77
- Changed only package distribution references (`name = "..."` and optional-dependency references)
- Preserved ALL module references (copaw namespace stays internal)

### Key insight
The rename is **distribution-name-only** — what users `pip install` as changes, but the internal package structure (imports, CLI entry points, etc.) remains `copaw`. This is critical because:
- Users will `pip install boostclaw`
- Developers still `import copaw` and `from copaw.cli import main`
- Lines 33, 41, 53 deliberately left unchanged

### Pattern: Distinguishing distribution vs. module names
- **Distribution name**: What appears in `pyproject.toml` `[project]` section and what `pip` knows
- **Module name**: What Python code imports; lives in `src/` directory structure
- When renaming distributions, always verify you're NOT changing module/import references

### Verification checklist passed
- ✅ Distribution name on line 2: `boostclaw`
- ✅ Optional deps on lines 66, 70, 77: `boostclaw[...]`
- ✅ Module reference line 33: `copaw.__version__` (untouched)
- ✅ Package-data line 41: `"copaw"` (untouched)
- ✅ CLI entry line 53: `copaw.cli.main:cli` (untouched)

## Task 2: Install Scripts Package Variable Rename

**Date:** 2026-03-13

### Changes Made
- Updated PACKAGE variable references in 3 install scripts (sh, ps1, bat)
- Changed from `copaw` to `boostclaw` for PyPI package references only
- 6 total line changes:
  - `scripts/install.sh`: Lines 234, 236
  - `scripts/install.ps1`: Lines 314, 315  
  - `scripts/install.bat`: Lines 423, 436

### Key Principle Applied
**Surgical precision**: Changed ONLY the PACKAGE variables, preserving all CLI command references (`copaw init`, `copaw app`) and config paths (`~/.copaw`). The CLI entry point name remains `copaw` per user decision.

### Verification Strategy
1. Checked surrounding context (lines ±5) before editing
2. Verified exact line/hash tags before applying edits
3. Used grep to confirm all 6 changes applied correctly
4. Validated CLI references remain unchanged
5. Confirmed no branding text "CoPaw" was affected

### Evidence Generated
- `.sisyphus/evidence/task-2-install-scripts.txt` - PACKAGE variable changes
- `.sisyphus/evidence/task-2-cli-refs-preserved.txt` - CLI command preservation

### Lessons for Future Tasks
1. For multi-file refactoring: read context around target lines first
2. When renaming package references: preserve CLI/command references
3. Use grep to verify before/after state for confidence
4. Surgical edits (changing only what's specified) reduce risk of unintended changes

## Task 4: Sidebar.tsx package rename update

**Pattern**: Multi-language instruction strings in frontend code
- PyPI URL and package name in pip install commands scattered across localized strings
- Chinese (zh), Russian (ru), English (en) variants all require identical updates
- Search strategy: grep for `pypi/` and `pip install` to catch all variants

**Lesson**: When renaming packages in i18n contexts:
1. Always search for package name in quoted strings, not just variable assignments
2. Verify all language variants (zh, ru, en) are updated
3. Keep branding (CoPaw) separate from package name (boostclaw) — they're different concepts
4. Frontend URLs depend on PyPI: ensure PyPI package exists BEFORE updating frontend

**Files touched**: console/src/layouts/Sidebar.tsx (4 lines)
- Line 45: PyPI URL constant
- Lines 81, 110, 139: pip install commands (Chinese, Russian, English respectively)

## Task 5: Build/Pack Scripts Update

**Completed**: Changed wheel glob patterns and archive names from `copaw` to `boostclaw`.

**Files Modified**:
- `scripts/pack/build_common.py`: Lines 54, 149
- `scripts/pack/build_win.ps1`: Line 10
- `scripts/pack/build_macos.sh`: Line 10

**Key Pattern Discovered**:
- Archive names (`copaw-env.tar.gz`, `copaw-env.zip`) are user-visible distribution artifacts
- Wheel glob patterns must match output from `python -m build` (which now produces `boostclaw-*.whl` after pyproject.toml rename)
- Install reference uses the wheel glob pattern for pip install
- Module path references (`src/copaw/`) were preserved unchanged (internal implementation detail, not part of renaming scope)
- Comments and old wheel cleanup logic (lines 92, 42) reference `copaw` but are outside scope of task's 4 specified line changes

**QA Result**: All 4 target lines successfully changed. No copaw artifact patterns in the 4 specified lines. Module paths intact.

## Task 3: Update pip install error messages

### What was done
- Changed 11 user-facing pip install strings across 8 Python files
- Pattern: `pip install 'copaw[...]'` → `pip install 'boostclaw[...]'`
- Only error/hint messages were updated; no imports, module names, or internal references changed

### Files modified (8 total, 11 line changes)
1. **src/copaw/cli/providers_cmd.py** (3 lines: 684, 736, 772) - `copaw[local]` → `boostclaw[local]`
2. **src/copaw/local_models/manager.py** (1 line: 135) - `copaw[local]` → `boostclaw[local]`
3. **src/copaw/local_models/backends/llamacpp_backend.py** (1 line: 62) - `copaw[llamacpp]` → `boostclaw[llamacpp]`
4. **src/copaw/local_models/backends/mlx_backend.py** (1 line: 71) - `copaw[mlx]` → `boostclaw[mlx]`
5. **src/copaw/providers/ollama_provider.py** (1 line: 38) - `copaw[ollama]` → `boostclaw[ollama]`
6. **src/copaw/providers/ollama_manager.py** (1 line: 56) - `copaw[ollama]` → `boostclaw[ollama]`
7. **src/copaw/app/routers/local_models.py** (1 line: 139) - `copaw[local]` → `boostclaw[local]`
8. **src/copaw/app/routers/ollama_models.py** (2 lines: 173, 285) - `copaw[ollama]` → `boostclaw[ollama]`

### Verification results
- ✅ Old `copaw[...]` strings: 0 matches
- ✅ New `boostclaw[...]` strings: 11 matches (exact requirement)
- ✅ No `from boostclaw import` or `import boostclaw` introduced: 0 matches
- ✅ All `import copaw` statements preserved: imports untouched

### Key pattern: Error message strings as user-facing only
These pip install references live in `ImportError` and `HTTPException` messages. They're ONLY visible to users when optional dependencies are missing, directing them to install the correct distribution package name. The internal module structure (`import copaw`) stays unchanged — developers still import the copaw module, users still install the boostclaw distribution.

### Testing approach
Grep patterns were used to verify:
1. No regression: old strings completely gone
2. Completeness: all 11 required strings present
3. Guardrail: no new imports introduced that would break the module structure

## Task 6: README files (3 languages) pip install reference update

**Date:** 2026-03-13

### Changes Made
Updated all `pip install copaw` and `pip install 'copaw[...]'` references to `boostclaw` across 3 README files:
- README.md: 4 lines changed (line 102 + lines 342-344)
- README_zh.md: 4 lines changed (line 102 + lines 346-348)
- README_ja.md: 4 lines changed (line 102 + lines 342-344)

Total: 12 line updates across 3 multilingual files

### Key Principle Applied
**Surgical precision across multilingual content**: 
- Updated ONLY pip install package references
- Preserved ALL branding (CoPaw appears 45+ times)
- Preserved ALL CLI command references (copaw init/app/models/uninstall)
- Preserved ALL config path references (~/.copaw)
- Preserved ALL documentation URLs (copaw.agentscope.io)
- Preserved ALL Docker image references (agentscope/copaw)
- Preserved source install instructions (pip install -e .)

### Verification Strategy
1. Grep for stale references: `grep -rn 'pip install copaw' --include='*.md'` → 0 matches ✓
2. Grep for new references: `grep -rn 'pip install boostclaw' --include='*.md'` → 12 matches ✓
3. Branding check: grep for "CoPaw" → 45+ matches ✓
4. CLI preservation: grep for "copaw init/app" → 4-5+ matches per command ✓
5. Docker image: grep for "agentscope/copaw" → 6+ matches ✓

### Evidence Generated
- `.sisyphus/evidence/task-6-readme-pip-install.txt` - Scenario 1 verification
- `.sisyphus/evidence/task-6-readme-preserved.txt` - Scenario 2 verification

### Lessons for Future Tasks
1. **Multilingual consistency**: When updating same content across language variants, ensure consistency across all languages
2. **Pattern matching precision**: Use exact patterns (pip install copaw vs. pip install boostclaw) to avoid false positives
3. **Preservation mindset**: In READMEs, many "copaw" references are legitimate (branding, CLI, URLs) — only distribution package name changes
4. **Context verification**: Always verify surrounding context (before/after lines) to ensure no unintended replacements
5. **Evidence collection**: QA scenarios prove non-invasiveness — branding/CLI/URLs unchanged despite package name change

### Pattern Learned
README files often mix multiple categories of "copaw" references:
- **CHANGE**: pip install instructions (distribution name)
- **PRESERVE**: CoPaw brand name, CLI commands, documentation URLs, Docker images, GitHub URLs, badge URLs, config paths

## Task 7: Website Documentation pip install References Update

### Completion Summary
- **Task**: Update all pip install references from `copaw` to `boostclaw` in website documentation
- **Files Modified**: 12 markdown files under `website/public/docs/`
- **Changes**: Updated 24 occurrences of pip install instructions

### Files Changed
1. models.en.md (3 occurrences)
2. models.zh.md (3 occurrences)
3. cli.en.md (3 occurrences)
4. cli.zh.md (3 occurrences)
5. faq.en.md (1 occurrence)
6. faq.zh.md (1 occurrence)
7. quickstart.en.md (1 occurrence)
8. quickstart.zh.md (1 occurrence)
9. console.en.md (2 occurrences)
10. console.zh.md (3 occurrences)
11. comparison.en.md (1 occurrence)
12. comparison.zh.md (1 occurrence)

### Patterns Replaced
- `pip install copaw` → `pip install boostclaw`
- `pip install 'copaw[llamacpp]'` → `pip install 'boostclaw[llamacpp]'`
- `pip install 'copaw[mlx]'` → `pip install 'boostclaw[mlx]'`
- `pip install 'copaw[ollama]'` → `pip install 'boostclaw[ollama]'`

### QA Verification Results
✓ Zero old copaw references remain
✓ 12 files now contain boostclaw references
✓ CLI commands (`copaw init`, `copaw app`) preserved in 14+ files
✓ CoPaw branding ("CoPaw") preserved in 39+ files
✓ Config paths (`~/.copaw`) preserved
✓ Documentation URLs preserved

### Key Learning
- Website docs use both `.en.md` and `.zh.md` naming conventions for language variants
- Pip install instructions require careful replacement to preserve optional extras syntax (brackets)
- CLI command references and branding must remain unchanged during package rename
- All 24 pip install occurrences successfully updated across English and Chinese docs
