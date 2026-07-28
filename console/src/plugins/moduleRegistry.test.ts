import { describe, expect, it, vi } from "vitest";
import { ModuleRegistryImpl } from "./moduleRegistry";

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
});
