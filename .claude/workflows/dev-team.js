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

// ---- Phase 2-3: Code <-> Review loop ----
let lastReview = null
let codeReport = null
for (let round = 1; round <= MAX_ROUNDS; round++) {
  phase('Code')
  const fixNote = lastReview ? (lastReview.findings || []).join('\n- ') : ''
  codeReport = await runCode(`round${round}`, fixNote)

  phase('Review')
  lastReview = await agent(
    `Review the current working-tree change for this task. Inspect it with: git diff -- ${plan.files.map((f) => '"' + f + '"').join(' ')}  (and git status for new files).

TASK: ${TASK}
SURFACE: ${SURFACE}
${KB}
Apply your full checklist for this surface (backend: AgentScope/guardian correctness; frontend: window.QwenPaw.* contract, theme tokens, i18n, accessibility). Return your structured verdict.`,
    { label: `review:round${round}`, phase: 'Review', agentType: 'qwenpaw-reviewer', schema: REVIEW_SCHEMA }
  )

  if (lastReview && lastReview.verdict === 'APPROVE') break
  log(`Round ${round}: review = ${lastReview ? lastReview.verdict : 'null'} (${lastReview ? lastReview.blockers : '?'} blockers)`)
}

// ---- Phase 4: Test loop ----
const TEST_GUIDE = IS_FRONTEND
  ? 'Add focused vitest + @testing-library/react tests co-located under console/src/ mirroring the component; mock network/host SDK calls. Run only the affected tests from console/: `cd console && npm run test:run -- <path>`. Report real results.'
  : 'Add focused tests under tests/ mirroring the code; mock external/model calls; run only the affected test paths with .venv/Scripts/python.exe -m pytest ... -q. Report real results.'
  + (IS_MIXED ? ' For the frontend slice, also add vitest tests under console/src/ and run them with `cd console && npm run test:run -- <path>`.' : '')

phase('Test')
let test = null
for (let round = 1; round <= MAX_ROUNDS; round++) {
  test = await agent(
    `Write and run tests for this change.

TASK: ${TASK}
SURFACE: ${SURFACE}
FILES CHANGED: ${plan.files.join(', ')}
MISSING TESTS flagged by review: ${(lastReview && lastReview.missingTests || []).join(', ') || '(none flagged — choose sensible cases)'}

${KB}
${TEST_GUIDE}`,
    { label: `test:round${round}`, phase: 'Test', agentType: 'qwenpaw-tester', schema: TEST_SCHEMA }
  )
  if (!test || test.result === 'PASS') break

  // Tests failed -> one code fix pass, then retest.
  phase('Code')
  codeReport = await runCode(`testfix${round}`, 'Tests are FAILING: ' + (test.failures || []).join('; ') + '. Fix the implementation (not the tests, unless a test is genuinely wrong). Keep the change minimal.')
  phase('Test')
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
