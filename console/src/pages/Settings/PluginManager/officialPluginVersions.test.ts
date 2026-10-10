import { describe, expect, it } from "vitest";
import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import {
  getOfficialPluginVersions,
  groupOfficialPlugins,
  resolveOfficialPluginSelection,
} from "./officialPluginVersions";

function makeEntry(
  pluginId: string,
  version: string,
  overrides: Partial<OfficialPluginCatalogEntry> = {},
): OfficialPluginCatalogEntry {
  return {
    id: `${pluginId}-${version}`,
    plugin_id: pluginId,
    name: pluginId,
    description: "",
    version,
    author: "AgentScope",
    kind: "tool",
    size: "1 MB",
    sha256: "sha",
    install_url: `https://example.com/${pluginId}-${version}.zip`,
    installed: false,
    upgrade_available: false,
    ...overrides,
  };
}

describe("officialPluginVersions", () => {
  it("groups plugin releases and selects the newest catalog version", () => {
    const groups = groupOfficialPlugins([
      makeEntry("creator", "1.0.3"),
      makeEntry("creator", "1.1.1"),
      makeEntry("creator", "1.0.1"),
      makeEntry("creator", "1.1.0"),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].versions.map((entry) => entry.version)).toEqual([
      "1.1.1",
      "1.1.0",
      "1.0.3",
      "1.0.1",
    ]);
    expect(groups[0].defaultVersion.version).toBe("1.1.1");
  });

  it("groups same-name releases even when their package IDs changed", () => {
    const groups = groupOfficialPlugins([
      makeEntry("qwenpaw-data", "0.1.1", { name: "QwenPaw-Data" }),
      makeEntry("datapaw", "0.2.0", { name: "QwenPaw-Data" }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].versions.map((entry) => entry.plugin_id)).toEqual([
      "datapaw",
      "qwenpaw-data",
    ]);
    expect(groups[0].defaultVersion.version).toBe("0.2.0");
  });

  it("preserves plugin group order and sorts pre-release versions", () => {
    const groups = groupOfficialPlugins([
      makeEntry("creator", "2.0.0b1"),
      makeEntry("computer-use", "1.0.0"),
      makeEntry("creator", "2.0.0"),
      makeEntry("computer-use", "1.0.1"),
    ]);

    expect(groups.map((group) => group.key)).toEqual([
      "name:creator",
      "name:computer-use",
    ]);
    expect(groups[0].versions.map((entry) => entry.version)).toEqual([
      "2.0.0",
      "2.0.0b1",
    ]);
    expect(groups[1].defaultVersion.version).toBe("1.0.1");
  });

  it("selects the latest catalog version when an update is available", () => {
    const installed = {
      installed: true,
      installed_version: "1.1.0",
    };
    const group = groupOfficialPlugins([
      makeEntry("demo", "1.2.0", installed),
      makeEntry("demo", "1.1.0", installed),
      makeEntry("demo", "1.0.0", installed),
    ])[0];

    expect(group.installedVersion).toBe("1.1.0");
    expect(getOfficialPluginVersions(group)).toEqual([
      "1.2.0",
      "1.1.0",
      "1.0.0",
    ]);
    expect(resolveOfficialPluginSelection(group)).toMatchObject({
      selectedVersion: "1.2.0",
      action: "update",
    });
    expect(resolveOfficialPluginSelection(group, "1.2.0").action).toBe(
      "update",
    );
    expect(resolveOfficialPluginSelection(group, "1.0.0").action).toBe(
      "update",
    );
  });

  it("keeps the latest installed version selected until another is chosen", () => {
    const installed = {
      installed: true,
      installed_version: "1.2.0",
    };
    const group = groupOfficialPlugins([
      makeEntry("demo", "1.2.0", installed),
      makeEntry("demo", "1.1.0", installed),
    ])[0];

    expect(resolveOfficialPluginSelection(group)).toMatchObject({
      selectedVersion: "1.2.0",
      action: "current",
    });
    expect(resolveOfficialPluginSelection(group, "1.1.0")).toMatchObject({
      selectedVersion: "1.1.0",
      action: "install",
    });
  });

  it("keeps an installed version that is absent from the catalog selectable", () => {
    const group = groupOfficialPlugins([
      makeEntry("demo", "1.0.0", {
        installed: true,
        installed_version: "1.1.0",
      }),
    ])[0];

    expect(getOfficialPluginVersions(group)).toEqual(["1.1.0", "1.0.0"]);
    expect(resolveOfficialPluginSelection(group)).toMatchObject({
      selectedVersion: "1.1.0",
      catalogEntry: undefined,
      action: "current",
    });
    expect(resolveOfficialPluginSelection(group, "1.0.0").action).toBe(
      "install",
    );
  });
});
