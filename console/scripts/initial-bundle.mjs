import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";

/** Measure the entry's static imports and CSS using Vite's emitted graph. */
export async function measureInitialBundle(outputDirectory) {
  const manifest = JSON.parse(
    await readFile(join(outputDirectory, ".vite", "manifest.json"), "utf8"),
  );
  const assets = new Set();
  const visited = new Set();
  const active = [];

  function visit(key) {
    if (active.includes(key)) {
      const cycle = [...active.slice(active.indexOf(key)), key];
      throw new Error(
        `Initial JavaScript import cycle: ${cycle
          .map((entry) => manifest[entry].file)
          .join(" -> ")}`,
      );
    }
    if (visited.has(key)) return;
    const chunk = manifest[key];
    if (!chunk) throw new Error(`Missing manifest entry: ${key}`);
    visited.add(key);
    active.push(key);
    assets.add(chunk.file);
    for (const css of chunk.css ?? []) assets.add(css);
    // dynamicImports are intentionally excluded: they are separate budgets.
    for (const dependency of chunk.imports ?? []) visit(dependency);
    active.pop();
  }

  visit("index.html");
  const sizes = await Promise.all(
    [...assets].map(async (file) => {
      const path = join(outputDirectory, file);
      const rawBytes = (await stat(path)).size;
      let brotliBytes = rawBytes;
      let compressed = false;
      try {
        brotliBytes = (await stat(`${path}.br`)).size;
        compressed = true;
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
      }
      return { file, rawBytes, brotliBytes, compressed };
    }),
  );
  sizes.sort((left, right) => right.rawBytes - left.rawBytes);
  return {
    assets: sizes,
    rawBytes: sizes.reduce((sum, asset) => sum + asset.rawBytes, 0),
    brotliBytes: sizes.reduce((sum, asset) => sum + asset.brotliBytes, 0),
  };
}

/** Return all budget violations so CI names each regressing asset. */
export function checkInitialBundle(report, budgets) {
  const failures = [];
  if (report.rawBytes > budgets.rawBytes) {
    failures.push("Initial raw bundle exceeds budget.");
  }
  if (report.brotliBytes > budgets.brotliBytes) {
    failures.push("Initial Brotli bundle exceeds budget.");
  }
  for (const asset of report.assets) {
    if (asset.file.endsWith(".js") && asset.rawBytes > budgets.chunkRawBytes) {
      failures.push(`${asset.file} exceeds the JavaScript chunk raw budget.`);
    }
    if (
      asset.file.endsWith(".js") &&
      asset.brotliBytes > budgets.chunkBrotliBytes
    ) {
      failures.push(
        `${asset.file} exceeds the JavaScript chunk Brotli budget.`,
      );
    }
    if (
      budgets.lazyOnly.some((name) => asset.file.startsWith(`assets/${name}-`))
    ) {
      failures.push(`${asset.file} must remain outside the initial bundle.`);
    }
  }
  return failures;
}
