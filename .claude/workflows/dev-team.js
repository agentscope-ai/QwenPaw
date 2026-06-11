export const meta = {
  name: 'dev-team',
  description: 'qwenpaw dev team: surface-aware (backend/frontend) plan -> code -> review -> test, with fix loops',
  phases: [
    { title: 'Plan', detail: 'guardian/lead classifies surface, plans, and approves backend files' },
    { title: 'Code', detail: 'qwenpaw-coder (backend) or qwenpaw-frontend-designer (UI/UX) implements the change' },
    { title: 'Review', detail: 'qwenpaw-reviewer checks the diff (loops with Code)' },
    { title: 'Test', detail: 'qwenpaw-tester runs pytest (backend) or vitest (frontend) (loops with Code)' },
  ],
}

// Per-role permission contract (modeled on AgentScope's Permission System —
// docs/agentscope-v2/building-blocks/permission-system.md). These are Claude Code
// subagents, so the boundary is enforced via each agent's `tools:` frontmatter
// (not a Python PermissionContext), but the intent maps to PermissionMode:
//   - plan/guardian : DEFAULT  — explores read-only, but DOES mutate state (runs the
//                                guardian-approve script + git); needs Bash. Not EXPLORE.
//   - qwenpaw-reviewer : EXPLORE — read-only; Write/Edit withheld in its frontmatter.
//   - qwenpaw-coder / frontend-designer : ACCEPT_EDITS-equivalent — may edit approved files.
//   - qwenpaw-tester : may Write/run tests (records guardian approval for agentscope-importing
//                      test files first); not read-only.
// Only the reviewer is a true read-only (EXPLORE) role; the prompt below restates that.

// args: { task: string, files?: string[], maxRounds?: number, surface?: 'backend'|'frontend'|'mixed'|'auto' }
//   OR  a plain task string.
const cfg = typeof args === 'string' ? { task: args } : (args || {})
const TASK = cfg.task
const FILES = Array.isArray(cfg.files) ? cfg.files : []
const MAX_ROUNDS = Number.isInteger(cfg.maxRounds) ? cfg.maxRounds : 2
const SURFACE_HINT = ['backend', 'frontend', 'mixed'].includes(cfg.surface) ? cfg.surface : 'auto'

if (!TASK) {
  return { error: 'dev-team requires a task. Pass args: { task: "...", files?: [...], maxRounds?: 2, surface?: "backend|frontend|mixed|auto" }' }
}

const KB_BACKEND = 'BACKEND sources of truth: docs/agentscope-v2/ (AgentScope v2 KB + _guardian-checklist.md) and existing src/qwenpaw/ patterns. AGENTSCOPE VERSION: the fork is on agentscope 2.x — verified 2.0.0 on 2026-06-11 (pinned ==2.0.0 in pyproject.toml). Still confirm with `.venv/Scripts/python.exe -c "import agentscope; print(agentscope.__version__)"` before relying on an API; since it is 2.x, docs/agentscope-v2/ applies directly and any 1.x-only pattern is legacy — flag any divergence. (There is no docs/qwenpaw/ directory.)'

const KB_FRONTEND = 'FRONTEND (Console) sources of truth: website/public/docs/plugins.en.md (plugin system, incl. frontend window.QwenPaw.* contract), console/src/plugins/types/qwenpaw.d.ts (host SDK types), and existing console/src/ patterns. Stack: React 18 + TS + Ant Design 5 + .module.less CSS modules; theme via console/src/contexts/ThemeContext.tsx (light/dark); i18n via react-i18next with locales en/id/ja/pt-BR/ru/zh; zustand stores; react-router-dom v7; tests with vitest + @testing-library/react. Frontend is NOT AgentScope and is NOT subject to the agentscope-guardian gate — do NOT run the guardian-approve script for console/ files.'

const PLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    approved: { type: 'boolean', description: 'true if the change is sound (and, for backend files, approval was recorded)' },
    surface: { type: 'string', enum: ['backend', 'frontend', 'mixed'], description: 'which codebase the change touches' },
    plan: { type: 'string', description: 'the implementation plan' },
    files: { type: 'array', items: { type: 'string' }, description: 'files that will be changed' },
    concerns: { type: 'array', items: { type: 'string' } },
  },
  required: ['approved', 'surface', 'plan', 'files'],
}
const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['APPROVE', 'REQUEST_CHANGES'] },
    blockers: { type: 'integer' }, majors: { type: 'integer' },
    findings: { type: 'array', items: { type: 'string' } },
    missingTests: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'findings'],
}
const TEST_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    result: { type: 'string', enum: ['PASS', 'FAIL'] },
    summary: { type: 'string' },
    testsAdded: { type: 'array', items: { type: 'string' } },
    failures: { type: 'array', items: { type: 'string' } },
  },
  required: ['result', 'summary'],
}

