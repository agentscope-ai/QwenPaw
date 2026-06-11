export const meta = {
  name: 'dev-team',
  description: 'qwenpaw dev team: guardian-gated code -> review -> test, with fix loops',
  phases: [
    { title: 'Plan', detail: 'guardian reviews the task against the AgentScope v2 KB and approves files' },
    { title: 'Code', detail: 'qwenpaw-coder implements the change' },
    { title: 'Review', detail: 'qwenpaw-reviewer checks the diff (loops with Code)' },
    { title: 'Test', detail: 'qwenpaw-tester writes & runs pytest (loops with Code)' },
  ],
}

// args: { task: string, files?: string[], maxRounds?: number }  OR  a plain task string.
const cfg = typeof args === 'string' ? { task: args } : (args || {})
const TASK = cfg.task
const FILES = Array.isArray(cfg.files) ? cfg.files : []
const MAX_ROUNDS = Number.isInteger(cfg.maxRounds) ? cfg.maxRounds : 2

if (!TASK) {
  return { error: 'dev-team requires a task. Pass args: { task: "...", files?: [...], maxRounds?: 2 }' }
}

const KB = 'Sources of truth: docs/agentscope-v2/ (AgentScope v2 KB + _guardian-checklist.md), docs/qwenpaw/ (package docs), and existing src/qwenpaw/ patterns. AGENTSCOPE VERSION — VERIFY FIRST: the user reported updating to v2 (agentscope 2.x); do NOT assume it — run `.venv/Scripts/python.exe -c "import agentscope; print(agentscope.__version__)"` and check pyproject.toml, then use whatever is actually installed (last check: 1.0.20, pinned ==1.0.20). If 2.x the KB applies directly; if still 1.x prefer installed/existing usage and flag the mismatch.'

const PLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    approved: { type: 'boolean', description: 'true if the change is sound and approval was recorded' },
    plan: { type: 'string', description: 'the implementation plan' },
    files: { type: 'array', items: { type: 'string' }, description: 'files that will be changed and were approved' },
    concerns: { type: 'array', items: { type: 'string' } },
  },
  required: ['approved', 'plan', 'files'],
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

// ---- Phase 1: Plan + Guardian gate ----
phase('Plan')
const plan = await agent(
  `Act as the AgentScope guardian + tech lead for this qwenpaw change.

TASK: ${TASK}
${FILES.length ? 'Target files (hint): ' + FILES.join(', ') : 'Discover the right files yourself.'}

${KB}

Do:
1. Read the relevant docs/agentscope-v2/ file(s), docs/agentscope-v2/_guardian-checklist.md, and the relevant docs/qwenpaw/ doc. Grep src/qwenpaw/ for the existing pattern.
2. Decide if the task is sound and how to implement it. Identify the EXACT files to change.
3. If sound: record approval so the edit hook lets the coder through —
   run: python scripts/agentscope_guardian_approve.py "<file1>" "<file2>" ...
   for every file you expect to be edited (only those you reviewed and approve). Set approved=true.
   If NOT sound (uses a non-existent/deprecated API, missing requirement, unsafe): set approved=false and explain in concerns. Do not approve.
Return the plan, the approved files list, approved flag, and any concerns.`,
  { label: 'plan+guardian', phase: 'Plan', schema: PLAN_SCHEMA }
)

if (!plan || !plan.approved) {
  return { stopped: 'guardian rejected or could not approve', plan }
}

// ---- Phase 2-3: Code <-> Review loop ----
let lastReview = null
let codeReport = null
for (let round = 1; round <= MAX_ROUNDS; round++) {
  phase('Code')
  codeReport = await agent(
    `Implement this qwenpaw change.

TASK: ${TASK}
PLAN (from guardian): ${plan.plan}
APPROVED FILES: ${plan.files.join(', ')}
${lastReview ? 'FIX these review findings from the previous round:\n- ' + (lastReview.findings || []).join('\n- ') : ''}

${KB}
The approved files are already cleared with the guardian-approve script, so your Edit/Write on them will pass the hook. If you must touch an additional file, run python scripts/agentscope_guardian_approve.py "<file>" for it first. Implement the smallest correct change; match existing patterns; black/flake8 clean.`,
    { label: `code:round${round}`, phase: 'Code', agentType: 'qwenpaw-coder' }
  )

  phase('Review')
  lastReview = await agent(
    `Review the current working-tree change for this task. Inspect it with: git diff -- ${plan.files.map((f) => '"' + f + '"').join(' ')}  (and git status for new files).

TASK: ${TASK}
${KB}
Apply your full checklist. Return your structured verdict.`,
    { label: `review:round${round}`, phase: 'Review', agentType: 'qwenpaw-reviewer', schema: REVIEW_SCHEMA }
  )

  if (lastReview && lastReview.verdict === 'APPROVE') break
  log(`Round ${round}: review = ${lastReview ? lastReview.verdict : 'null'} (${lastReview ? lastReview.blockers : '?'} blockers)`)
}

// ---- Phase 4: Test loop ----
phase('Test')
let test = null
for (let round = 1; round <= MAX_ROUNDS; round++) {
  test = await agent(
    `Write and run pytest for this change.

TASK: ${TASK}
FILES CHANGED: ${plan.files.join(', ')}
MISSING TESTS flagged by review: ${(lastReview && lastReview.missingTests || []).join(', ') || '(none flagged — choose sensible cases)'}

${KB}
Add focused tests under tests/ mirroring the code; mock external/model calls; run only the affected test paths with .venv/Scripts/python.exe -m pytest ... -q. Report real results.`,
    { label: `test:round${round}`, phase: 'Test', agentType: 'qwenpaw-tester', schema: TEST_SCHEMA }
  )
  if (!test || test.result === 'PASS') break

  // Tests failed -> one coder fix pass, then retest.
  phase('Code')
  codeReport = await agent(
    `Tests are FAILING for this change. Fix the implementation (not the tests, unless a test is genuinely wrong).

TASK: ${TASK}
FAILURES: ${(test.failures || []).join('\n')}
${KB}
Edit the approved files (already guardian-cleared). Keep the change minimal.`,
    { label: `code:testfix${round}`, phase: 'Code', agentType: 'qwenpaw-coder' }
  )
  phase('Test')
}

return {
  task: TASK,
  approvedFiles: plan.files,
  plan: plan.plan,
  finalReview: lastReview,
  finalTest: test,
  lastCodeReport: codeReport,
  status: (lastReview && lastReview.verdict === 'APPROVE' && test && test.result === 'PASS') ? 'GREEN' : 'NEEDS_ATTENTION',
}
