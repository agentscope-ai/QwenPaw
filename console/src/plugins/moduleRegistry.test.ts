// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { moduleRegistry } from "./moduleRegistry";

describe("moduleRegistry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns undefined without warning when an optional module is absent", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(
      moduleRegistry.getOptional("test.optional-missing", "default"),
    ).toBeUndefined();
    expect(warn).not.toHaveBeenCalled();
  });

  it("returns an export from an optional registered module", () => {
    const value = () => "registered";
    moduleRegistry.register("test.optional-present", { default: value });

    expect(moduleRegistry.getOptional("test.optional-present", "default")).toBe(
      value,
    );
  });

  it("returns undefined without warning when an optional export is absent", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    moduleRegistry.register("test.optional-export-missing", {
      named: "value",
    });

    expect(
      moduleRegistry.getOptional("test.optional-export-missing", "default"),
    ).toBeUndefined();
    expect(warn).not.toHaveBeenCalled();
  });

  it("retains a plugin's route registration across frontend evaluations", () => {
    const pluginId = "test.mcp-management";
    const register = () => {
      const state = (window.QwenPaw.modules[pluginId] ??= {});
      const previous = state.management as { dispose: () => void } | undefined;
      previous?.dispose();
      const management = { dispose: vi.fn() };
      state.management = management;
      return management;
    };

    try {
      const first = register();
      const second = register();
      expect(first.dispose).toHaveBeenCalledOnce();
      expect(window.QwenPaw.modules[pluginId].management).toBe(second);
      expect(second.dispose).not.toHaveBeenCalled();
    } finally {
      delete window.QwenPaw.modules[pluginId];
    }
  });

  it("keeps strict lookup diagnostics for a required missing module", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    expect(
      moduleRegistry.get("test.required-missing", "default"),
    ).toBeUndefined();
    expect(warn).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      "[moduleRegistry] Module not found: test.required-missing",
    );
  });
});
