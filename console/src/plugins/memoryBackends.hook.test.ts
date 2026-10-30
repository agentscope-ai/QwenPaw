import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api from "../api";
import {
  memoryBackendNamespace,
  memoryBackendRegistry,
  useMemoryBackends,
} from "./memoryBackends";

// Each test uses its own plugin id and backend id so the module level
// registry singleton cannot leak state between cases.
const find = (id: string) =>
  memoryBackendRegistry.getSnapshot().find((item) => item.id === id);

const disposers: Array<{ dispose(): void }> = [];
const plugins: string[] = [];

const usePlugin = (pluginId: string) => {
  plugins.push(pluginId);
  return pluginId;
};

vi.mock("../api", () => ({
  default: { listMemoryBackends: vi.fn() },
}));

describe("memoryBackendRegistry ownership", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listMemoryBackends).mockResolvedValue([]);
  });

  afterEach(() => {
    while (disposers.length) disposers.pop()?.dispose();
    while (plugins.length) memoryBackendRegistry.removeBySource(plugins.pop()!);
  });

  it("refuses to overwrite a backend owned by another source", () => {
    expect(() =>
      memoryBackendRegistry.register("hijack-plugin", {
        id: "REMELIGHT",
        label: "Hijacked",
      }),
    ).toThrow("Memory backend 'remelight' is already registered by core");
    expect(find("remelight")?.label).toBe("ReMe Light");
  });

  it("lets the owning plugin replace its own registration", () => {
    const pluginId = usePlugin("own-plugin");
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "OWN-BACKEND",
        label: "v1",
      }),
    );
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "OWN-BACKEND",
        label: "v2",
      }),
    );

    expect(find("own-backend")?.label).toBe("v2");
    expect(find("own-backend")?.source).toBe(`plugin:${pluginId}`);
  });

  it("normalises the backend id before registering", () => {
    const pluginId = usePlugin("case-plugin");
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "  MiXeD-Case  ",
        label: "Mixed",
      }),
    );

    expect(find("mixed-case")?.label).toBe("Mixed");
    expect(find("  MiXeD-Case  ")).toBeUndefined();
  });

  it("keeps an entry alive after a superseded registration is disposed", () => {
    const pluginId = usePlugin("supersede-plugin");
    const first = memoryBackendRegistry.register(pluginId, {
      id: "SUPERSEDED",
      label: "first",
    });
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "SUPERSEDED",
        label: "second",
      }),
    );

    first.dispose();

    // The stale disposer no longer owns the slot, so it must not remove it.
    expect(find("superseded")?.label).toBe("second");
  });

  it("removes only the entries contributed by one plugin", () => {
    const target = usePlugin("remove-target");
    const keeper = usePlugin("remove-keeper");
    memoryBackendRegistry.register(target, { id: "DROP-ONE", label: "one" });
    memoryBackendRegistry.register(target, { id: "DROP-TWO", label: "two" });
    memoryBackendRegistry.register(keeper, { id: "KEEP-ME", label: "keep" });

    memoryBackendRegistry.removeBySource(target);

    expect(find("drop-one")).toBeUndefined();
    expect(find("drop-two")).toBeUndefined();
    expect(find("keep-me")?.label).toBe("keep");
    expect(find("remelight")).toBeDefined();
    expect(find("none")).toBeDefined();
  });

  it("tolerates removing a plugin that registered nothing", () => {
    const before = memoryBackendRegistry.getSnapshot();

    memoryBackendRegistry.removeBySource("never-registered");

    expect(memoryBackendRegistry.getSnapshot()).toBe(before);
  });
});

