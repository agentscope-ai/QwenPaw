// vite-plugin-patchable.ts
// 放在项目根目录，在 vite.config.ts 中引入
//
// 使用方式：
//   1. 在需要暴露给插件的模块顶部加注释: // @patchable
//   2. vite.config.ts 中引入: plugins: [vitePatchable()]
//   3. main.tsx 中调用: installHostExternals() （会自动调用生成的 registerHostModules）
//   4. 宿主代码从 .proxy 文件导入: import { fn } from "./foo.__proxy__"
//      或开启 autoRewrite: true 自动重写所有 import
//
// 插件端使用：
//   const mod = window.QwenPaw.modules["Chat/OptionsPanel/defaultConfig"];
//   const orig = mod.getDefaultConfig;
//   mod.getDefaultConfig = (type) => ({ ...orig(type), greeting: "Hi" });

import fs from "fs";
import path from "path";
import type { Plugin, ResolvedConfig } from "vite";

// ─────────────────────────────────────────────────────────────────────────────
// 类型定义
// ─────────────────────────────────────────────────────────────────────────────

interface PatchableOptions {
  /**
   * 扫描目录列表，相对于 vite root（通常是项目根目录）
   * @default ["src/pages"]
   */
  include?: string[];

  /**
   * 生成的注册文件路径，相对于 vite root
   * @default "src/plugins/generated/registerHostModules.ts"
   */
  registryOutput?: string;

  /**
   * moduleRegistry 单例的导入路径，相对于生成文件
   * @default "../moduleRegistry"
   */
  registryImport?: string;

  /**
   * 是否需要 @patchable 标记才注册模块
   * @default false （注册所有文件）
   */
  requireMarker?: boolean;

  /**
   * 触发 @patchable 标记的正则（当 requireMarker = true 时使用）
   * @default /^\s*(?:\/\/\s*@patchable|\/\*\*?\s*@patchable[\s\S]*?\*\/)/m
   */
  marker?: RegExp;

  /**
   * 排除文件的正则列表
   * @default [/\.(test|spec)\.[tj]sx?$/, /\.d\.ts$/, /\.module\.(less|css|scss)$/]
   */
  exclude?: RegExp[];

  /**
   * 是否输出调试日志
   * @default false
   */
  verbose?: boolean;
}

interface ExportInfo {
  name: string;
  /** function/class 走 call()；const/let/var 走 get() */
  kind: "callable" | "value";
}

interface ModuleInfo {
  /** 绝对路径（normalize 后） */
  absPath: string;
  /** 注册表 key，如 "Chat/OptionsPanel/defaultConfig" */
  moduleKey: string;
  /** 提取到的导出列表 */
  exports: ExportInfo[];
}

// ─────────────────────────────────────────────────────────────────────────────
// 工具函数
// ─────────────────────────────────────────────────────────────────────────────

function normalizePath(p: string): string {
  return p.replace(/\\/g, "/");
}

/**
 * 把绝对路径转换成模块 key
 * /project/src/pages/Chat/OptionsPanel/defaultConfig.ts
 * → Chat/OptionsPanel/defaultConfig
 */
function absToModuleKey(absPath: string, pagesRoot: string): string {
  return normalizePath(path.relative(pagesRoot, absPath)).replace(
    /\.[tj]sx?$/,
    "",
  );
}

