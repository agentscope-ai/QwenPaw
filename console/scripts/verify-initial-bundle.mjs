import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { checkInitialBundle, measureInitialBundle } from "./initial-bundle.mjs";

const outputDirectory = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "dist",
);
const MiB = 1024 * 1024;
const budgets = {
  rawBytes: 4 * MiB,
  brotliBytes: 1.2 * MiB,
  chunkRawBytes: 2.5 * MiB,
  chunkBrotliBytes: 0.75 * MiB,
  lazyOnly: ["charts-vendor", "d3-vendor", "editor-vendor"],
};
const report = await measureInitialBundle(outputDirectory);
const javaScript = report.assets.filter((asset) => asset.file.endsWith(".js"));
const toMiB = (bytes) => (bytes / MiB).toFixed(3);
console.table(
  report.assets.map((asset) => ({
    asset: asset.file,
    "raw MiB": toMiB(asset.rawBytes),
    "Brotli MiB": toMiB(asset.brotliBytes),
    compression: asset.compressed ? "Brotli" : "raw fallback",
  })),
);
console.table([
  {
    budget: "Initial raw",
    "used MiB": toMiB(report.rawBytes),
    "limit MiB": toMiB(budgets.rawBytes),
  },
  {
    budget: "Initial Brotli",
    "used MiB": toMiB(report.brotliBytes),
    "limit MiB": toMiB(budgets.brotliBytes),
  },
  {
    budget: "Each initial JS raw",
    "used MiB": toMiB(Math.max(...javaScript.map((asset) => asset.rawBytes))),
    "limit MiB": toMiB(budgets.chunkRawBytes),
  },
  {
    budget: "Each initial JS Brotli",
    "used MiB": toMiB(
      Math.max(...javaScript.map((asset) => asset.brotliBytes)),
    ),
    "limit MiB": toMiB(budgets.chunkBrotliBytes),
  },
]);
console.log(
  `Initial bundle: ${toMiB(report.rawBytes)} MiB raw, ` +
    `${toMiB(report.brotliBytes)} MiB Brotli across ${
      report.assets.length
    } assets.`,
);
const failures = checkInitialBundle(report, budgets);
if (failures.length > 0) throw new Error(failures.join("\n"));
