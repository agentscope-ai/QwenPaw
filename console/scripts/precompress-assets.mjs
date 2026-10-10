import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { brotliCompress, constants, gzip } from "node:zlib";

const compressBrotli = promisify(brotliCompress);
const compressGzip = promisify(gzip);
const outputDirectory = new URL("../dist/", import.meta.url);
const compressibleExtensions = new Set([
  ".css",
  ".html",
  ".js",
  ".json",
  ".svg",
  ".txt",
  ".wasm",
]);
const minimumSize = 1024;

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(
    entries.map(async (entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? walk(path) : [path];
    }),
  );
  return files.flat();
}

async function compress(path) {
  if (!compressibleExtensions.has(extname(path))) return false;
  if ((await stat(path)).size < minimumSize) return false;
  const source = await readFile(path);
  const [brotli, gzipped] = await Promise.all([
    compressBrotli(source, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 6,
      },
    }),
    compressGzip(source, { level: 6 }),
  ]);
  await Promise.all([
    writeFile(`${path}.br`, brotli),
    writeFile(`${path}.gz`, gzipped),
  ]);
  return true;
}

const outputPath = fileURLToPath(outputDirectory);
const files = await walk(outputPath);
const results = await Promise.all(files.map(compress));
const count = results.filter(Boolean).length;
console.log(`Precompressed ${count} Console assets.`);
