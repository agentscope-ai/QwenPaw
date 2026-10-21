// `loop.iteration.max_iterations` mirrors the legacy `AgentsRunningConfig.max_iters`
// in the UI, but only the gate field is bounded by the schema. Sharing the bounds
// keeps the seeded value, the input constraints and the submitted payload in
// agreement: a number the schema rejects fails the whole PUT, so the Run Config
// page could not save any of its other sections either.
export const ITERATION_LIMIT_MIN = 1;
export const ITERATION_LIMIT_MAX = 500;

/** Return the value when it is a usable iteration limit, otherwise null. */
export function normalizeIterationLimit(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= ITERATION_LIMIT_MIN &&
    value <= ITERATION_LIMIT_MAX
    ? value
    : null;
}