// ---- Phase 1: Plan + (backend) guardian gate ----
phase('Plan')
const plan = await agent(
  `Act as the tech lead (and AgentScope guardian for backend) for this qwenpaw change.

TASK: ${TASK}
${FILES.length ? 'Target files (hint): ' + FILES.join(', ') : 'Discover the right files yourself.'}
SURFACE HINT: ${SURFACE_HINT}

${KB_BACKEND}

${KB_FRONTEND}

Do:
1. CLASSIFY the surface: "backend" (src/qwenpaw/** Python / AgentScope), "frontend" (console/** TypeScript/React UI), or "mixed". Respect the surface hint if given and consistent.
2. Read the relevant sources for that surface (for backend: docs/agentscope-v2/ + _guardian-checklist.md + grep src/qwenpaw/; for frontend: website/public/docs/plugins.en.md, console/src/plugins/types/qwenpaw.d.ts + grep console/src/). Decide how to implement it and identify the EXACT files to change.
3. GATE (backend files only): for every src/qwenpaw/** or agentscope-importing .py file you expect to be edited, record approval —
   run: python scripts/agentscope_guardian_approve.py "<file1>" "<file2>" ...
   Do NOT run the approve script for console/** (frontend) files — they are not gated.
   If the change is sound, set approved=true. If NOT sound (backend uses a non-existent/deprecated API, missing requirement, unsafe; or frontend introduces a new framework / breaks the window.QwenPaw.* contract): set approved=false and explain in concerns.
Return: surface, the plan, the files list, approved flag, and any concerns.`,
  { label: 'plan+guardian', phase: 'Plan', schema: PLAN_SCHEMA }
)

if (!plan || !plan.approved) {
  return { stopped: 'plan rejected or could not approve', plan }
}

const SURFACE = plan.surface || (SURFACE_HINT === 'auto' ? 'backend' : SURFACE_HINT)
const IS_FRONTEND = SURFACE === 'frontend'
const IS_MIXED = SURFACE === 'mixed'
const KB = IS_FRONTEND ? KB_FRONTEND : (IS_MIXED ? KB_BACKEND + '\n\n' + KB_FRONTEND : KB_BACKEND)

// Split files by surface for routing.
const isFrontendFile = (f) => /(^|[\\/])console[\\/]/.test(f)
const backendFiles = plan.files.filter((f) => !isFrontendFile(f))
const frontendFiles = plan.files.filter(isFrontendFile)

// Pick the implementation agent(s) for the Code phase.
async function runCode(roundLabel, fixNote) {
  // Frontend (or the frontend slice of a mixed change) -> the UI/UX designer.
  if (IS_FRONTEND || (IS_MIXED && frontendFiles.length)) {
    const feFiles = IS_MIXED ? frontendFiles : plan.files
    var feReport = await agent(
      `Implement the UI/UX part of this qwenpaw Console change.

TASK: ${TASK}
PLAN (from lead): ${plan.plan}
FRONTEND FILES: ${feFiles.join(', ')}
${fixNote ? 'FIX these review/test findings:\n- ' + fixNote : ''}

${KB_FRONTEND}
Match existing console/src/ patterns: antd components + .module.less, theme-safe tokens (works in light AND dark), all user-facing text via react-i18next across locales (at least en/zh/pt-BR), accessible and responsive. Verify visually (cd console && npm run dev) before declaring done. No guardian approval needed for console/ files.`,
      { label: `design:${roundLabel}`, phase: 'Code', agentType: 'qwenpaw-frontend-designer' }
    )
  }
  // Backend (or the backend slice of a mixed change) -> the coder.
  if (!IS_FRONTEND || (IS_MIXED && backendFiles.length)) {
    const beFiles = IS_MIXED ? backendFiles : plan.files
    var beReport = await agent(
      `Implement the backend part of this qwenpaw change.

TASK: ${TASK}
PLAN (from guardian): ${plan.plan}
APPROVED FILES: ${beFiles.join(', ')}
${fixNote ? 'FIX these review/test findings:\n- ' + fixNote : ''}

${KB_BACKEND}
The approved files are already cleared with the guardian-approve script, so your Edit/Write on them will pass the hook. If you must touch an additional backend file, run python scripts/agentscope_guardian_approve.py "<file>" for it first. Implement the smallest correct change; match existing patterns; black/flake8 clean.`,
      { label: `code:${roundLabel}`, phase: 'Code', agentType: 'qwenpaw-coder' }
    )
  }
  return [feReport, beReport].filter(Boolean).join('\n\n---\n\n') || null
}

