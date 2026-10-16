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

function mean(values) {
  return values.some((v) => v === null)
    ? null
    : values.reduce((a, b) => a + b, 0) / values.length;
}

function cost(trials, role, rate) {
  const values = trials.map((t) =>
    role === "judge" && !t.judge_called
      ? { amount: 0, currency: "USD" }
      : t[role === "judge" ? "judge_cost" : "cost"],
  );
  if (values.some((v) => v === null)) return { usd: null, original: null };
  const nonzero = values.filter((v) => v.amount !== 0);
  const currencies = new Set(nonzero.map((v) => v.currency));
  check(currencies.size <= 1, "Mixed original currencies within a benchmark");
  const currency = nonzero[0]?.currency ?? values[0].currency;
  const amount = values.reduce((n, v) => n + v.amount, 0) / trials.length;
  return {
    usd: amount / (currency === "CNY" ? rate : 1),
    original: { currency, mean_amount: amount },
  };
}

export function summarize(input, benchmark, direction) {
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
  const b = input.benchmark;
  const expected = new Set(
    b.instances.flatMap((instance) =>
      Array.from({ length: b.repetitions }, (_, repeat) =>
        JSON.stringify([instance, repeat]),
      ),
    ),
  );
  const observed = input.trials.map((t) =>
    JSON.stringify([t.instance, t.repeat]),
  );
  check(
    expected.size === b.expected &&
      observed.length === b.expected &&
      new Set(observed).size === b.expected &&
      observed.every((k) => expected.has(k)),
    `${input.id}: incomplete or duplicate task identities`,
  );
  const failures = {};
  for (const t of input.trials)
    if (t.status !== "passed")
      failures[t.status] = (failures[t.status] ?? 0) + 1;
  const model = cost(input.trials, "model", input.exchange_rate.cny_per_usd);
  const judge = cost(input.trials, "judge", input.exchange_rate.cny_per_usd);
  return {
    benchmark,
    name: b.name,
    judge: b.judge,
    domains: [direction],
    expected: b.expected,
    scored: input.trials.length,
    score: mean(
      input.trials.map((t) => (t.status === "passed" ? t.score * 100 : 0)),
    ),
    mean_runtime_seconds: mean(input.trials.map((t) => t.runtime_seconds)),
    mean_model_cost_usd: model.usd,
    original_model_cost: model.original,
    mean_judge_cost_usd: judge.usd,
    original_judge_cost: judge.original,
    cost_sources: {
      [model.usd === null ? "unknown" : "snapshot_estimated"]: b.expected,
    },
    cost_bases: { [model.usd === null ? "unknown" : "exact"]: b.expected },
    failures,
    failed: Object.values(failures).reduce((a, b) => a + b, 0),
  };
}
