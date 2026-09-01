/**
 * osPluginStore — install/uninstall/reset lifecycle and the persist migrate
 * hook that merges catalog apps into legacy persisted state.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { OS_APPS } from "./osApps";
import { useOsPlugins } from "./osPluginStore";

const DEFAULT_IDS = OS_APPS.map((a) => a.routeId);

describe("osPluginStore", () => {
  beforeEach(() => {
    useOsPlugins.setState({ installed: [...DEFAULT_IDS] });
  });

  it("starts with every catalog app installed", () => {
    expect(useOsPlugins.getState().installed).toEqual(DEFAULT_IDS);
  });

  it("install is idempotent", () => {
    const store = useOsPlugins.getState();
    store.uninstall(DEFAULT_IDS[0]);
    store.install(DEFAULT_IDS[0]);
    const once = useOsPlugins.getState().installed;
    store.install(DEFAULT_IDS[0]);
    expect(useOsPlugins.getState().installed).toBe(once);
  });

  it("uninstall removes only the given app", () => {
    useOsPlugins.getState().uninstall(DEFAULT_IDS[0]);
    const installed = useOsPlugins.getState().installed;
    expect(installed).not.toContain(DEFAULT_IDS[0]);
    expect(installed).toContain(DEFAULT_IDS[1]);
  });

  it("installAll restores the full catalog (factory reset)", () => {
    const store = useOsPlugins.getState();
    store.uninstall(DEFAULT_IDS[0]);
    store.uninstall(DEFAULT_IDS[1]);
    store.installAll();
    expect(useOsPlugins.getState().installed).toEqual(DEFAULT_IDS);
  });

  it("persist migrate merges legacy entries with the catalog", () => {
    const persisted = useOsPlugins.persist;
    const migrate = persisted.getOptions().migrate as (
      persistedState: unknown,
      version: number,
    ) => unknown;
    const migrated = migrate({ installed: ["legacy.app"] }, 1) as {
      installed: string[];
    };
    expect(migrated.installed).toContain("legacy.app");
    for (const id of DEFAULT_IDS) {
      expect(migrated.installed).toContain(id);
    }
    // no duplicates after merging
    expect(new Set(migrated.installed).size).toBe(migrated.installed.length);
  });

  it("persist migrate handles a missing persisted payload", () => {
    const migrate = useOsPlugins.persist.getOptions().migrate as (
      persistedState: unknown,
      version: number,
    ) => unknown;
    const migrated = migrate(undefined, 1) as { installed: string[] };
    expect(migrated.installed).toEqual(DEFAULT_IDS);
  });
});
