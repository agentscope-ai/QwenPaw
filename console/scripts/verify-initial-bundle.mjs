import { readFile, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const outputDirectory = join(scriptDirectory, "..", "dist");
const indexPath = join(outputDirectory, "index.html");
const maximumRawBytes = 10 * 1024 * 1024;
const maximumBrotliBytes = 3 * 1024 * 1024;

const html = await readFile(indexPath, "utf-8");
const assets = new Set(
  [...html.matchAll(/\/assets\/[^"' ]+\.(?:css|js)/g)].map(([asset]) => asset),
);

let rawBytes = 0;
let brotliBytes = 0;
for (const asset of assets) {
  const path = join(outputDirectory, asset);
  rawBytes += (await stat(path)).size;
  brotliBytes += (await stat(`${path}.br`)).size;
}

const toMiB = (bytes) => (bytes / 1024 / 1024).toFixed(2);
console.log(
  `Initial bundle: ${toMiB(rawBytes)} MiB raw, ` +
    `${toMiB(brotliBytes)} MiB Brotli across ${assets.size} assets.`,
);

if (rawBytes > maximumRawBytes) {
  throw new Error(`Initial raw bundle exceeds ${toMiB(maximumRawBytes)} MiB.`);
}
if (brotliBytes > maximumBrotliBytes) {
  throw new Error(
    `Initial Brotli bundle exceeds ${toMiB(maximumBrotliBytes)} MiB.`,
  );
}
