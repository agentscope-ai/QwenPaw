// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { pluginSystem } from "./hostExternals";
import { removePluginRuntime } from "./pluginRuntimeCleanup";
import { chatExtensions } from "./registry/chatExtensions";
import { menuRegistry, routeRegistry, slotRegistry } from "./registry/store";

const PLUGIN_ID = "cleanup-test";

beforeEach(() => {
  removePluginRuntime(PLUGIN_ID);
  menuRegistry.__resetForTests();
  routeRegistry.__resetForTests();
  slotRegistry.__resetForTests();
  chatExtensions.__resetForTests();
});

function registerEverySurface(): void {
  menuRegistry.add(PLUGIN_ID, { id: "plugin.menu", label: "Plugin" });
  routeRegistry.add(PLUGIN_ID, {
    id: "plugin.route",
    path: "/plugin",
    component: () => null,
  });
  slotRegistry.fill(PLUGIN_ID, "header.left", () => null);
  pluginSystem.addRoutes(PLUGIN_ID, [
    { path: "/legacy", component: () => null, label: "Legacy" },
  ]);
  chatExtensions.setScalar(PLUGIN_ID, "sender.placeholder", "Plugin input");
}

function expectPluginRegistrationCount(expected: number): void {
  expect(
    menuRegistry.snapshot().filter((item) => item.id === "plugin.menu"),
  ).toHaveLength(expected);
  expect(
    routeRegistry.snapshot().filter((route) => route.source === PLUGIN_ID),
  ).toHaveLength(expected);
  expect(
    slotRegistry.snapshotAll().filter((slot) => slot.source === PLUGIN_ID),
  ).toHaveLength(expected);
  expect(
    pluginSystem.getRoutes().filter((route) => route.path === "/legacy"),
  ).toHaveLength(expected);
  const chatPluginId =
    chatExtensions.getScalarSnapshot()["sender.placeholder"]?.pluginId;
  if (expected === 1) expect(chatPluginId).toBe(PLUGIN_ID);
  else expect(chatPluginId).toBeUndefined();
}

describe("plugin runtime cleanup", () => {
  it("removes all host-managed registrations", () => {
    registerEverySurface();

    removePluginRuntime(PLUGIN_ID);

    expectPluginRegistrationCount(0);
  });
});
