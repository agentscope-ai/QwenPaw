import { beforeEach, describe, expect, it, vi } from "vitest";

import { pawappApi } from "../api/modules/pawapp";
import { buildPawAppManifestApps, mergePawAppDefinitions } from "./osApps";
import {
  resetPawAppManifestStoreForTests,
  syncPawAppManifests,
  usePawAppManifestStore,
} from "./pawAppManifestStore";

vi.mock("../api/modules/pawapp", () => ({
  pawappApi: { list: vi.fn() },
}));

const app = {
  id: "notes",
  name: "Notes",
  version: "1.0.0",
  description: "",
  author: "dev",
  category: "tools",
  icon: "",
  status: "installed",
  home_page: null,
  entry_page: "/apps/notes",
  dir: "/tmp/notes",
  settings: [],
  permissions: {},
  backends: {},
};

describe("PawApp manifest store", () => {
  beforeEach(() => {
    resetPawAppManifestStoreForTests();
    vi.mocked(pawappApi.list).mockReset();
  });

  it("deduplicates manifest refresh requests", async () => {
    vi.mocked(pawappApi.list).mockResolvedValue({ apps: [app], total: 1 });

    const first = usePawAppManifestStore.getState().refresh();
    const concurrent = usePawAppManifestStore.getState().refresh();
    expect(concurrent).toBe(first);
    await first;

    expect(pawappApi.list).toHaveBeenCalledTimes(1);
    expect(usePawAppManifestStore.getState().apps).toEqual([app]);
  });

  it("keeps cached apps and rejects when a refresh fails", async () => {
    syncPawAppManifests([app]);
    vi.mocked(pawappApi.list).mockRejectedValue(new Error("offline"));

    await expect(usePawAppManifestStore.getState().refresh()).rejects.toThrow(
      "offline",
    );

    expect(usePawAppManifestStore.getState()).toMatchObject({
      apps: [app],
      error: "offline",
      loading: false,
    });
  });

  it("updates installed apps locally without waiting for a list refresh", () => {
    syncPawAppManifests([app]);
    const updated = { ...app, version: "2.0.0" };

    usePawAppManifestStore.getState().upsert(updated);
    expect(usePawAppManifestStore.getState().apps).toEqual([updated]);

    usePawAppManifestStore.getState().remove(app.id);
    expect(usePawAppManifestStore.getState().apps).toEqual([]);
  });

  it("does not let an older refresh overwrite a confirmed local removal", async () => {
    syncPawAppManifests([app]);
    let resolveList!: (value: {
      apps: Array<typeof app>;
      total: number;
    }) => void;
    vi.mocked(pawappApi.list).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveList = resolve;
        }),
    );

    const refresh = usePawAppManifestStore.getState().refresh();
    usePawAppManifestStore.getState().remove(app.id);
    resolveList({ apps: [app], total: 1 });
    await refresh;

    expect(usePawAppManifestStore.getState().apps).toEqual([]);
  });

  it("builds a desktop entry before the app route is registered", () => {
    expect(buildPawAppManifestApps([app])).toMatchObject([
      {
        routeId: "pawapp:notes",
        source: "notes",
        entryPage: "/apps/notes",
        fallback: "Notes",
      },
    ]);
  });

  it("accepts manifests fetched by the classic App Center", () => {
    syncPawAppManifests([app]);

    expect(usePawAppManifestStore.getState()).toMatchObject({
      apps: [app],
      loaded: true,
      error: null,
    });
  });

  it("prefers manifest apps without dropping legacy route apps", () => {
    const routeApps = [
      {
        ...buildPawAppManifestApps([app])[0],
        routeId: "legacy-notes",
      },
      {
        ...buildPawAppManifestApps([{ ...app, id: "legacy" }])[0],
        routeId: "legacy-route",
      },
    ];

    expect(
      mergePawAppDefinitions([app], routeApps).map((item) => item.routeId),
    ).toEqual(["pawapp:notes", "legacy-route"]);
  });
});
