# Cron Invalid Schedule Handling Proposal

## Scope

- Upstream target: agentscope-ai/CoPaw main
- Local fork impact: keep in sync after upstream discussion/merge

This proposal addresses a startup stability gap: invalid cron expressions in persisted jobs should not fail app startup.

## Problem Statement

When a persisted cron job contains an expression that passes basic shape checks (5 fields) but fails APScheduler semantic validation, app startup can fail during cron registration.

Example:
- cron: 0 */30 8-18 * 1-5
- failure: step value 30 exceeds hour range 0-23

Observed effect:
- app fails in lifespan startup
- noisy secondary shutdown errors may appear from other async subsystems

## Why This Matters

- Reliability: one bad job should not block all services.
- Operability: users need clear visibility of invalid jobs and easy recovery.
- Roadmap alignment: fits self-healing/daemon direction.

## Proposed Design

### 1) Startup resilience (task-level)

At startup, register cron jobs one by one:
- if valid: schedule normally
- if invalid: skip scheduling that job, set runtime state to error, keep app startup successful

Status shape (existing model can be reused):
- last_status = error
- last_error = invalid schedule: <validation message>
- next_run_at = null

### 2) Validation on create/update

Add semantic validation before persistence for all write paths:
- API create/replace cron job
- CLI cron create (and any edit/replace command path)
- Console form submit path (server-side is authoritative)

Validation rule:
- build APScheduler trigger with provided cron/timezone
- if trigger build fails, reject request with clear 4xx error and actionable message

### 3) Recovery UX

Expose invalid jobs clearly in list/state views:
- display error status and message
- provide edit/resave flow to fix and reactivate

No auto-rewrite of expressions in backend.

## Non-Goals

- Automatic transformation of invalid cron expressions
- Backfilling complex migration for historical job data beyond state marking

## Compatibility

- Backward compatible for valid jobs
- Invalid historical jobs no longer crash startup
- Existing storage format remains usable

## Acceptance Criteria

1. App starts successfully even when persisted jobs include invalid cron entries.
2. Invalid jobs are marked error and omitted from scheduler registration.
3. Creating/replacing a job with invalid cron returns a clear validation error.
4. Unit tests cover:
- startup skip invalid + keep valid jobs
- API/CLI write-path validation failures
5. Integration startup test passes with mixed valid/invalid jobs.

## Risks and Mitigations

- Risk: users do not notice skipped jobs
- Mitigation: explicit warning log + error state surfaced in API/Console

- Risk: validation behavior differs across entry points
- Mitigation: centralize validation helper used by manager/API/CLI

## Suggested Upstream Issue Draft

Title:
- Bug: Invalid persisted cron schedule can fail app startup; should degrade to per-job error

Body:
- Background:
  - Persisted cron jobs are loaded on startup.
  - Certain expressions pass field-count checks but fail APScheduler semantic validation.
- Repro:
  1. Persist a cron job with expression like 0 */30 8-18 * 1-5
  2. Start app
  3. Observe startup failure in lifespan during cron registration
- Actual:
  - Startup fails; service unavailable.
- Expected:
  - Startup succeeds.
  - Invalid job is skipped and marked error.
  - Create/update paths reject invalid cron with clear message.
- Proposed fix:
  - Startup task-level fault isolation + write-path semantic validation + invalid state visibility.
- Acceptance criteria:
  - (copy from the section above)

## Ownership Split

- Upstream:
  - Cron startup fault isolation
  - Create/update semantic validation
  - Test coverage
- Local/Fork:
  - Temporary operational guidance and migration notes if needed
  - Optional local alerting conventions
