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
  source_sha: string | null;
  source_repository: string;
  artifact_sha256: string;
  complete: boolean;
  benchmarks: Benchmark[];
}
export interface Run {
  schema_version: 3;
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
    protocol_hash: string;
    parameters: Record<string, number | null>;
  }[];
  id: string;
  kind: "testing" | "official";
  evaluation_sha: string | null;
  source_repository: string;
  artifact_sha256: string;
  exchange_rate: { cny_per_usd: number; basis: "fixed" };
  date: string;
  workflow_url: string;
  records: RecordResult[];
  complete: boolean;
}
export interface History {
  schema_version: 3;
  runs: Run[];
}
export interface Row extends RecordResult {
  id: string;
  run: Run;
  score: number | null;
  cost: number | null;
  runtime: number | null;
  upperBound: boolean;
  coverage: string;
  failureRate: number | null;
}
export function harnessLogo(name: string): string | undefined {
  const files: Record<string, string> = {
    qwenpaw: "qwenpaw.png",
    codex: "codex.svg",
    claudecode: "claudecode.svg",
    deepseekharness: "deepseekharness.svg",
  };
  const file = files[name.toLowerCase().replace(/[^a-z]/g, "")];
  return file
    ? `${import.meta.env.BASE_URL}evaluation/logos/${file}`
    : undefined;
}
function weighted(
  run: Run,
  parts: Benchmark[],
  metric: string,
  field: "score" | "mean_model_cost_usd" | "mean_runtime_seconds",
): number | null {
  if (!parts.length || parts.some((p) => p[field] === null)) return null;
  if (metric.startsWith("benchmark:")) return parts[0][field];
  let result = 0;
  for (const [id, direction] of Object.entries(
    run.index_definition.directions,
  )) {
    if (metric !== "index" && metric !== `domain:${id}`) continue;
    let subtotal = 0;
    for (const [benchmark, weight] of Object.entries(direction.benchmarks)) {
      const part = parts.find((p) => p.benchmark === benchmark);
      if (!part || part[field] === null) return null;
      subtotal += part[field] * weight;
    }
    result += subtotal * (metric === "index" ? direction.weight : 1);
  }
  return result;
}
export function selectRows(runs: Run[], metric: string): Row[] {
  return runs.flatMap((run) =>
    run.records.map((record, i) => {
      const parts = record.benchmarks.filter(
        (part) =>
          metric === "index" ||
          metric === `benchmark:${part.benchmark}` ||
          part.domains.some((domain) => metric === `domain:${domain}`),
      );
      return {
        ...record,
        run,
        id: `${run.id}-${i}`,
        score: weighted(run, parts, metric, "score"),
        cost: weighted(run, parts, metric, "mean_model_cost_usd"),
        runtime: weighted(run, parts, metric, "mean_runtime_seconds"),
        failureRate: parts.some((p) => p.scored !== p.expected)
          ? null
          : parts.reduce((n, p) => n + p.failed, 0) /
            parts.reduce((n, p) => n + p.expected, 0),
        upperBound: parts.some((p) => p.cost_bases.upper_bound > 0),
        coverage: `${parts.filter((p) => p.scored === p.expected).length}/${
          parts.length
        }`,
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
