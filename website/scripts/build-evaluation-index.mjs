import { readFile, readdir, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";
import Ajv from "ajv/dist/2020.js";
import { check, summarize, validateDefinition } from "./evaluation-scoring.mjs";

const root = new URL("../evaluation/", import.meta.url);
const read = async (url) => JSON.parse(await readFile(url, "utf8"));
const ajv = new Ajv({ allErrors: true });
ajv.addFormat(
  "timestamp",
  (value) =>
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString() === value.replace("Z", ".000Z"),
);
ajv.addFormat("public-https-url", (value) => {
  try {
    const u = new URL(value);
    return (
      u.protocol === "https:" &&
      !u.username &&
      !u.password &&
      !u.search &&
      !u.hash
    );
  } catch {
    return false;
  }
});
const validate = ajv.compile(await read(new URL("schema.json", root)));
const definitions = await read(new URL("indexes.json", root));
const definitionIds = new Set();
for (const definition of definitions) {
  validateDefinition(definition);
  check(!definitionIds.has(definition.id), "Duplicate index version");
  definitionIds.add(definition.id);
}
const groups = new Map();
const ids = new Set();
check(
  !(await readdir(new URL("results/", root))).some((n) => n.endsWith(".json")),
  "Use testing/ or official/",
);
for (const kind of ["official"]) {
  for (const name of (await readdir(new URL(`results/${kind}/`, root)))
    .filter((n) => n.endsWith(".json"))
    .sort()) {
    const input = await read(new URL(`results/${kind}/${name}`, root));
    check(validate(input), `${name}: ${ajv.errorsText(validate.errors)}`);
    check(
      name === `${input.id}.json` && input.kind === kind,
      `${name}: mismatched identity or kind`,
    );
    check(!ids.has(input.id), "Duplicate observation ID");
    ids.add(input.id);
    const benchmarkIds = new Set();
    for (const benchmark of input.benchmarks) {
      check(!benchmarkIds.has(benchmark.id), "Duplicate benchmark summary");
      benchmarkIds.add(benchmark.id);
      summarize(benchmark, benchmark.id, "validation", input.exchange_rate);
    }
    const key = JSON.stringify([kind, input.board.id, input.id]);
    const group = groups.get(key) ?? [];
    group.push(
      ...input.benchmarks.map((benchmark) => ({
        ...input,
        publication_id: input.id,
        id: benchmark.observation_id,
        date: benchmark.date,
        benchmark,
      })),
    );
    groups.set(key, group);
  }
}
const runs = [];
const runIds = new Set();
for (const observations of groups.values()) {
  observations.sort(
    (a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id),
  );
  const epochs = new Map();
  for (const input of observations)
    epochs.set(input.experiment, [input.date, input]);
  for (const [experiment, [date, origin]] of epochs) {
    for (const definition of definitions) {
      const available = new Map();
      for (const input of observations) {
        const spec = definition.benchmarks[input.benchmark.id];
        if (input.date > date || !spec) continue;
        if (
          input.benchmark.revision !== spec.revision ||
          input.benchmark.expected !== spec.expected ||
          !["kind", "model", "scorer", "prompt_revision"].every((field) =>
            isDeepStrictEqual(input.benchmark.judge[field], spec.judge[field]),
          )
        )
          continue;
        available.set(input.benchmark.id, input);
      }
      if (!available.size) continue;
      const parts = [];
      for (const [direction, metadata] of Object.entries(
        definition.directions,
      )) {
        for (const benchmark of Object.keys(metadata.benchmarks)) {
          const part = summarize(
            available.get(benchmark)?.benchmark,
            benchmark,
            direction,
            origin.exchange_rate,
          );
          if (!available.has(benchmark))
            Object.assign(part, {
              name: definition.benchmarks[benchmark].name,
              expected: definition.benchmarks[benchmark].expected,
              judge: definition.benchmarks[benchmark].judge,
            });
          parts.push(part);
        }
      }
      const complete = parts.every((p) => p.score !== null);
      const id = `${origin.publication_id}--${definition.id}`;
      check(!runIds.has(id), "Duplicate run ID");
      runIds.add(id);
      runs.push({
        schema_version: 4,
        kind: origin.kind,
        board: origin.board,
        index_version: definition.id,
        index_definition: definition,
        id,
        date,
        source_repository: origin.source_repository,
        exchange_rate: origin.exchange_rate,
        workflow_url: "",
        source_results: [...available.values()].map((v) => ({
          id: v.id,
          date: v.date,
          benchmark: v.benchmark.id,
          parameters: v.parameters,
        })),
        benchmark_versions: Object.values(definition.benchmarks),
        complete,
        records: [
          {
            model: origin.model,
            provider: origin.provider,
            harness: origin.harness,
            sdk_version: origin.sdk_version,
            source_repository: origin.source_repository,
            complete,
            benchmarks: parts,
          },
        ],
      });
    }
  }
}
runs.sort(
  (a, b) =>
    b.index_definition.order - a.index_definition.order ||
    b.date.localeCompare(a.date),
);
const target = new URL("../public/evaluation/data/", import.meta.url);
await mkdir(target, { recursive: true });
await writeFile(
  new URL("index.json", target),
  JSON.stringify({ schema_version: 4, runs }, null, 2) + "\n",
);
console.log(
  `Evaluation index: ${runs.length} snapshots from ${
    ids.size
  } publication summaries → ${fileURLToPath(target)}`,
);
