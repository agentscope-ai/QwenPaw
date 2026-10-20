#!/usr/bin/env node
// Reduce a QwenPaw SSE stream with the response builder that actually ships
// in `@agentscope-ai/chat`, so a replay fold can be judged by the client
// rather than by a model of it.
//
// The SDK is published as ESM with extensionless relative imports, which
// plain Node refuses to resolve, so the builder is bundled once with the
// esbuild that already sits in `console/node_modules`. Nothing else from the
// console tree is touched.
//
// Usage:
//   node scripts/sdk_builder_reduce.mjs [--sdk-root DIR] [--cache DIR] \
//       [--input FILE]
//
// `--input` defaults to stdin. Either way the input is a JSON array of SSE
// lines, each framed exactly as the channel frames it (`data: {...}\n\n`).
// stdout is one JSON object; see `summarize` below for its shape.

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const SSE_PREFIX = "data: ";
const SSE_SUFFIX = "\n\n";

// Mirrors `_IGNORED_FIELDS` in tests/unit/app/replay_oracle.py: C8 forbids a
// client from depending on `sequence_number`, and the builder defaults
// `created_at` to the wall clock, so neither can take part in a comparison.
const IGNORED_FIELDS = new Set(["sequence_number", "created_at", "object"]);

// Mirrors `_GENERATING` in the same module (`index.tsx:4256-4276`).
const GENERATING = new Set(["created", "in_progress", "cancelled"]);

function parseArgs(argv) {
  const args = {
    sdkRoot: "console/node_modules",
    cache: null,
    input: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--sdk-root") {
      args.sdkRoot = value;
      index += 1;
    } else if (flag === "--cache") {
      args.cache = value;
      index += 1;
    } else if (flag === "--input") {
      args.input = value;
      index += 1;
    } else {
      throw new Error(`unknown flag: ${flag}`);
    }
  }
  return args;
}

function readInput(path) {
  const raw = path ? readFileSync(path, "utf8") : readFileSync(0, "utf8");
  const events = JSON.parse(raw);
  if (!Array.isArray(events)) throw new Error("input must be a JSON array");
  return events;
}

function entryPath(sdkRoot) {
  return join(
    sdkRoot,
    "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core",
    "AgentScopeRuntime/Response/Builder.js",
  );
}

// Bundle the builder, reusing a cached bundle until the SDK file changes.
function bundle(entry, sdkRoot, cacheDir) {
  mkdirSync(cacheDir, { recursive: true });
  const digest = createHash("sha256");
  digest.update(resolve(entry));
  digest.update(String(statSync(entry).mtimeMs));
  digest.update(String(statSync(entry).size));
  const outfile = join(cacheDir, `builder-${digest.digest("hex").slice(0, 16)}.mjs`);
  if (existsSync(outfile)) return outfile;
  execFileSync(
    join(sdkRoot, ".bin/esbuild"),
    [
      entry,
      "--bundle",
      "--format=esm",
      "--platform=node",
      "--target=node18",
      "--log-level=error",
      `--outfile=${outfile}`,
    ],
    { stdio: ["ignore", "ignore", "inherit"] },
  );
  return outfile;
}

function normalizeCancellation(payload) {
  if (payload.object !== "response" || payload.status !== "cancelled") return;
  payload.status = "canceled";
  for (const message of Array.isArray(payload.output) ? payload.output : []) {
    if (!message || typeof message !== "object") continue;
    if (GENERATING.has(message.status)) message.status = "canceled";
    const contents = Array.isArray(message.content) ? message.content : [];
    for (const content of contents) {
      if (content && typeof content === "object" && GENERATING.has(content.status)) {
        content.status = "canceled";
      }
    }
  }
}

// The console installs a `responseParser` in front of the builder
// (`index.tsx:4251-4368`). Three control frames never reach the builder:
// `turn_usage` and `rate_limited` return null, and `replay_end` becomes a
// heartbeat that `handle` skips. Reproducing that here is what keeps an
// error frame from being fabricated out of a usage report.
function parseResponse(chunk) {
  if (!chunk.startsWith(SSE_PREFIX) || !chunk.endsWith(SSE_SUFFIX)) {
    return { kind: "unparseable" };
  }
  const body = chunk.slice(SSE_PREFIX.length, chunk.length - SSE_SUFFIX.length);
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return { kind: "unparseable" };
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { kind: "unparseable" };
  }
  normalizeCancellation(payload);
  if (payload.type === "turn_usage" || payload.type === "rate_limited") {
    return { kind: "swallow" };
  }
  if (payload.type === "replay_end") {
    return { kind: "payload", payload: { object: "message", type: "heartbeat" } };
  }
  return { kind: "payload", payload };
}

function stripIgnored(node) {
  if (!node || typeof node !== "object" || Array.isArray(node)) return node;
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (!IGNORED_FIELDS.has(key)) out[key] = value;
  }
  return out;
}

function summarizeMessage(message) {
  const summary = stripIgnored(message);
  if (!summary || typeof summary !== "object") return summary;
  delete summary.content;
  summary.content = (message.content || []).map(stripIgnored);
  return summary;
}

// `handleError` stamps a fresh `uuid()` onto the message it injects, so the
// id is replaced by its ordinal — nothing downstream keys on it, and a
// random id can never compare equal across two reductions.
function stabilizeErrorIds(output) {
  let seen = 0;
  for (const message of output) {
    if (message && message.type === "error") {
      message.id = `__error_${seen}__`;
      seen += 1;
    }
  }
  return output;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const sdkRoot = resolve(args.sdkRoot);
  const entry = entryPath(sdkRoot);
  if (!existsSync(entry)) throw new Error(`builder not found: ${entry}`);
  const cacheDir =
    args.cache ??
    join(
      tmpdir(),
      `qwenpaw-sdk-builder-${createHash("sha256").update(sdkRoot).digest("hex").slice(0, 12)}`,
    );
  const outfile = bundle(entry, sdkRoot, cacheDir);
  const module = await import(pathToFileURL(outfile).href);
  const Builder = module.default;

  const events = readInput(args.input);
  // `handleContent` warns when it cannot find the host message. The count is
  // what matters here, not the text, so keep it out of the harness output.
  console.warn = () => {};
  const builder = new Builder({});
  const verbatim = [];
  const intercepted = [];
  let dropped = 0;
  for (const chunk of events) {
    const parsed = parseResponse(chunk);
    if (parsed.kind === "unparseable") {
      verbatim.push(chunk);
      continue;
    }
    if (parsed.kind === "swallow") {
      intercepted.push(chunk);
      continue;
    }
    const before = builder.data;
    builder.handle(parsed.payload);
    // immer hands back the very same object when a recipe changed nothing,
    // which is exactly what the missing-host-message early return does.
    if (parsed.payload.object === "content" && builder.data === before) {
      dropped += 1;
    }
  }

  const state = builder.data;
  const output = stabilizeErrorIds((state.output || []).map(summarizeMessage));
  // `handleError` writes `code` and `message` unconditionally, so a payload
  // without them leaves own properties holding `undefined`, which
  // `JSON.stringify` would silently drop. The Python oracle keeps them as
  // `null`, so keep the keys here too.
  const keepUndefinedAsNull = (_key, value) =>
    value === undefined ? null : value;
  process.stdout.write(
    `${JSON.stringify(
      {
        status: state.status ?? null,
        id: state.id ?? null,
        output,
        verbatim,
        intercepted,
        dropped,
      },
      keepUndefinedAsNull,
    )}\n`,
  );
}

main().catch((error) => {
  process.stderr.write(`${error && error.message ? error.message : error}\n`);
  process.exit(1);
});
