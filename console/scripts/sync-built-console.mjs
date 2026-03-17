import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const consoleDir = path.resolve(__dirname, "..");
const distDir = path.join(consoleDir, "dist");
const backendConsoleDir = path.resolve(consoleDir, "../src/copaw/console");

if (!existsSync(path.join(distDir, "index.html"))) {
  console.error(`[console sync] Missing build output: ${distDir}`);
  process.exit(1);
}

rmSync(backendConsoleDir, { recursive: true, force: true });
mkdirSync(backendConsoleDir, { recursive: true });
cpSync(distDir, backendConsoleDir, { recursive: true });

console.log(`[console sync] Synced ${distDir} -> ${backendConsoleDir}`);

