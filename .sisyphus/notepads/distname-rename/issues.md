## Issues

> Problems, gotchas, and known issues discovered during execution.

---

### Pre-Execution Analysis

**Issue: Filename conventions in website docs**
- **Context**: Plan initially referenced `quickstart.md`, `models.md`, `intro.md`
- **Reality**: Files use `*.en.md` / `*.zh.md` naming convention
- **Impact**: Minor — task instructs grep of entire directory, so no blocker
- **Fix**: Plan updated with correct filename examples and note about convention
- **Status**: RESOLVED (plan corrected before execution)

### Known Patterns to Watch

**Many "copaw" occurrences per file**:
- READMEs have branding, CLI commands, Docker refs, GitHub URLs — only pip install lines change
- Install scripts have CLI command refs, config paths — only PACKAGE variable changes
- Python source has imports, module paths — only pip install string literals change

**Guardrail hotspots** (lines that must NOT change):
- `pyproject.toml` lines 33, 41, 53 (module refs, CLI entry point)
- All `import copaw` and `from copaw import` statements
- All `COPAW_*` environment variable names
- All `~/.copaw` config path references
- All branding text "CoPaw"
- All GitHub URLs (`agentscope-ai/CoPaw`)
- All Docker image references (`agentscope/copaw`)
