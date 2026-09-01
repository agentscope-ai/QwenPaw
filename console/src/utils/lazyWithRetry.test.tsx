/**
 * lazyWithRetry / lazyImportWithRetry wrap React.lazy with chunk-load
 * retries and plugin-registry overrides. Defects here break every page
 * navigation on a flaky network or hide plugin module patches.
 *
 * Note: real timers throughout — fake timers deadlock with Suspense's
 * async resolution (findByText polls on real timers). Retry delays are
 * fixed at 1s, so the retry test waits ~2s real time.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import React, { Suspense } from "react";

const registryMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("../plugins/moduleRegistry", () => ({
  moduleRegistry: registryMock,
}));

import { lazyWithRetry, lazyImportWithRetry } from "./lazyWithRetry";

const Dummy = () => React.createElement("div", null, "loaded-page");

function renderLazy(Comp: React.ComponentType<unknown>) {
  return render(
    React.createElement(
      Suspense,
      { fallback: React.createElement("div", null, "loading...") },
      React.createElement(Comp),
    ),
  );
}

describe("lazyWithRetry", () => {
  beforeEach(() => {
    registryMock.get.mockReset().mockReturnValue(undefined);
  });

  it("loads the module through React.lazy", async () => {
    const factory = vi.fn(() => Promise.resolve({ default: Dummy }));
    const Comp = lazyWithRetry(factory);
    const { findByText } = renderLazy(Comp);
    await expect(findByText("loaded-page")).resolves.toBeTruthy();
    expect(factory).toHaveBeenCalledTimes(1);
  });

  it("retries after chunk-load failures and eventually succeeds", async () => {
    const factory = vi
      .fn()
      .mockRejectedValueOnce(new Error("chunk gone"))
      .mockRejectedValueOnce(new Error("chunk gone"))
      .mockResolvedValueOnce({ default: Dummy });
    const Comp = lazyWithRetry(factory);
    const { findByText } = renderLazy(Comp);
    // Two failures => two 1s retry delays; generous timeout for CI
    await expect(
      findByText("loaded-page", {}, { timeout: 6000 }),
    ).resolves.toBeTruthy();
    expect(factory).toHaveBeenCalledTimes(3);
  }, 15000);

  it("uses the registry override when present (relative path key)", async () => {
    const Patched = () => React.createElement("div", null, "patched-by-plugin");
    registryMock.get.mockImplementation((key: string, name: string) =>
      key === "Settings/Debug/index" && name === "default"
        ? Patched
        : undefined,
    );
    const factory = vi.fn(() => Promise.resolve({ default: Dummy }));
    const Comp = lazyWithRetry(factory, "../../pages/Settings/Debug");
    const { findByText } = renderLazy(Comp);
    await expect(findByText("patched-by-plugin")).resolves.toBeTruthy();
    expect(registryMock.get).toHaveBeenCalledWith(
      "Settings/Debug/index",
      "default",
    );
  });

  it("normalizes bare-directory paths to the /index registry key", async () => {
    const Comp = lazyWithRetry(
      () => Promise.resolve({ default: Dummy }),
      "../pages/Settings/Debug/index.tsx",
    );
    const { findByText } = renderLazy(Comp);
    await expect(findByText("loaded-page")).resolves.toBeTruthy();
    expect(registryMock.get).toHaveBeenCalledWith(
      "Settings/Debug/index",
      "default",
    );
  });

  it("uses a non-relative module key verbatim", async () => {
    const Patched = () => React.createElement("div", null, "exact-key");
    registryMock.get.mockImplementation((key: string) =>
      key === "Custom/Module" ? Patched : undefined,
    );
    const Comp = lazyWithRetry(
      () => Promise.resolve({ default: Dummy }),
      "Custom/Module",
    );
    const { findByText } = renderLazy(Comp);
    await expect(findByText("exact-key")).resolves.toBeTruthy();
    expect(registryMock.get).toHaveBeenCalledWith("Custom/Module", "default");
  });

  it("falls back to the real module when the registry has nothing", async () => {
    const factory = () => Promise.resolve({ default: Dummy });
    const Comp = lazyWithRetry(factory, "Missing/Module");
    const { findByText } = renderLazy(Comp);
    await expect(findByText("loaded-page")).resolves.toBeTruthy();
  });
});

describe("lazyImportWithRetry", () => {
  beforeEach(() => {
    registryMock.get.mockReset().mockReturnValue(undefined);
  });

  it("throws a helpful error listing available keys for unknown paths", () => {
    expect(() => lazyImportWithRetry("../../pages/Nope/Missing")).toThrow(
      /No glob entry found/,
    );
  });

  it("resolves a registry override for a glob-backed path", async () => {
    // Use a lightweight real page module path so the glob lookup succeeds,
    // but the registry override wins without executing the heavy chunk.
    const Patched = () => React.createElement("div", null, "glob-patched");
    registryMock.get.mockImplementation((_key: string, name: string) =>
      name === "default" ? Patched : undefined,
    );
    const Comp = lazyImportWithRetry("../../pages/Settings/Debug");
    const { findByText } = renderLazy(Comp);
    await expect(
      findByText("glob-patched", {}, { timeout: 6000 }),
    ).resolves.toBeTruthy();
  }, 15000);
});
