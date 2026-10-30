export interface Benchmark {
  benchmark: string;
  name: string;
  judge: {
    kind: "programmatic" | "llm";
    model: string | null;
    scorer: string | null;
    official_model: string | null;
    prompt_revision: string | null;
    parity_note: string;
  };
  original_model_cost: { currency: "CNY" | "USD"; mean_amount: number } | null;
  mean_judge_cost_usd: number | null;
  original_judge_cost: { currency: "CNY" | "USD"; mean_amount: number } | null;
  domains: string[];
  failed: number;
  failures: Record<string, number>;
  expected: number;
  scored: number;
  score: number | null;
  mean_runtime_seconds: number | null;
  mean_model_cost_usd: number | null;
  cost_sources: Record<string, number>;
  cost_bases: Record<string, number>;
}
export interface RecordResult {
  trajectory_url?: string;
  provider?: string;
  model: string;
  harness: string;
  sdk_version: string;
  source_repository: string;
  complete: boolean;
  benchmarks: Benchmark[];
}
export interface Run {
  schema_version: 4;
  board: { id: string; name: string; group_by: "model" | "model_harness" };
  index_version: string;
  index_definition: {
    id: string;
    order: number;
    directions: Record<
      string,
      {
        name: string;
        weight: number;
        benchmarks: Record<string, number>;
      }
    >;
  };
  source_results: {
    id: string;
    date: string;
    benchmark: string;
    parameters: Record<string, number | null>;
  }[];
  id: string;
  kind: "testing" | "official";
  source_repository: string;
  exchange_rate: { cny_per_usd: number; basis: "fixed" };
  date: string;
  workflow_url: string;
  records: RecordResult[];
  complete: boolean;
}
export interface History {
  schema_version: 4;
  runs: Run[];
}
export interface Row extends RecordResult {
  id: string;
  run: Run;
  score: number | null;
  cost: number | null;
  runtime: number | null;
  upperBound: boolean;
  partialCost: boolean;
  costKnown: number;
  costTotal: number;
  coverage: string;
  failureRate: number | null;
}
export function harnessLogo(name: string): string | undefined {
  const files: Record<string, string> = {
    qwenpaw: "qwenpaw.png",
    qwenpawgoal: "qwenpaw.png",
    qwenpawcode: "qwenpaw.png",
    codex: "codex.svg",
    claudecode: "claudecode.svg",
    deepseekharness: "deepseekharness.svg",
  };
  const file = files[name.toLowerCase().replace(/[^a-z]/g, "")];
  return file
    ? `${import.meta.env.BASE_URL}evaluation/logos/${file}`
    : undefined;
}
export function harnessLabel(harness: string): string {
  const labels: Record<string, string> = {
    qwenpaw: "qwenpawDefault",
    "qwenpaw-goal": "qwenpawGoal",
    "qwenpaw-code": "qwenpawCode",
  };
  return labels[harness] ?? harness;
}
export type BenchmarkWeights = Record<string, number>;

export function defaultWeights(run?: Run): BenchmarkWeights {
  return Object.fromEntries(
    Object.values(run?.index_definition.directions ?? {}).flatMap((direction) =>
      Object.entries(direction.benchmarks).map(([id, weight]) => [
        id,
        weight * direction.weight,
      ]),
    ),
  );
}

export function normalizeWeights(weights: BenchmarkWeights): BenchmarkWeights {
  const selected = Object.entries(weights).filter(([, weight]) => weight > 0);
  const total = selected.reduce((sum, [, weight]) => sum + weight, 0);
  return Object.fromEntries(
    selected.map(([id, weight]) => [id, weight / total]),
  );
}

function weighted(
  parts: Benchmark[],
  weights: BenchmarkWeights,
  field: "score" | "mean_model_cost_usd" | "mean_runtime_seconds",
): number | null {
  const selected = Object.entries(weights);
  if (!selected.length) return null;
  let result = 0;
  for (const [id, weight] of selected) {
    const part = parts.find((part) => part.benchmark === id);
    if (!part || part[field] === null) return null;
    result += part[field] * weight;
  }
  return result;
}

export function selectRows(runs: Run[], weights?: BenchmarkWeights): Row[] {
  return runs.flatMap((run) =>
    run.records.map((record, i) => {
      const selected = normalizeWeights(weights ?? defaultWeights(run));
      const parts = record.benchmarks.filter(
        (part) => part.benchmark in selected,
      );
      const complete =
        Object.keys(selected).length > 0 &&
        Object.keys(selected).every((id) =>
          parts.some(
            (part) =>
              part.benchmark === id &&
              part.score !== null &&
              part.scored === part.expected,
          ),
        );
      return {
        ...record,
        run,
        id: `${run.id}-${i}`,
        complete,
        score: weighted(parts, selected, "score"),
        cost: weighted(parts, selected, "mean_model_cost_usd"),
        runtime: weighted(parts, selected, "mean_runtime_seconds"),
        failureRate: !complete
          ? null
          : parts.reduce((n, p) => n + p.failed, 0) /
            parts.reduce((n, p) => n + p.expected, 0),
        partialCost:
          !complete || parts.some((p) => (p.cost_sources.unknown ?? 0) > 0),
        costKnown: parts.reduce(
          (n, p) => n + p.expected - (p.cost_sources.unknown ?? 0),
          0,
        ),
        costTotal: parts.reduce((n, p) => n + p.expected, 0),
        upperBound: parts.some((p) => p.cost_bases.upper_bound > 0),
        coverage: `${
          parts.filter((p) => p.score !== null && p.scored === p.expected)
            .length
        }/${Object.keys(selected).length}`,
      };
    }),
  );
}
export function logo(model: string): string | undefined {
  const provider = model.toLowerCase().startsWith("qwen")
    ? "qwen"
    : model.toLowerCase().startsWith("deepseek")
    ? "deepseek"
    : model.toLowerCase().startsWith("glm")
    ? "zai"
    : undefined;
  if (!provider) return undefined;
  return `${import.meta.env.BASE_URL}evaluation/logos/${provider}.svg`;
}
export function money(
  cost: number | null,
  locale: string,
  unknown: string,
): string {
  return cost === null
    ? unknown
    : new Intl.NumberFormat(locale, {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: cost < 0.01 ? 4 : 3,
        maximumFractionDigits: cost < 0.01 ? 4 : 3,
      }).format(cost);
}
export function safeWorkflow(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
      ? value
      : undefined;
  } catch {
    return undefined;
  }
}
