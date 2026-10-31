// Leaderboard policy lives here, never in the evaluation runner.
export function check(condition, message) {
  if (!condition) throw new Error(message);
}

export function validateDefinition(definition) {
  check(definition.id && definition.directions, "Missing index definition");
  const assigned = [];
  let total = 0;
  for (const direction of Object.values(definition.directions)) {
    check(
      Number.isFinite(direction.weight) && direction.weight > 0,
      "Invalid direction weight",
    );
    total += direction.weight;
    let subtotal = 0;
    for (const [benchmark, weight] of Object.entries(direction.benchmarks)) {
      check(definition.benchmarks[benchmark], "Unknown benchmark in direction");
      check(Number.isFinite(weight) && weight > 0, "Invalid benchmark weight");
      assigned.push(benchmark);
      subtotal += weight;
    }
    check(Math.abs(subtotal - 1) < 1e-9, "Benchmark weights must sum to one");
  }
  check(Math.abs(total - 1) < 1e-9, "Direction weights must sum to one");
  check(
    new Set(assigned).size === assigned.length &&
      assigned.length === Object.keys(definition.benchmarks).length,
    "Assign each benchmark to exactly one direction",
  );
}

export function summarize(input, benchmark, direction, rate) {
  if (!input)
    return {
      benchmark,
      name: benchmark,
      judge: null,
      domains: [direction],
      expected: 0,
      scored: 0,
      score: null,
      mean_runtime_seconds: null,
      mean_model_cost_usd: null,
      original_model_cost: null,
      mean_judge_cost_usd: null,
      original_judge_cost: null,
      cost_sources: { unknown: 0 },
      cost_bases: { unknown: 0 },
      failures: {},
      failed: 0,
    };
  const b = input;
  const summary = b.summary;
  const failed = Object.values(summary.failures).reduce((a, b) => a + b, 0);
  check(failed <= b.expected, "Failure count exceeds expected tasks");
  check(summary.score_sum <= b.expected, "Score sum exceeds task count");
  for (const role of ["model", "judge"]) {
    const count = summary[`${role}_cost_count`];
    const value = summary[`${role}_cost`];
    check(
      count <= b.expected && (count === 0) === (value === null),
      "Invalid cost coverage",
    );
  }
  check(
    summary.runtime_count <= b.expected &&
      (summary.runtime_count !== 0 || summary.runtime_seconds_sum === 0),
    "Invalid runtime coverage",
  );
  const original = (role) => {
    const value = summary[`${role}_cost`];
    return value === null
      ? null
      : {
          currency: value.currency,
          mean_amount: value.amount / b.expected,
        };
  };
  const usd = (role) => {
    const value = original(role);
    return value === null
      ? null
      : value.mean_amount / (value.currency === "CNY" ? rate.cny_per_usd : 1);
  };
  return {
    benchmark,
    name: b.name,
    judge: b.judge,
    domains: [direction],
    expected: b.expected,
    scored: b.expected,
    score: (summary.score_sum / b.expected) * 100,
    mean_runtime_seconds: summary.runtime_count
      ? summary.runtime_seconds_sum / summary.runtime_count
      : null,
    mean_model_cost_usd: usd("model"),
    original_model_cost: original("model"),
    mean_judge_cost_usd: usd("judge"),
    original_judge_cost: original("judge"),
    cost_sources: {
      snapshot_estimated: summary.model_cost_count,
      unknown: b.expected - summary.model_cost_count,
    },
    cost_bases: {
      exact: summary.model_cost_count,
      unknown: b.expected - summary.model_cost_count,
    },
    failures: summary.failures,
    failed,
  };
}