// ---- Phases 2-4: explicit Code -> Review -> Test state graph (LangGraph-style) ----
// A single cyclic state machine replaces the former two separate loops. Key gain over
// the old code: a fix prompted by a TEST failure now loops back through REVIEW before
// re-testing (the old test loop applied a code fix and re-tested WITHOUT re-reviewing,
// so a "make the test pass" change could ship unreviewed). States and transitions:
//   CODE   -> REVIEW
//   REVIEW -> TEST            (verdict APPROVE)
//          -> CODE            (REQUEST_CHANGES, budget left)  [carries findings as fixNote]
//          -> TEST            (REQUEST_CHANGES, budget exhausted — still test once to report)
//   TEST   -> DONE            (PASS)
//          -> CODE            (FAIL, budget left)             [carries failures as fixNote]
//          -> STUCK           (FAIL, budget exhausted)
// A single global budget (MAX_ROUNDS *code* iterations) bounds the whole cycle; exhausting
// it lands NEEDS_ATTENTION. `round` increments only on CODE, so the graph always terminates.
const TEST_GUIDE = IS_FRONTEND
  ? 'Add focused vitest + @testing-library/react tests co-located under console/src/ mirroring the component; mock network/host SDK calls. Run only the affected tests from console/: `cd console && npm run test:run -- <path>`. Report real results.'
  : 'Add focused tests under tests/ mirroring the code; mock external/model calls; run only the affected test paths with .venv/Scripts/python.exe -m pytest ... -q. Report real results.'
  + (IS_MIXED ? ' For the frontend slice, also add vitest tests under console/src/ and run them with `cd console && npm run test:run -- <path>`.' : '')

let lastReview = null
let test = null
let codeReport = null

async function runReview(round) {
  return await agent(
    `Review the current working-tree change for this task. Inspect it with: git diff -- ${plan.files.map((f) => '"' + f + '"').join(' ')}  (and git status for new files).

You are READ-ONLY (AgentScope PermissionMode.EXPLORE-equivalent): inspect with read-only commands only (git diff/status, grep/rg, version checks) and do NOT modify, stage, commit, or write any file. Produce findings; the coder fixes them.

TASK: ${TASK}
SURFACE: ${SURFACE}
${KB}
Apply your full checklist for this surface (backend: AgentScope/guardian correctness; frontend: window.QwenPaw.* contract, theme tokens, i18n, accessibility). Return your structured verdict.`,
    { label: `review:round${round}`, phase: 'Review', agentType: 'qwenpaw-reviewer', schema: REVIEW_SCHEMA }
  )
}

async function runTest(round) {
  return await agent(
    `Write and run tests for this change.

TASK: ${TASK}
SURFACE: ${SURFACE}
FILES CHANGED: ${plan.files.join(', ')}
MISSING TESTS flagged by review: ${(lastReview && lastReview.missingTests || []).join(', ') || '(none flagged — choose sensible cases)'}

${KB}
${TEST_GUIDE}`,
    { label: `test:round${round}`, phase: 'Test', agentType: 'qwenpaw-tester', schema: TEST_SCHEMA }
  )
}

let state = 'CODE'
let round = 0
let fixNote = ''
while (state !== 'DONE' && state !== 'STUCK') {
  if (state === 'CODE') {
    round++
    phase('Code')
    codeReport = await runCode(`round${round}`, fixNote)
    fixNote = ''
    state = 'REVIEW'
  } else if (state === 'REVIEW') {
    phase('Review')
    lastReview = await runReview(round)
    if (lastReview && lastReview.verdict === 'APPROVE') {
      state = 'TEST'
    } else {
      log(`Round ${round}: review = ${lastReview ? lastReview.verdict : 'null'} (${lastReview ? lastReview.blockers : '?'} blockers)`)
      if (round >= MAX_ROUNDS) {
        state = 'TEST' // code budget spent on review fixes; run tests once so the report is complete
      } else {
        fixNote = (lastReview && lastReview.findings || []).join('\n- ')
        state = 'CODE'
      }
    }
  } else { // state === 'TEST'
    phase('Test')
    test = await runTest(round)
    if (!test || test.result === 'PASS') {
      state = 'DONE'
    } else if (round >= MAX_ROUNDS) {
      log(`Round ${round}: tests FAIL and code budget exhausted`)
      state = 'STUCK'
    } else {
      fixNote = 'Tests are FAILING: ' + (test.failures || []).join('; ') + '. Fix the implementation (not the tests, unless a test is genuinely wrong). Keep the change minimal.'
      state = 'CODE' // a test-driven fix loops back through REVIEW too (the key improvement)
    }
  }
}

return {
  task: TASK,
  surface: SURFACE,
  approvedFiles: plan.files,
  plan: plan.plan,
  finalReview: lastReview,
  finalTest: test,
  lastCodeReport: codeReport,
  status: (lastReview && lastReview.verdict === 'APPROVE' && test && test.result === 'PASS') ? 'GREEN' : 'NEEDS_ATTENTION',
}
