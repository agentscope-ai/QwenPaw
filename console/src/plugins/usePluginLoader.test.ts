// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  preloadPluginHostModules,
  waitForPluginReady,
  withTimeout,
} from "./usePluginLoader";

afterEach(() => {
  vi.useRealTimers();
});

describe("waitForPluginReady", () => {
  it("waits for a plugin readiness promise", async () => {
    let resolveReady: (() => void) | undefined;
    const ready = new Promise<void>((resolve) => {
      resolveReady = resolve;
    });
    const completed = vi.fn();

    const waiting = waitForPluginReady({ default: ready }).then(completed);
    await Promise.resolve();
    expect(completed).not.toHaveBeenCalled();

    resolveReady?.();
    await waiting;
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it("accepts plugins without an asynchronous initializer", async () => {
    await expect(waitForPluginReady({})).resolves.toBeUndefined();
  });
});

describe("preloadPluginHostModules", () => {
  it("loads declared modules before plugin execution", async () => {
    const loadModule = vi.fn(async (key: string) => ({ key }));
    window.QwenPaw = { loadModule } as unknown as Window["QwenPaw"];

    await preloadPluginHostModules({
      id: "plugin-a",
      name: "Plugin A",
      host_modules: ["Chat/config", "Settings/page"],
    });

    expect(loadModule).toHaveBeenCalledTimes(2);
    expect(loadModule).toHaveBeenCalledWith("Chat/config");
    expect(loadModule).toHaveBeenCalledWith("Settings/page");
  });

  it("does not warm modules when none are declared", async () => {
    const loadModule = vi.fn();
    window.QwenPaw = { loadModule } as unknown as Window["QwenPaw"];

    await preloadPluginHostModules({ id: "plugin-a", name: "Plugin A" });

    expect(loadModule).not.toHaveBeenCalled();
  });
});

describe("withTimeout", () => {
  it("rejects stalled plugin work and invokes timeout cleanup", async () => {
    vi.useFakeTimers();
    const onTimeout = vi.fn();
    const waiting = withTimeout(
      new Promise<void>(() => undefined),
      100,
      "plugin timed out",
      onTimeout,
    );

    const assertion = expect(waiting).rejects.toThrow("plugin timed out");
    await vi.advanceTimersByTimeAsync(100);
    await assertion;
    expect(onTimeout).toHaveBeenCalledTimes(1);
  });
});
