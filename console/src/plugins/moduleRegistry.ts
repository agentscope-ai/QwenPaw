/**
 * moduleRegistry.ts
 *
 * Runtime module registry for plugin system monkey-patching
 *
 * How it works:
 * 1. Host app registers lazy import factories for all @patchable modules.
 * 2. Plugins load only the modules they need and patch the copied exports.
 * 3. Host code reads the registry so plugin-modified exports take effect.
 */

export type ModuleFactory = () => Promise<Record<string, unknown>>;

export interface ModuleRegistry {
  /**
   * Register a module (called by generated registerHostModules())
   */
  register(key: string, module: Record<string, unknown>): void;

  /** Register a lazy module factory without executing it. */
  registerFactory(key: string, factory: ModuleFactory): void;

  /** Load and register one module, deduplicating concurrent requests. */
  load(key: string): Promise<Record<string, unknown>>;

  /**
   * Get a module export value (for const/let/var types)
   */
  get(moduleKey: string, exportName: string): unknown;

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

export class ModuleRegistryImpl implements ModuleRegistry {
  private modules = new Map<string, Record<string, unknown>>();
  private factories = new Map<string, ModuleFactory>();
  private pendingLoads = new Map<string, Promise<Record<string, unknown>>>();

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

      this.modules.set(key, safeCopy);
    } catch (err) {
      if (console && console.error) {
        console.error(
          `[moduleRegistry] Failed to register module: ${key}`,
          err,
        );
      }
    }
  }

  registerFactory(key: string, factory: ModuleFactory): void {
    this.factories.set(key, factory);
  }

  load(key: string): Promise<Record<string, unknown>> {
    const loaded = this.modules.get(key);
    if (loaded) return Promise.resolve(loaded);

    const pending = this.pendingLoads.get(key);
    if (pending) return pending;

    const factory = this.factories.get(key);
    if (!factory) {
      return Promise.reject(
        new Error(`[moduleRegistry] Module factory not found: ${key}`),
      );
    }

    const loadPromise = factory()
      .then((module) => {
        this.register(key, module);
        return this.modules.get(key) ?? {};
      })
      .finally(() => {
        this.pendingLoads.delete(key);
      });
    this.pendingLoads.set(key, loadPromise);
    return loadPromise;
  }

  get(moduleKey: string, exportName: string): unknown {
    const mod = this.modules.get(moduleKey);
    if (!mod) {
      console.warn(`[moduleRegistry] Module not found: ${moduleKey}`);
      return undefined;
    }
    return mod[exportName];
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
    return Array.from(this.modules.keys());
  }

  getModule(key: string): Record<string, unknown> | undefined {
    return this.modules.get(key);
  }

  /**
   * Get all modules (for window.QwenPaw.modules)
   */
  getAllModules(): Record<string, Record<string, unknown>> {
    const result: Record<string, Record<string, unknown>> = {};
    for (const [key, mod] of this.modules) {
      result[key] = mod;
    }
    return result;
  }
}

export const moduleRegistry = new ModuleRegistryImpl();

// Expose to window.QwenPaw.modules (for plugin use)
// Set during initialization
if (typeof window !== "undefined") {
  if (!window.QwenPaw) {
    window.QwenPaw = {} as Window["QwenPaw"];
  }

  // Use Proxy for dynamic access, ensuring plugins always get latest module state
  Object.defineProperty(window.QwenPaw, "modules", {
    get() {
      return moduleRegistry.getAllModules();
    },
    configurable: true,
    enumerable: true,
  });
  window.QwenPaw.loadModule = (key: string) => moduleRegistry.load(key);
}
