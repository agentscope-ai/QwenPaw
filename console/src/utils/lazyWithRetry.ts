import { createElement, lazy } from "react";
import type { ComponentType } from "react";
import { moduleRegistry } from "../plugins/moduleRegistry";
import { isChunkLoadError, isErrorLike } from "./chunkRecovery";
import { importFailures } from "./lazyImportFailure";

export { getLazyImportFailure } from "./lazyImportFailure";

const failedImports = new WeakMap<object, Set<() => void>>();
/** Reset only imports caught by the boundary, after React commits the error. */
export function resetFailedLazyImports(error: object): void {
  const resets = failedImports.get(error);
  failedImports.delete(error);
  resets?.forEach((reset) => reset());
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Derive the module-registry key from an import path, e.g.
 *   "../pages/Settings/Debug/index.tsx"  →  "Settings/Debug/index"
 *   "../../pages/Settings/Debug"         →  "Settings/Debug/index"
 */
function pathToModuleKey(importPath: string): string {
  const key = importPath.replace(/^.*\/pages\//, "").replace(/\.[^.]+$/, "");
  // Bare-directory imports are registered as "<Dir>/index" in registerHostModules
  return key.includes("/") && !/\/index$/.test(key) ? `${key}/index` : key;
}

function loadImport<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
): Promise<{ default: T }> {
  return factory().catch((error: unknown) => {
    if (isErrorLike(error)) {
      importFailures.set(error, { attempts: 1 });
    }
    // Browsers cache failed module imports for this document. The boundary
    // recovers with a bounded reload instead of repeating the same import.
    throw error;
  });
}

/** Keep the public component stable while replacing rejected lazy payloads. */
function recoverableLazy(
  loader: () => Promise<{ default: ComponentType<unknown> }>,
  modulePath?: string,
): ComponentType<unknown> {
  const load = () =>
    loader().catch((error: unknown) => {
      if (isChunkLoadError(error)) {
        importFailures.set(error, {
          attempts: importFailures.get(error)?.attempts ?? 1,
          modulePath,
        });
        const resets = failedImports.get(error) ?? new Set<() => void>();
        resets.add(() => {
          LazyPage = lazy(load);
        });
        failedImports.set(error, resets);
      }
      throw error;
    });
  let LazyPage = lazy(load);
  return function RecoverablePage(props: unknown) {
    return createElement(LazyPage, props as Record<string, unknown>);
  };
}

// All page modules, keyed relative to this file (src/utils/).
// e.g. "../pages/Settings/Debug/index.tsx"
const PAGE_MODULES = import.meta.glob<ComponentType<unknown>>(
  ["../pages/**/*.{ts,tsx}", "!../pages/**/*.test.{ts,tsx}"],
  { import: "default" },
);

/**
 * Normalize any caller-relative path to the glob key used by PAGE_MODULES.
 * Callers in src/layouts/MainLayout use "../../pages/…"
 * The glob map is keyed as "../pages/…" (relative to src/utils/).
 */
function toGlobKey(path: string): string {
  // Strip everything up to and including the first occurrence of "pages/"
  let afterPages = path.replace(/^.*pages\//, "pages/");
  // Remove a bare "/index" suffix so both "Foo/index" and "Foo" resolve the same
  afterPages = afterPages.replace(/\/index$/, "");
  // Add the ../  prefix to match the glob map
  return `../${afterPages}`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Like `React.lazy` but supports boundary recovery on chunk-load failure.
 * Pass the import path as a second argument to enable plugin-registry lookup:
 *
 * ```ts
 * // registry lookup enabled
 * const DebugPage = lazyWithRetry(
 *   () => import("../../pages/Settings/Debug"),
 *   "../../pages/Settings/Debug",
 * );
 * // no registry lookup (default behaviour, unchanged)
 * const ModelsPage = lazyWithRetry(() => import("../../pages/Settings/Models"));
 * ```
 */
export function lazyWithRetry<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
  moduleKeyOrPath?: string,
) {
  return recoverableLazy(() => {
    if (moduleKeyOrPath) {
      const key = moduleKeyOrPath.startsWith(".")
        ? pathToModuleKey(moduleKeyOrPath)
        : moduleKeyOrPath;
      const patched = moduleRegistry.get(key, "default");
      if (patched) return Promise.resolve({ default: patched as T });
    }
    return loadImport(factory);
  }, moduleKeyOrPath);
}

/**
 * Convenience variant — call sites only need the **path string**.
 * The dynamic import is sourced from an `import.meta.glob` map, so Vite
 * still creates individual chunks while allowing a runtime registry override.
 *
 * Path is relative to the caller — bare-directory or full-extension paths both work:
 *
 * ```ts
 * // from src/layouts/MainLayout/ — bare directory, index.tsx resolved automatically
 * const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
 * ```
 *
 * Any plugin that patches `Settings/Debug/index.default` in the module
 * registry will automatically take effect.
 */
export function lazyImportWithRetry(path: string): ComponentType<unknown> {
  // Normalise to the glob-map key (relative to src/utils/).
  // Bare-directory paths like "../../pages/Settings/Debug" are tried with
  // /index.tsx and /index.ts suffixes automatically.
  const base = toGlobKey(path);
  const globKey = PAGE_MODULES[base]
    ? base
    : PAGE_MODULES[`${base}/index.tsx`]
    ? `${base}/index.tsx`
    : PAGE_MODULES[`${base}/index.ts`]
    ? `${base}/index.ts`
    : base;
  const factory = PAGE_MODULES[globKey];
  if (!factory) {
    throw new Error(
      `[lazyImportWithRetry] No glob entry found for "${path}".\n` +
        `Resolved key: "${globKey}". ` +
        `Available: ${Object.keys(PAGE_MODULES).join(", ")}`,
    );
  }
  const key = pathToModuleKey(path);
  return recoverableLazy(() => {
    const patched = moduleRegistry.get(key, "default");
    if (patched) {
      return Promise.resolve({
        default: patched as ComponentType<unknown>,
      });
    }
    return loadImport(() => factory().then((comp) => ({ default: comp })));
  }, path);
}
