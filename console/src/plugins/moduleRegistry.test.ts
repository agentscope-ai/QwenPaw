import { describe, expect, it, vi } from "vitest";
import { createModuleSnapshot, ModuleRegistryImpl } from "./moduleRegistry";

describe("ModuleRegistryImpl", () => {
  it("does not execute factories during registration", () => {
    const registry = new ModuleRegistryImpl();
    const factory = vi.fn(async () => ({ value: 1 }));

    registry.registerFactory("page", factory);

    expect(factory).not.toHaveBeenCalled();
    expect(registry.getModule("page")).toBeUndefined();
  });

  it("loads once and deduplicates concurrent requests", async () => {
    const registry = new ModuleRegistryImpl();
    const factory = vi.fn(async () => ({ value: 1 }));
    registry.registerFactory("page", factory);

    const [first, second] = await Promise.all([
      registry.load("page"),
      registry.load("page"),
    ]);

    expect(factory).toHaveBeenCalledTimes(1);
    expect(first).toBe(second);
    expect(first.value).toBe(1);
  });

  it("allows plugins to patch loaded exports", async () => {
    const registry = new ModuleRegistryImpl();
    registry.registerFactory("page", async () => ({ value: 1 }));

    const module = await registry.load("page");
    module.value = 2;

    expect(registry.get("page", "value")).toBe(2);
  });

  it("reports whether a lazy factory is registered", () => {
    const registry = new ModuleRegistryImpl();

    expect(registry.hasFactory("page")).toBe(false);
    registry.registerFactory("page", async () => ({ value: 1 }));
    expect(registry.hasFactory("page")).toBe(true);
  });

  it("warns when legacy sync access targets a lazy module", () => {
    const registry = new ModuleRegistryImpl();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    registry.registerFactory("page", async () => ({ value: 1 }));

    const modules = createModuleSnapshot(registry);

    expect(modules.page).toBeUndefined();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("entry.host_modules"),
    );
    warn.mockRestore();
  });
});
