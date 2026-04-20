/**
 * moduleRegistry.ts
 *
 * 运行时模块注册表，用于插件系统的模块 monkey-patching
 *
 * 工作原理：
 * 1. 宿主应用启动时调用 moduleRegistry.register() 注册所有 @patchable 模块
 * 2. 插件通过 window.QwenPaw.modules 访问并修改模块导出
 * 3. 宿主代码通过 moduleRegistry.get/call 访问模块，确保使用插件修改后的版本
 */

export interface ModuleRegistry {
  /**
   * 注册模块（由生成的 registerHostModules() 调用）
   */
  register(key: string, module: Record<string, unknown>): void;

  /**
   * 获取模块的某个导出值（用于 const/let/var 类型）
   */
  get(moduleKey: string, exportName: string): unknown;

  /**
   * 调用模块的某个导出函数（用于 function/class 类型）
   */
  call(moduleKey: string, exportName: string, ...args: unknown[]): unknown;

  /**
   * 获取所有已注册的模块 key
   */
  keys(): string[];

  /**
   * 获取整个模块对象（供插件使用）
   */
  getModule(key: string): Record<string, unknown> | undefined;
}

class ModuleRegistryImpl implements ModuleRegistry {
  private modules = new Map<string, Record<string, unknown>>();

  register(key: string, module: Record<string, unknown>): void {
    // 安全地复制模块导出，避免 ES Module namespace 的特殊属性导致错误
    const safeCopy: Record<string, unknown> = {};

    try {
      // 只复制可枚举的自有属性
      for (const exportName of Object.keys(module)) {
        try {
          const descriptor = Object.getOwnPropertyDescriptor(module, exportName);
          if (descriptor && descriptor.enumerable && !descriptor.get) {
            // 只复制普通属性，跳过 getter/setter
            safeCopy[exportName] = module[exportName];
          }
        } catch (e) {
          // 跳过无法访问的属性
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
        console.error(`[moduleRegistry] Failed to register module: ${key}`, err);
      }
    }
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
   * 获取所有模块（供 window.QwenPaw.modules 使用）
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

// 暴露到 window.QwenPaw.modules（供插件使用）
// 初始化时设置
if (typeof window !== "undefined") {
  if (!window.QwenPaw) {
    (window as any).QwenPaw = {};
  }

  // 使用 Proxy 实现动态访问，确保插件总是能获取到最新的模块状态
  Object.defineProperty(window.QwenPaw, "modules", {
    get() {
      return (moduleRegistry as any).getAllModules();
    },
    configurable: true,
    enumerable: true,
  });
}