describe("memoryBackendRegistry availability sync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listMemoryBackends).mockResolvedValue([]);
  });

  afterEach(() => {
    while (disposers.length) disposers.pop()?.dispose();
    while (plugins.length) memoryBackendRegistry.removeBySource(plugins.pop()!);
  });

  it("adds a server side backend the frontend never registered", () => {
    memoryBackendRegistry.syncAvailable([
      { id: "SERVER-ONLY", label: "Server Only", available: true },
    ]);

    expect(find("server-only")?.label).toBe("Server Only");
    expect(find("server-only")?.available).toBe(true);
  });

  it("treats a missing availability flag as available", () => {
    memoryBackendRegistry.syncAvailable([{ id: "NO-FLAG", label: "No Flag" }]);

    expect(find("no-flag")?.available).toBe(true);
  });

  it("keeps one snapshot instance when nothing changed", () => {
    const payload = [{ id: "STABLE-ONE", label: "Stable", available: true }];
    memoryBackendRegistry.syncAvailable(payload);
    const first = memoryBackendRegistry.getSnapshot();

    memoryBackendRegistry.syncAvailable(payload);

    // useSyncExternalStore relies on a stable reference to skip re-renders.
    expect(memoryBackendRegistry.getSnapshot()).toBe(first);
  });

  it("flips an existing backend to unavailable without losing ownership", () => {
    const pluginId = usePlugin("flip-plugin");
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "FLIP-ME",
        label: "Flip",
        available: true,
      }),
    );

    memoryBackendRegistry.syncAvailable([
      { id: "flip-me", label: "Flip", available: false },
    ]);

    expect(find("flip-me")?.available).toBe(false);
    expect(find("flip-me")?.source).toBe(`plugin:${pluginId}`);
  });

  it("applies the known availability to a registration made later", () => {
    memoryBackendRegistry.syncAvailable([
      { id: "later-backend", label: "Later", available: false },
    ]);
    const pluginId = usePlugin("later-plugin");
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "LATER-BACKEND",
        label: "Later",
        available: true,
      }),
    );

    // The server already reported this backend missing, so the optimistic
    // default from the extension must not win.
    expect(find("later-backend")?.available).toBe(false);
  });

  it("notifies subscribers on change and stops after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = memoryBackendRegistry.subscribe(listener);

    memoryBackendRegistry.syncAvailable([
      { id: "notify-one", label: "Notify", available: true },
    ]);
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    memoryBackendRegistry.syncAvailable([
      { id: "notify-two", label: "Notify", available: true },
    ]);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("memoryBackendNamespace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listMemoryBackends).mockResolvedValue([]);
  });

  afterEach(() => {
    while (disposers.length) disposers.pop()?.dispose();
    while (plugins.length) memoryBackendRegistry.removeBySource(plugins.pop()!);
  });

  it("routes plugin registrations into the shared registry", () => {
    const pluginId = usePlugin("namespace-plugin");
    const ConfigComponent = () => null;

    disposers.push(
      memoryBackendNamespace.register(pluginId, {
        id: "NAMESPACED",
        label: "Namespaced",
        ConfigComponent,
      }),
    );

    expect(find("namespaced")?.ConfigComponent).toBe(ConfigComponent);
    expect(find("namespaced")?.source).toBe(`plugin:${pluginId}`);
  });
});

describe("useMemoryBackends", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listMemoryBackends).mockResolvedValue([]);
  });

  afterEach(() => {
    while (disposers.length) disposers.pop()?.dispose();
    while (plugins.length) memoryBackendRegistry.removeBySource(plugins.pop()!);
  });

  it("exposes the registry snapshot and refreshes on registration", async () => {
    const { result, unmount } = renderHook(() => useMemoryBackends());
    await waitFor(() =>
      expect(api.listMemoryBackends).toHaveBeenCalledTimes(1),
    );
    const initial = result.current;
    expect(initial.some((item) => item.id === "remelight")).toBe(true);

    act(() => {
      disposers.push(
        memoryBackendRegistry.register(usePlugin("live-plugin"), {
          id: "LIVE-BACKEND",
          label: "Live",
        }),
      );
    });

    expect(result.current.some((item) => item.id === "live-backend")).toBe(
      true,
    );
    expect(result.current.length).toBe(initial.length + 1);
    unmount();
  });

  it("adopts the availability reported by the server on mount", async () => {
    const pluginId = usePlugin("mount-plugin");
    disposers.push(
      memoryBackendRegistry.register(pluginId, {
        id: "MOUNT-BACKEND",
        label: "Mount",
      }),
    );
    vi.mocked(api.listMemoryBackends).mockResolvedValue([
      {
        id: "mount-backend",
        label: "Mount",
        source: "plugin:mount-plugin",
        available: false,
      },
    ]);

    const { result, unmount } = renderHook(() => useMemoryBackends());

    await waitFor(() => expect(find("mount-backend")?.available).toBe(false));
    expect(
      result.current.find((item) => item.id === "mount-backend")?.available,
    ).toBe(false);
    unmount();
  });

  it("keeps working when the availability probe fails", async () => {
    vi.mocked(api.listMemoryBackends).mockRejectedValue(
      new Error("backend list unavailable"),
    );

    const { result, unmount } = renderHook(() => useMemoryBackends());

    await waitFor(() =>
      expect(api.listMemoryBackends).toHaveBeenCalledTimes(1),
    );
    // The failure is swallowed so the settings page still renders its cores.
    expect(result.current.some((item) => item.id === "none")).toBe(true);
    unmount();
  });
});
