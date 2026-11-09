import { afterEach, describe, expect, it, vi } from "vitest";
import {
  settingsSearchRegistry as registry,
  type SettingsSearchItem,
} from "./settingsSearch";
import { removePluginRuntime } from "./pluginRuntimeCleanup";

const item: SettingsSearchItem = {
  id: "timeout",
  routeId: "example.settings",
  label: "Timeout",
  target: { targetId: "example.timeout" },
};

afterEach(() => {
  registry.removeBySource("example");
  registry.removeBySource("other");
});

describe("plugin settings search registrations", () => {
  it("keeps a stable snapshot until a registration changes", () => {
    const before = registry.getSnapshot();
    expect(registry.getSnapshot()).toBe(before);
    const listener = vi.fn();
    const unsubscribe = registry.subscribe(listener);
    const registration = registry.register("example", [item]);
    expect(registry.getSnapshot()).not.toBe(before);
    expect(listener).toHaveBeenCalledTimes(1);
    registration.dispose();
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("isolates plugin ids and ignores a superseded registration's disposer", () => {
    const first = registry.register("example", [item]);
    registry.register("other", [item]);
    registry.register("example", [{ ...item, label: "New timeout" }]);
    first.dispose();
    expect(registry.getSnapshot().map(({ item }) => item.label)).toEqual([
      "New timeout",
      "Timeout",
    ]);
    registry.removeBySource("example");
    expect(registry.getSnapshot().map(({ pluginId }) => pluginId)).toEqual([
      "other",
    ]);
  });

  it("removes search metadata with every other plugin runtime registration", () => {
    registry.register("example", [item]);
    removePluginRuntime("example");
    expect(registry.getSnapshot()).toHaveLength(0);
  });
});
