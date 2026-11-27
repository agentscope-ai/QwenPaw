import { beforeEach, describe, expect, it } from "vitest";
import {
  clearPluginSdkDeclarations,
  getPluginSdkDeclaration,
  replacePluginSdkDeclarations,
  setPluginSdkDeclaration,
} from "./pluginSdk";

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
