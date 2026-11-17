import { beforeEach, describe, expect, it } from "vitest";
import {
  clearPluginSdkDeclarations,
  getPluginSdkDeclaration,
  meetsMinVersion,
  replacePluginSdkDeclarations,
  setPluginSdkDeclaration,
} from "./pluginSdk";

describe("meetsMinVersion", () => {
  it("compares numerically instead of lexically", () => {
    expect(meetsMinVersion("1.10.0", "1.9.0")).toBe(true);
    expect(meetsMinVersion("1.9.0", "1.10.0")).toBe(false);
  });

  it("treats an equal version as meeting the minimum", () => {
    expect(meetsMinVersion("1.2.0", "1.2.0")).toBe(true);
  });

  it("ignores prerelease suffixes", () => {
    expect(meetsMinVersion("1.2.0-beta.4", "1.2.0")).toBe(true);
  });

  it("fills missing segments with zero", () => {
    expect(meetsMinVersion("1.2", "1.2.0")).toBe(true);
  });

  it("accepts the PEP 440 spellings the backend accepts", () => {
    expect(meetsMinVersion("v1.2.0", "1.2.0")).toBe(true);
    expect(meetsMinVersion("V1.2.0", "1.2.0")).toBe(true);
    expect(meetsMinVersion("  1.2.0  ", "1.2.0")).toBe(true);
    expect(meetsMinVersion("v1.10.0", "1.9.0")).toBe(true);
    expect(meetsMinVersion("v1.1.0", "1.2.0")).toBe(false);
  });
});

describe("plugin SDK declarations", () => {
  beforeEach(() => {
    clearPluginSdkDeclarations();
  });

  it("indexes declarations by plugin and skips rows without a version", () => {
    replacePluginSdkDeclarations([
      { id: "a", sdkVersion: "1.2.0", sdkCapabilities: ["themeTokens"] },
      { id: "b" },
    ]);
    expect(getPluginSdkDeclaration("a")?.capabilities).toEqual(["themeTokens"]);
    expect(getPluginSdkDeclaration("b")).toBeUndefined();
  });

  it("copies capabilities so later caller mutation cannot leak in", () => {
    const capabilities = ["themeTokens"];
    setPluginSdkDeclaration("a", { version: "1.2.0", capabilities });
    capabilities.push("harnesses");
    expect(getPluginSdkDeclaration("a")?.capabilities).toEqual(["themeTokens"]);
  });

  it("clears declarations that a later listing no longer reports", () => {
    setPluginSdkDeclaration("a", { version: "1.2.0", capabilities: [] });
    replacePluginSdkDeclarations([{ id: "b", sdkVersion: "1.0.0" }]);
    expect(getPluginSdkDeclaration("a")).toBeUndefined();
    expect(getPluginSdkDeclaration("b")?.version).toBe("1.0.0");
  });
});
