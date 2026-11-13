import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  useSessionTerminalOpen,
  useTerminalSurfaceStore,
} from "./terminalSurfaceStore";

describe("terminalSurfaceStore", () => {
  beforeEach(() => {
    useTerminalSurfaceStore.setState({ openSessions: {} });
  });

  it("isolates visibility by session", () => {
    const first = renderHook(() => useSessionTerminalOpen("session:a:one"));
    const second = renderHook(() => useSessionTerminalOpen("session:a:two"));

    act(() => {
      useTerminalSurfaceStore.getState().setSessionOpen("session:a:one", true);
    });

    expect(first.result.current).toBe(true);
    expect(second.result.current).toBe(false);
  });

  it("toggles only the selected session", () => {
    const store = useTerminalSurfaceStore.getState();
    store.toggleSession("session:a:one");
    store.toggleSession("session:a:two");
    store.toggleSession("session:a:one");

    expect(useTerminalSurfaceStore.getState().openSessions).toEqual({
      "session:a:two": true,
    });
  });

  it("migrates an open draft to its persisted session", () => {
    const store = useTerminalSurfaceStore.getState();
    store.setSessionOpen("session:a:new", true);
    store.migrateSession("session:a:new", "session:a:real");

    expect(useTerminalSurfaceStore.getState().openSessions).toEqual({
      "session:a:real": true,
    });
  });

  it("does not overwrite state when the source is closed", () => {
    const store = useTerminalSurfaceStore.getState();
    store.setSessionOpen("session:a:real", true);
    const before = useTerminalSurfaceStore.getState().openSessions;
    store.migrateSession("session:a:new", "session:a:real");

    expect(useTerminalSurfaceStore.getState().openSessions).toBe(before);
  });

  it("removes deleted session state", () => {
    const store = useTerminalSurfaceStore.getState();
    store.setSessionOpen("session:a:one", true);
    store.removeSession("session:a:one");

    expect(useTerminalSurfaceStore.getState().openSessions).toEqual({});
  });
});
