/**
 * moduleRegistry.ts
 *
 * Runtime module registry for plugin system monkey-patching
 *
 * How it works:
 * 1. Host app calls moduleRegistry.register() at startup to register all @patchable modules
 * 2. Plugins access and modify module exports via window.QwenPaw.modules
 * 3. Host code accesses modules via moduleRegistry.get/call to ensure using plugin-modified versions
 */

export interface ModuleRegistry {
  /**
   * Register a module (called by generated registerHostModules())
   */
  register(key: string, module: Record<string, unknown>): void;

  /**
   * Get a module export value (for const/let/var types)
   */
  get(moduleKey: string, exportName: string): unknown;

  /**
   * Get an optional module export without logging when the module is absent.
   */
  getOptional(moduleKey: string, exportName: string): unknown;

  /**
   * Call a module export function (for function/class types)
   */
  call(moduleKey: string, exportName: string, ...args: unknown[]): unknown;

  /**
   * Get all registered module keys
   */
  keys(): string[];

  /**
   * Get entire module object (for plugin use)
   */
  getModule(key: string): Record<string, unknown> | undefined;
}

class ModuleRegistryImpl implements ModuleRegistry {
  // Plugins keep registration handles here between frontend evaluations.
  readonly modules: Record<string, Record<string, unknown>> =
    Object.create(null);

  register(key: string, module: Record<string, unknown>): void {
    // Safely copy module exports, avoiding ES Module namespace special properties
    const safeCopy: Record<string, unknown> = {};

    try {
      // Only copy enumerable own properties
      for (const exportName of Object.keys(module)) {
        try {
          const descriptor = Object.getOwnPropertyDescriptor(
            module,
            exportName,
          );
          if (descriptor && descriptor.enumerable) {
            // Read the current value (works for both plain properties and getters)
            safeCopy[exportName] = module[exportName];
          }
        } catch (e) {
          // Skip inaccessible properties
          if (console && console.warn) {
            console.warn(
              `[moduleRegistry] Cannot copy property ${exportName} from ${key}:`,
              e,
            );
          }
        }
      }

      this.modules[key] = safeCopy;
    } catch (err) {
      if (console && console.error) {
        console.error(
          `[moduleRegistry] Failed to register module: ${key}`,
          err,
        );
      }
    }
  }

  get(moduleKey: string, exportName: string): unknown {
    const mod = this.modules[moduleKey];
    if (!mod) {
      console.warn(`[moduleRegistry] Module not found: ${moduleKey}`);
      return undefined;
    }
    return mod[exportName];
  }

  getOptional(moduleKey: string, exportName: string): unknown {
    return this.modules[moduleKey]?.[exportName];
  }

  call(moduleKey: string, exportName: string, ...args: unknown[]): unknown {
    const fn = this.get(moduleKey, exportName);
    if (typeof fn !== "function") {
      console.error(
        `[moduleRegistry] Export "${exportName}" in "${moduleKey}" is not callable`,
      );
      return undefined;
    }
    return fn(...args);
  }

  keys(): string[] {
    return Object.keys(this.modules);
  }

  getModule(key: string): Record<string, unknown> | undefined {
    return this.modules[key];
  }
}

export const moduleRegistry = new ModuleRegistryImpl();

// Expose to window.QwenPaw.modules (for plugin use)
// Set during initialization
if (typeof window !== "undefined") {
  if (!window.QwenPaw) {
    (window as any).QwenPaw = {};
  }

  Object.defineProperty(window.QwenPaw, "modules", {
    value: moduleRegistry.modules,
    configurable: true,
    enumerable: true,
  });
}
