import type { History, Run } from "./types";

const models = [
  "qwen3.8-max-0902",
  "qwen3.8-27b",
  "deepseek-v4-pro-0813",
  "deepseek-v4.1-flash",
  "glm-5.3",
  "glm-5.2",
];
const names = ["gaia", "spreadsheetbench-verified", "swebench-verified"];
const domains = ["research", "office", "coding"];
const counts = [165, 400, 500];
export function demoHistory(privateView: boolean): History {
  const harnesses = privateView
    ? ["QwenPaw", "Codex", "Claude Code", "DeepSeek Harness"]
    : ["QwenPaw"];
  const runs: Run[] = [0, 1, 2].map((version) => {
    const records = harnesses.flatMap((harness, h) =>
      models.map((model, m) => {
        const parts = names.map((benchmark, b) => ({
          benchmark,
          domains: [domains[b]],
          expected: counts[b],
          scored: counts[b],
          score: Math.min(
            96,
            61 +
              (5 - m) * 3 +
              version * 2.4 +
              Math.sin(m + b + h) * 6 -
              h * 1.7,
          ),
          mean_model_cost_usd:
            m === 5 && version === 0
              ? null
              : Number(
                  (
                    (m === 1 ? 0.07 : 0.9 / (m + 1)) *
                    (1 + b * 0.3 + h * 0.18) *
                    (1 - version * 0.08)
                  ).toFixed(4),
                ),
          mean_runtime_seconds: 160 + m * 47 + b * 110 - version * 13,
          cost_sources: { litellm_estimated: counts[b] },
          cost_bases: { list_price: counts[b] },
          cost_observed_attempts: counts[b],
          cost_known_attempts: m === 5 && version === 0 ? 0 : counts[b],
        }));
        return {
          model,
          harness,
          sdk_version: `2.${version}.0-demo`,
          source_sha: "demo",
          complete: true,
          index_score: null,
          index_model_cost_usd: null,
          index_runtime_seconds: null,
          observed_model_spend_usd: null,
          attempts_with_known_cost: 1065,
          observed_attempts: 1065,
          cost_status: "mock",
          domains: {},
          benchmarks: parts,
        };
      }),
    );
    return {
      schema_version: 1,
      visibility: privateView ? "private" : "public",
      index_version: "index-v1",
      manifest_sha256: `demo-${version}`,
      evaluation_sha: "demo",
      date: `2026-0${7 + version}-08T00:00:00Z`,
      workflow_url: "",
      complete: true,
      prices: {
        version: "demo-prices",
        fx: { date: "demo", cny_per_usd: 6.7351 },
      },
      records,
    };
  });
  return {
    schema_version: 1,
    visibility: privateView ? "private" : "public",
    runs,
  };
}
