import { lazy } from "react";
import type { ComponentType } from "react";
import { moduleRegistry } from "../plugins/moduleRegistry";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Derive the module-registry key from an import path, e.g.
 *   "../pages/Settings/Debug/index.tsx"  →  "Settings/Debug/index"
 *   "../../pages/Settings/Debug"         →  "Settings/Debug/index"
 */
function pathToModuleKey(importPath: string): string {
  const hasExtension = /\.(ts|tsx)$/.test(importPath);
  const key = importPath.replace(/^.*\/pages\//, "").replace(/\.[^.]+$/, "");
  // Bare-directory imports are registered as "<Dir>/index".
  return !hasExtension && !/\/index$/.test(key) ? `${key}/index` : key;
}

function retryImport<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
  retries: number,
): Promise<{ default: T }> {
  return factory().catch((error: unknown) => {
    if (retries <= 0) throw error;
    return new Promise<{ default: T }>((resolve) =>
      setTimeout(
        () => resolve(retryImport(factory, retries - 1)),
        RETRY_DELAY_MS,
      ),
    );
  });
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Like `React.lazy` but retries on chunk-load failure.
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
  if (moduleKeyOrPath) {
    const key = moduleKeyOrPath.startsWith(".")
      ? pathToModuleKey(moduleKeyOrPath)
      : moduleKeyOrPath;
    return lazy(() =>
      retryImport(
        () =>
          moduleRegistry.load(key).then((module) => ({
            default: module.default as T,
          })),
        MAX_RETRIES,
      ),
    );
  }
  return lazy(() => retryImport(factory, MAX_RETRIES));
}

/**
 * Convenience variant — call sites only need the **path string**. The
 * central module registry owns the Vite import factory so routes and plugins
 * share one deduplicated, patchable load path.
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
export function lazyImportWithRetry(
  path: string,
): ReturnType<typeof lazy<ComponentType<unknown>>> {
  const key = pathToModuleKey(path);
  return lazy(() =>
    retryImport(
      () =>
        moduleRegistry.load(key).then((module) => ({
          default: module.default as ComponentType<unknown>,
        })),
      MAX_RETRIES,
    ),
  );
}
