/**
 * filesSurfaceStore — reducer branch coverage supplement: preview/workspace
 * transitions, expand/collapse, no-op migration guards and the per-session
 * drawer hook.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { CLOSED_FILES_DRAWER } from "../features/files-workspace/filesDrawerState";
import {
  useFilesSurfaceStore,
  useSessionFilesDrawer,
} from "./filesSurfaceStore";

const target = {
  source: "workspace" as const,
  path: "src/app.ts",
  root: "project" as const,
};
const otherTarget = {
  source: "workspace" as const,
  path: "src/other.ts",
  root: "project" as const,
};

describe("filesSurfaceStore branches", () => {
  beforeEach(() => {
    useFilesSurfaceStore.setState({ sessionDrawers: {} });
  });

  it("re-targets a preview while staying in preview mode", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_PREVIEW",
      target,
      trigger: null,
    });
    store.dispatchSession("s", {
      type: "OPEN_PREVIEW",
      target: otherTarget,
      trigger: null,
    });
    expect(useFilesSurfaceStore.getState().sessionDrawers["s"]).toMatchObject({
      kind: "preview",
      target: otherTarget,
      trigger: null,
    });
  });

  it("keeps workspace mode when opening a preview inside it", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    store.dispatchSession("s", {
      type: "OPEN_PREVIEW",
      target: otherTarget,
      trigger: null,
    });
    const state = useFilesSurfaceStore.getState().sessionDrawers["s"];
    expect(state.kind).toBe("workspace");
    expect((state as { target: unknown }).target).toEqual(otherTarget);
  });

  it("expands a preview into a workspace", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_PREVIEW",
      target,
      trigger: null,
    });
    store.dispatchSession("s", { type: "EXPAND_WORKSPACE" });
    expect(useFilesSurfaceStore.getState().sessionDrawers["s"]).toMatchObject({
      kind: "workspace",
      target,
    });
  });

  it("leaves a workspace untouched on EXPAND_WORKSPACE", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    const before = useFilesSurfaceStore.getState().sessionDrawers["s"];
    store.dispatchSession("s", { type: "EXPAND_WORKSPACE" });
    expect(useFilesSurfaceStore.getState().sessionDrawers["s"]).toBe(before);
  });

  it("collapses a workspace with a target back to preview", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    store.dispatchSession("s", { type: "COLLAPSE_TO_PREVIEW" });
    expect(useFilesSurfaceStore.getState().sessionDrawers["s"]).toMatchObject({
      kind: "preview",
      target,
    });
  });

  it("closes the drawer on CLOSE", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    store.dispatchSession("s", { type: "CLOSE" });
    expect(useFilesSurfaceStore.getState().sessionDrawers["s"]).toEqual(
      CLOSED_FILES_DRAWER,
    );
  });

  it("migrateSession is a no-op for identical keys", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    const drawers = useFilesSurfaceStore.getState().sessionDrawers;
    store.migrateSession("s", "s");
    expect(useFilesSurfaceStore.getState().sessionDrawers).toBe(drawers);
  });

  it("migrateSession is a no-op when the source drawer is missing", () => {
    const drawers = useFilesSurfaceStore.getState().sessionDrawers;
    useFilesSurfaceStore.getState().migrateSession("missing", "target");
    expect(useFilesSurfaceStore.getState().sessionDrawers).toBe(drawers);
  });

  it("removeSession drops the drawer", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    store.removeSession("s");
    expect(useFilesSurfaceStore.getState().sessionDrawers["s"]).toBeUndefined();
  });

  it("removeSession is a no-op for unknown keys", () => {
    const drawers = useFilesSurfaceStore.getState().sessionDrawers;
    useFilesSurfaceStore.getState().removeSession("missing");
    expect(useFilesSurfaceStore.getState().sessionDrawers).toBe(drawers);
  });
});

describe("useSessionFilesDrawer", () => {
  beforeEach(() => {
    useFilesSurfaceStore.setState({ sessionDrawers: {} });
  });

  it("returns the closed state for sessions without a drawer", () => {
    const { result } = renderHook(() => useSessionFilesDrawer("s"));
    expect(result.current).toEqual(CLOSED_FILES_DRAWER);
  });

  it("reflects the stored drawer for the session", () => {
    useFilesSurfaceStore.getState().dispatchSession("s", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });
    const { result } = renderHook(() => useSessionFilesDrawer("s"));
    expect(result.current).toMatchObject({ kind: "workspace", target });
  });
});
