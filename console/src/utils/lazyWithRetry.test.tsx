/**
 * lazyWithRetry / lazyImportWithRetry wrap React.lazy with chunk-load
 * recovery and plugin-registry overrides. Defects here break every page
 * navigation on a flaky network or hide plugin module patches.
 *
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import React from "react";
import { ChunkRecoverySuspense } from "../components/ChunkRecoverySuspense";

const registryMock = vi.hoisted(() => ({
  get: vi.fn(),
  getOptional: vi.fn(),
}));

vi.mock("../plugins/moduleRegistry", () => ({
  moduleRegistry: registryMock,
}));

vi.mock("../pages/Settings/Debug", () => ({
  default: () => React.createElement("div", null, "base-debug-page"),
}));

import { lazyWithRetry, lazyImportWithRetry } from "./lazyWithRetry";
import { getFrontendBuildId } from "./chunkRecovery";

const Dummy = () => React.createElement("div", null, "loaded-page");

function renderLazy(Comp: React.ComponentType<unknown>) {
  return render(
    React.createElement(
      ChunkRecoverySuspense,
      { fallback: React.createElement("div", null, "loading...") },
      React.createElement(Comp),
    ),
  );
}

describe("lazyWithRetry", () => {
  beforeEach(() => {
    registryMock.get.mockReset().mockReturnValue(undefined);
    registryMock.getOptional.mockReset().mockReturnValue(undefined);
  });

  it("loads the module through React.lazy", async () => {
    const factory = vi.fn(() => Promise.resolve({ default: Dummy }));
    const Comp = lazyWithRetry(factory);
    const { findByText } = renderLazy(Comp);
    await expect(findByText("loaded-page")).resolves.toBeTruthy();
    expect(factory).toHaveBeenCalledTimes(1);
  });

  it("uses the registry override when present (relative path key)", async () => {
    const Patched = () => React.createElement("div", null, "patched-by-plugin");
    registryMock.getOptional.mockImplementation((key: string, name: string) =>
      key === "Settings/Debug/index" && name === "default"
        ? Patched
        : undefined,
    );
    const factory = vi.fn(() => Promise.resolve({ default: Dummy }));
    const Comp = lazyWithRetry(factory, "../../pages/Settings/Debug");
    const { findByText } = renderLazy(Comp);
    await expect(findByText("patched-by-plugin")).resolves.toBeTruthy();
    expect(factory).not.toHaveBeenCalled();
    expect(registryMock.getOptional).toHaveBeenCalledWith(
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
    expect(registryMock.getOptional).toHaveBeenCalledWith(
      "Settings/Debug/index",
      "default",
    );
  });

  it("uses a non-relative module key verbatim", async () => {
    const Patched = () => React.createElement("div", null, "exact-key");
    registryMock.getOptional.mockImplementation((key: string) =>
      key === "Custom/Module" ? Patched : undefined,
    );
    const Comp = lazyWithRetry(
      () => Promise.resolve({ default: Dummy }),
      "Custom/Module",
    );
    const { findByText } = renderLazy(Comp);
    await expect(findByText("exact-key")).resolves.toBeTruthy();
    expect(registryMock.getOptional).toHaveBeenCalledWith(
      "Custom/Module",
      "default",
    );
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
    registryMock.getOptional.mockReset().mockReturnValue(undefined);
  });

  it("throws a helpful error listing available keys for unknown paths", () => {
    expect(() => lazyImportWithRetry("../../pages/Nope/Missing")).toThrow(
      /No glob entry found/,
    );
  });

  it("resolves a registry override for a glob-backed path", async () => {
    // Keep the real glob path while isolating the page's application dependencies.
    const Patched = () => React.createElement("div", null, "glob-patched");
    registryMock.getOptional.mockImplementation((_key: string, name: string) =>
      name === "default" ? Patched : undefined,
    );
    const Comp = lazyImportWithRetry("../../pages/Settings/Debug");
    const { findByText } = renderLazy(Comp);
    await expect(
      findByText("glob-patched", {}, { timeout: 6000 }),
    ).resolves.toBeTruthy();
  }, 15000);
});

describe("reload allowance after a healthy page", () => {
  const reloadKey = "qwenpaw:chunk-reload-build";

  beforeEach(() => {
    registryMock.get.mockReset().mockReturnValue(undefined);
    sessionStorage.clear();
    vi.useFakeTimers();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("restores the allowance only after 60 seconds of committed content", async () => {
    const guard = JSON.stringify({
      build: getFrontendBuildId(),
      attempts: 2,
    });
    sessionStorage.setItem(reloadKey, guard);
    const Page = lazyWithRetry(() => Promise.resolve({ default: Dummy }));
    await act(async () => {
      renderLazy(Page);
    });
    expect(screen.getByText("loaded-page")).toBeVisible();
    await act(async () => {
      vi.advanceTimersByTime(59_999);
    });
    expect(sessionStorage.getItem(reloadKey)).toBe(guard);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(sessionStorage.getItem(reloadKey)).toBeNull();
  });
});
