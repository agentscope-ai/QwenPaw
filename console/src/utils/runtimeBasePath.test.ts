import { afterEach, describe, expect, it, vi } from "vitest";
import { getConsoleAssetUrl, getRuntimeBasePath } from "./runtimeBasePath";

describe("runtime base path", () => {
  afterEach(() => {
    delete window.__qpBase;
    vi.unstubAllEnvs();
  });

  it("defaults to the existing root deployment", () => {
    expect(getRuntimeBasePath()).toBe("");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe("/logo-light.svg");
  });

  it("keeps root asset URLs absolute with a relative Vite build base", () => {
    vi.stubEnv("BASE_URL", "./");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe("/logo-light.svg");
  });

  it("uses the server-injected prefix for public assets", () => {
    window.__qpBase = "/app/qwenpaw/web";
    expect(getRuntimeBasePath()).toBe("/app/qwenpaw/web");
    expect(getConsoleAssetUrl("logo-light.svg")).toBe(
      "/app/qwenpaw/web/logo-light.svg",
    );
  });

  it("normalizes a trailing slash and rejects malformed injected values", () => {
    window.__qpBase = "/app/qwenpaw/web/";
    expect(getRuntimeBasePath()).toBe("/app/qwenpaw/web");
    window.__qpBase = "https://attacker.example/";
    expect(getRuntimeBasePath()).toBe("");
    window.__qpBase = "/app/../admin";
    expect(getRuntimeBasePath()).toBe("");
    window.__qpBase = "//attacker.example";
    expect(getRuntimeBasePath()).toBe("");
    window.__qpBase = "/app/%2e%2e/admin";
    expect(getRuntimeBasePath()).toBe("");
  });
});
