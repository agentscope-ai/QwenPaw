import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_DOCK_APPS, normalizeDockApps, useOsDock } from "./osDockStore";

beforeEach(() => useOsDock.setState({ pinned: [...DEFAULT_DOCK_APPS] }));

describe("osDockStore", () => {
  it("pins without duplicates and preserves order", () => {
    useOsDock.getState().pin("core.skills");
    useOsDock.getState().pin("core.skills", 0);
    expect(useOsDock.getState().pinned).toEqual([
      ...DEFAULT_DOCK_APPS,
      "core.skills",
    ]);
  });

  it("moves and unpins shortcuts", () => {
    useOsDock.getState().move("os.store", "core.chat");
    expect(useOsDock.getState().pinned).toEqual([
      "os.store",
      "core.chat",
      "core.inbox",
    ]);
    useOsDock.getState().unpin("core.chat");
    expect(useOsDock.getState().pinned).toEqual(["os.store", "core.inbox"]);
  });

  it("purges confirmed removals only", () => {
    useOsDock.getState().pin("gone.app");
    useOsDock.getState().purge(new Set(["gone.app", "core.inbox"]));
    expect(useOsDock.getState().pinned).toEqual(["core.chat", "os.store"]);
  });

  it("normalizes persisted values while preserving an empty Dock", () => {
    expect(
      normalizeDockApps(["core.chat", 1, "core.chat", "os.store"]),
    ).toEqual(["core.chat", "os.store"]);
    expect(normalizeDockApps([])).toEqual([]);
    expect(normalizeDockApps(undefined)).toEqual(DEFAULT_DOCK_APPS);
  });
});
