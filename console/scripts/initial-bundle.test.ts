import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { checkInitialBundle, measureInitialBundle } from "./initial-bundle.mjs";

const directories: string[] = [];

async function fixture(manifest: Record<string, unknown>) {
  const directory = await mkdtemp(join(tmpdir(), "qwenpaw-bundle-"));
  directories.push(directory);
  await mkdir(join(directory, ".vite"));
  await mkdir(join(directory, "assets"));
  await writeFile(
    join(directory, ".vite", "manifest.json"),
    JSON.stringify(manifest),
  );
  return directory;
}

afterEach(async () => {
  await Promise.all(
    directories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true })),
  );
});

describe("initial bundle static closure", () => {
  it("counts transitive imports and shared CSS once, excluding dynamic imports", async () => {
    const directory = await fixture({
      "index.html": {
        file: "assets/index.js",
        imports: ["shell", "shared"],
        dynamicImports: ["charts"],
        css: ["assets/index.css"],
      },
      shell: { file: "assets/shell.js", imports: ["shared"] },
      shared: { file: "assets/shared.js", css: ["assets/index.css"] },
      charts: { file: "assets/charts.js", imports: ["index.html"] },
    });
    for (const file of ["index.js", "shell.js", "shared.js", "index.css"]) {
      await writeFile(join(directory, "assets", file), "1234567890");
      await writeFile(join(directory, "assets", `${file}.br`), "123");
    }
    // Public base paths do not affect the manifest's output-relative paths.
    await writeFile(
      join(directory, "index.html"),
      '<script type="module" src="/nested/console/assets/index.js"></script>',
    );
    const report = await measureInitialBundle(directory);
    expect(report.assets).toHaveLength(4);
    expect(report.rawBytes).toBe(40);
    expect(report.brotliBytes).toBe(12);
  });

  it("finds a static cycle outside the HTML's direct preload list", async () => {
    const directory = await fixture({
      "index.html": { file: "assets/index.js", imports: ["a"] },
      a: { file: "assets/a.js", imports: ["b"] },
      b: { file: "assets/b.js", imports: ["a"] },
    });
    await expect(measureInitialBundle(directory)).rejects.toThrow(
      "assets/a.js -> assets/b.js -> assets/a.js",
    );
  });

  it("fails for missing manifest dependencies instead of undercounting", async () => {
    const directory = await fixture({
      "index.html": { file: "assets/index.js", imports: ["missing"] },
    });
    await expect(measureInitialBundle(directory)).rejects.toThrow(
      "Missing manifest entry: missing",
    );
  });

  it("uses raw bytes conservatively when precompression is absent", async () => {
    const directory = await fixture({
      "index.html": { file: "assets/index.js" },
    });
    await writeFile(join(directory, "assets", "index.js"), "12345");
    const report = await measureInitialBundle(directory);
    expect(report.brotliBytes).toBe(5);
    expect(report.assets[0].compressed).toBe(false);
  });

  it("fails if a required emitted asset is missing", async () => {
    const directory = await fixture({
      "index.html": { file: "assets/missing.js" },
    });
    await expect(measureInitialBundle(directory)).rejects.toThrow("ENOENT");
  });
});

describe("initial bundle budgets", () => {
  const budgets = {
    rawBytes: 100,
    brotliBytes: 50,
    chunkRawBytes: 80,
    chunkBrotliBytes: 40,
    lazyOnly: ["charts-vendor"],
  };

  it("allows totals and chunks exactly on their limits", () => {
    expect(
      checkInitialBundle(
        {
          rawBytes: 100,
          brotliBytes: 50,
          assets: [{ file: "assets/ui.js", rawBytes: 80, brotliBytes: 40 }],
        },
        budgets,
      ),
    ).toEqual([]);
  });

  it("reports total, per-chunk, and lazy dependency regressions together", () => {
    const failures = checkInitialBundle(
      {
        rawBytes: 101,
        brotliBytes: 51,
        assets: [
          {
            file: "assets/charts-vendor-hash.js",
            rawBytes: 81,
            brotliBytes: 41,
          },
        ],
      },
      budgets,
    );
    expect(failures).toHaveLength(5);
    expect(failures.join(" ")).toContain("charts-vendor-hash.js");
  });
});
