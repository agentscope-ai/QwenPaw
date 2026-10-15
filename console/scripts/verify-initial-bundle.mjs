import { readFile, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadEnv } from "vite";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const consoleDirectory = join(scriptDirectory, "..");
const outputDirectory = join(consoleDirectory, "dist");
const indexPath = join(outputDirectory, "index.html");
const maximumRawBytes = 10 * 1024 * 1024;
const maximumBrotliBytes = 3 * 1024 * 1024;
const env = loadEnv("production", consoleDirectory, "");
const basename = (env.VITE_CONSOLE_BASENAME || "")
  .trim()
  .replace(/^\/+|\/+$/g, "");
const assetPrefix = `/${basename ? `${basename}/` : ""}assets/`;

const html = await readFile(indexPath, "utf-8");
const referencedAssets = [
  ...html.matchAll(/["']([^"']*\/assets\/[^"']+\.(?:css|js))["']/g),
].map(([, asset]) => asset);
if (
  referencedAssets.length === 0 ||
  referencedAssets.some((asset) => !asset.startsWith(assetPrefix))
) {
  throw new Error(`Initial HTML assets must use the ${assetPrefix} prefix.`);
}
const assets = new Set(referencedAssets);
const outputAssetPath = (asset) =>
  join(outputDirectory, "assets", asset.split("/").at(-1));

const initialJavaScriptAssets = [...assets].filter((asset) =>
  asset.endsWith(".js"),
);
const initialJavaScriptNames = new Set(
  initialJavaScriptAssets.map((asset) => asset.split("/").at(-1)),
);
const importGraph = new Map();

for (const asset of initialJavaScriptAssets) {
  const source = await readFile(outputAssetPath(asset), "utf-8");
  const dependencies = new Set(
    [...source.matchAll(/\b(?:from|import)\s*\(?["']\.\/([^"']+\.js)["']/g)]
      .map((match) => match[1])
      .filter((dependency) => initialJavaScriptNames.has(dependency)),
  );
  importGraph.set(asset.split("/").at(-1), dependencies);
}

const visited = new Set();
const active = new Set();
const stack = [];

function findImportCycle(asset) {
  if (active.has(asset)) {
    return [...stack.slice(stack.indexOf(asset)), asset];
  }
  if (visited.has(asset)) {
    return null;
  }

  visited.add(asset);
  active.add(asset);
  stack.push(asset);
  for (const dependency of importGraph.get(asset) ?? []) {
    const cycle = findImportCycle(dependency);
    if (cycle) {
      return cycle;
    }
  }
  stack.pop();
  active.delete(asset);
  return null;
}

for (const asset of initialJavaScriptNames) {
  const cycle = findImportCycle(asset);
  if (cycle) {
    throw new Error(`Initial JavaScript import cycle: ${cycle.join(" -> ")}`);
  }
}

let rawBytes = 0;
let brotliBytes = 0;
for (const asset of assets) {
  const path = outputAssetPath(asset);
  const rawSize = (await stat(path)).size;
  rawBytes += rawSize;
  try {
    brotliBytes += (await stat(`${path}.br`)).size;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    brotliBytes += rawSize;
  }
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