/**
 * 从 TypeScript/JavaScript 源码中提取导出名（不依赖 AST，正则实现）
 * 覆盖：
 *   export function foo
 *   export async function foo
 *   export class Foo
 *   export const/let/var foo = ...（含箭头函数判断）
 *   export { foo, bar as baz }
 *   export default function Foo / export default class Foo / export default Foo
 *   - 对于 export default，使用 "default" 作为导出名
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

  // export const/let/var foo [: Type] = ...
  // 需要判断右侧是否是箭头函数
  const bindingRe =
    /export\s+(const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*([\s\S]{0,120})/g;
  for (const m of source.matchAll(bindingRe)) {
    const name = m[2];
    const rhs = m[3];
    // 右侧开头是箭头函数特征：( args ) => 或 arg =>
    const isArrow = /^(?:\([^)]*\)|[\w]+)\s*(?::\s*[\w<>[\],\s]+)?\s*=>/.test(
      rhs.trim(),
    );
    push(name, isArrow ? "callable" : "value");
  }

  // export { foo, bar as baz } (不含 from)
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

  // export { foo, bar as baz } from "./module" (re-export)
  // 这些导出也应该被注册，因为它们在当前模块中可用
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

  // export * from "./module" - 这种情况无法静态分析，跳过
  // 但我们可以标记该模块有导出
  const hasWildcardReexport = /export\s+\*\s+from\s+['"]/.test(source);
  if (hasWildcardReexport && results.length === 0) {
    // 如果只有 export * from，我们添加一个特殊标记
    // 这样至少该模块会被注册
    push("__reexport__", "value");
  }

  // export default function Foo / export default class Foo
  // 捕获默认导出的函数或类名
  const defaultFunctionMatch = source.match(
    /export\s+default\s+(?:async\s+)?(?:function|class)\s+(\w+)/,
  );
  if (defaultFunctionMatch) {
    push("default", "callable");
  }

  // export default Foo (标识符) 或 export default expression
  // 仅在没有找到 function/class 时才检查
  if (!defaultFunctionMatch && /export\s+default\s+/.test(source)) {
    push("default", "value");
  }

  return results;
}

/**
 * 递归扫描目录，收集所有 TS/TSX 文件（或带 @patchable 标记的文件）
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

      // 只处理 TS/TSX/JS/JSX，跳过已生成的 proxy 文件
      if (!/\.[tj]sx?$/.test(entry.name)) continue;
      if (/__proxy__/.test(entry.name)) continue;

      // 应用排除规则
      if (exclude.some((re) => re.test(abs))) {
        if (verbose) console.log(`[patchable] Excluded: ${abs}`);
        continue;
      }

      let source: string;
      try {
        source = fs.readFileSync(abs, "utf-8");
      } catch {
        continue;
      }

      // 如果需要标记，检查是否有 @patchable
      if (requireMarker && !marker.test(source)) {
        continue;
      }

      const moduleKey = absToModuleKey(abs, pagesRoot);
      const exports = extractExports(source);

      if (exports.length === 0) {
        if (verbose)
          console.warn(`[patchable] No exports found (skipped): ${abs}`);
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
 * 生成集中注册文件（registerHostModules.ts）
 *
 * 生成结果示例：
 *   import { moduleRegistry } from "../moduleRegistry";
 *   import * as __mod0__ from "../../pages/Chat/OptionsPanel/defaultConfig";
 *   export function registerHostModules(): void {
 *     moduleRegistry.register("Chat/OptionsPanel/defaultConfig", __mod0__);
 *   }
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
    // 去掉扩展名（TS 编译器和 Vite 都能解析无扩展名路径）
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
    `  console.log("[patchable] Registering %d module(s)...", ${modules.size});`,
    ``,
    ...registers,
    ``,
    `  console.log(`,
    `    "[patchable] Successfully registered %d module(s):",`,
    `    moduleRegistry.keys().length,`,
    `    moduleRegistry.keys(),`,
    `  );`,
    `}`,
  ].join("\n");
}

// ─────────────────────────────────────────────────────────────────────────────
// Vite 插件主体
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

    if (verbose) {
      console.log(`[patchable] Total modules found: ${modules.size}`);
    }

    // 生成注册文件
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
      // 开发模式下，监听文件变化重新扫描
      if (/\.[tj]sx?$/.test(file)) {
        const normalized = normalizePath(file);
        const wasTracked = modules.has(normalized);

        scan();

        const isTracked = modules.has(normalized);

        if (wasTracked !== isTracked) {
          if (verbose) {
            console.log(
              `[patchable] File ${
                isTracked ? "added to" : "removed from"
              } registry: ${file}`,
            );
          }
        }
      }
    },
  };
}
