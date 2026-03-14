## Decisions

> Architectural choices and trade-offs made during execution.

---

### Metis Gap Analysis Decisions

**Decision 1: Python source error messages**
- **Context**: User-facing `pip install 'copaw[...]'` strings in exception messages
- **Decision**: CHANGE to `boostclaw[...]`
- **Rationale**: Users need correct install commands after package rename

**Decision 2: Console frontend PyPI URL**
- **Context**: `pypi.org/pypi/copaw/json` API endpoint for version checks
- **Decision**: CHANGE to `pypi.org/pypi/boostclaw/json`
- **Rationale**: Would 404 after package rename, breaking version check feature

**Decision 3: Docker image name**
- **Context**: `agentscope/copaw` image name in docs and deploy scripts
- **Decision**: SKIP for now (user explicit choice)
- **Rationale**: User chose to defer Docker rename to future work

**Decision 4: Archive names**
- **Context**: `copaw-env.zip` / `copaw-env.tar.gz` distribution archives
- **Decision**: CHANGE to `boostclaw-env.*`
- **Rationale**: User explicit choice — archive names are user-visible artifacts

### Execution Strategy Decisions

**Parallel Wave 1**:
- All 7 implementation tasks are independent (different files, no conflicts)
- Can run simultaneously for ~80% speedup vs sequential

**Sequential Wave 2**:
- Build verification depends on ALL Wave 1 changes
- Must wait for complete set before verifying

**Parallel Wave FINAL**:
- 4 review agents can run simultaneously (independent review types)
