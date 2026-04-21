/**
 * vite-plugin-patchable.ts
 * 
 * Vite plugin for automatic host module registration in plugin system.
 * Scans source files, extracts exports, and generates registration code.
 * 
 * Usage:
 *   1. Add to vite.config.ts: plugins: [vitePatchable()]
 *   2. Call in main.tsx: installHostExternals() and registerHostModules()
 *   3. Plugins access via: window.QwenPaw.modules["path/to/module"]
 */

import fs from "fs";
import path from "path";
import type { Plugin, ResolvedConfig } from "vite";

// ─────────────────────────────────────────────────────────────────────────────
// Type definitions
// ─────────────────────────────────────────────────────────────────────────────

interface PatchableOptions {
  /** Directories to scan (relative to vite root) */
  include?: string[];
  /** Output path for generated registry file */
  registryOutput?: string;
  /** Import path for moduleRegistry */
  registryImport?: string;
  /** Require @patchable marker to register modules */
  requireMarker?: boolean;
  /** Regex to match @patchable marker */
  marker?: RegExp;
  /** Exclude file patterns */
  exclude?: RegExp[];
  /** Enable debug logging */
  verbose?: boolean;
}

interface ExportInfo {
  name: string;
  kind: "callable" | "value";
}

interface ModuleInfo {
  absPath: string;
  moduleKey: string;
  exports: ExportInfo[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Utility functions
// ─────────────────────────────────────────────────────────────────────────────

function normalizePath(p: string): string {
  return p.replace(/\\/g, "/");
}

function absToModuleKey(absPath: string, pagesRoot: string): string {
  return normalizePath(path.relative(pagesRoot, absPath)).replace(
    /\.[tj]sx?$/,
    "",
  );
}

/**
 * Extract export names from TypeScript/JavaScript source (regex-based, no AST)
 * Covers: export function, export class, export const/let/var, export {}, export default
 */
function extractExports(source: string): ExportInfo[] {
  const seen = new Set<string>();
  const results: ExportInfo[] = [];

  function push(name: string, kind: ExportInfo["kind"]) {
    if (name && !seen.has(name)) {
      seen.add(name);
      results.push({ name, kind });
    }
  }

  // export function foo / export async function foo
  for (const m of source.matchAll(/export\s+(?:async\s+)?function\s+(\w+)/g)) {
    push(m[1], "callable");
  }

  // export class Foo
  for (const m of source.matchAll(/export\s+class\s+(\w+)/g)) {
    push(m[1], "callable");
  }

  // export const/let/var foo = ... (detect arrow functions)
  const bindingRe =
    /export\s+(const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*([\s\S]{0,120})/g;
  for (const m of source.matchAll(bindingRe)) {
    const name = m[2];
    const rhs = m[3];
    const isArrow = /^(?:\([^)]*\)|[\w]+)\s*(?::\s*[\w<>[\],\s]+)?\s*=>/.test(
      rhs.trim(),
    );
    push(name, isArrow ? "callable" : "value");
  }

  // export { foo, bar as baz } (without from)
  for (const m of source.matchAll(/export\s*\{([^}]+)\}(?!\s*from)/g)) {
    for (const part of m[1].split(",")) {
      const alias = part
        .trim()
        .split(/\s+as\s+/)
        .pop()
        ?.trim();
      if (alias && alias !== "default") push(alias, "value");
    }
  }

  // export { foo } from "./module" (re-export)
  for (const m of source.matchAll(/export\s*\{([^}]+)\}\s*from\s*['"]/g)) {
    for (const part of m[1].split(",")) {
      const alias = part
        .trim()
        .split(/\s+as\s+/)
        .pop()
        ?.trim();
      if (alias && alias !== "default") push(alias, "value");
    }
  }

  // export * from "./module" (wildcard re-export)
  const hasWildcardReexport = /export\s+\*\s+from\s+['"]/.test(source);
  if (hasWildcardReexport && results.length === 0) {
    push("__reexport__", "value");
  }

  // export default function/class
  const defaultFunctionMatch = source.match(
    /export\s+default\s+(?:async\s+)?(?:function|class)\s+(\w+)/,
  );
  if (defaultFunctionMatch) {
    push("default", "callable");
  }

  // export default <expression>
  if (!defaultFunctionMatch && /export\s+default\s+/.test(source)) {
    push("default", "value");
  }

  return results;
}

/**
 * Recursively scan directory for TS/TSX files
 */
function scanDirectory(
  dir: string,
  pagesRoot: string,
  requireMarker: boolean,
  marker: RegExp,
  exclude: RegExp[],
  verbose: boolean,
): Map<string, ModuleInfo> {
  const result = new Map<string, ModuleInfo>();

  if (!fs.existsSync(dir)) {
    if (verbose) console.warn(`[patchable] Directory not found: ${dir}`);
    return result;
  }

  function walk(current: string) {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      const abs = normalizePath(path.join(current, entry.name));

      if (entry.isDirectory()) {
        walk(abs);
        continue;
      }

      if (!/\.[tj]sx?$/.test(entry.name)) continue;
      if (/__proxy__/.test(entry.name)) continue;

      if (exclude.some((re) => re.test(abs))) {
        continue;
      }

      let source: string;
      try {
        source = fs.readFileSync(abs, "utf-8");
      } catch {
        continue;
      }

      if (requireMarker && !marker.test(source)) {
        continue;
      }

      const moduleKey = absToModuleKey(abs, pagesRoot);
      const exports = extractExports(source);

      if (exports.length === 0) {
        continue;
      }

      result.set(abs, { absPath: abs, moduleKey, exports });

      if (verbose) {
        console.log(
          `[patchable] Found: ${moduleKey} → [${exports
            .map((e) => e.name)
            .join(", ")}]`,
        );
      }
    }
  }

  walk(dir);
  return result;
}

/**
 * Generate registration file (registerHostModules.ts)
 */
function generateRegistryFile(
  modules: Map<string, ModuleInfo>,
  outputAbsPath: string,
  registryImport: string,
): string {
  const outputDir = path.dirname(outputAbsPath);
  const imports: string[] = [];
  const registers: string[] = [];

  let i = 0;
  for (const info of modules.values()) {
    const alias = `__mod${i++}__`;
    let rel = normalizePath(path.relative(outputDir, info.absPath));
    if (!rel.startsWith(".")) rel = `./${rel}`;
    const relNoExt = rel.replace(/\.[tj]sx?$/, "");
    imports.push(`import * as ${alias} from "${relNoExt}";`);
    registers.push(
      `  moduleRegistry.register("${info.moduleKey}", ${alias});`,
    );
  }

  return [
    `// [auto-generated] Host module registry`,
    `// DO NOT EDIT — regenerated by vite-plugin-patchable on every build`,
    `// Total patchable modules: ${modules.size}`,
    ``,
    `import { moduleRegistry } from "${registryImport}";`,
    ``,
    ...imports,
    ``,
    `export function registerHostModules(): void {`,
    `  console.log("[patchable] Registered %d module(s)", ${modules.size});`,
    ``,
    ...registers,
    `}`,
  ].join("\n");
}

// ─────────────────────────────────────────────────────────────────────────────
// Vite plugin
// ─────────────────────────────────────────────────────────────────────────────

export function vitePatchable(options: PatchableOptions = {}): Plugin {
  const {
    include = ["src/pages"],
    registryOutput = "src/plugins/generated/registerHostModules.ts",
    registryImport = "../moduleRegistry",
    requireMarker = false,
    marker = /^\s*(?:\/\/\s*@patchable|\/\*\*?\s*@patchable[\s\S]*?\*\/)/m,
    exclude = [
      /\.(test|spec)\.[tj]sx?$/,
      /\.d\.ts$/,
      /\.module\.(less|css|scss)$/,
    ],
    verbose = false,
  } = options;

  let viteConfig: ResolvedConfig;
  let modules = new Map<string, ModuleInfo>();

  function scan() {
    modules.clear();
    const root = viteConfig.root;

    for (const includeDir of include) {
      const absInclude = normalizePath(path.resolve(root, includeDir));
      const found = scanDirectory(
        absInclude,
        absInclude,
        requireMarker,
        marker,
        exclude,
        verbose,
      );

      for (const [key, value] of found) {
        modules.set(key, value);
      }
    }

    console.log(`[patchable] Total modules found: ${modules.size}`);

    const outputAbs = normalizePath(path.resolve(root, registryOutput));
    const outputDir = path.dirname(outputAbs);

    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    const content = generateRegistryFile(modules, outputAbs, registryImport);
    fs.writeFileSync(outputAbs, content, "utf-8");

    if (verbose) {
      console.log(`[patchable] Generated registry file: ${registryOutput}`);
    }
  }

  return {
    name: "vite-plugin-patchable",

    configResolved(config) {
      viteConfig = config;
    },

    buildStart() {
      scan();
    },

    handleHotUpdate({ file }) {
      if (/\.[tj]sx?$/.test(file)) {
        const normalized = normalizePath(file);
        const wasTracked = modules.has(normalized);

        scan();

        const isTracked = modules.has(normalized);

        if (verbose && wasTracked !== isTracked) {
          console.log(
            `[patchable] File ${
              isTracked ? "added to" : "removed from"
            } registry: ${file}`,
          );
        }
      }
    },
  };
}
