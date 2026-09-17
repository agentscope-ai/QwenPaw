import { beforeEach, describe, expect, it } from "vitest";
import { useFilesSurfaceStore } from "./filesSurfaceStore";

const target = {
  source: "workspace" as const,
  path: "src/app.ts",
  root: "project" as const,
};

describe("filesSurfaceStore", () => {
  beforeEach(() => {
    useFilesSurfaceStore.setState({ sessionDrawers: {} });
  });

  it("keeps drawer state isolated per Session scope", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("session:a:s1", {
      type: "OPEN_PREVIEW",
      target,
      trigger: null,
    });

    expect(
      useFilesSurfaceStore.getState().sessionDrawers["session:a:s1"],
    ).toMatchObject({ kind: "preview", target });
    expect(
      useFilesSurfaceStore.getState().sessionDrawers["session:a:s2"],
    ).toBeUndefined();
  });

  it("migrates the drawer when a temporary Session id resolves", () => {
    const store = useFilesSurfaceStore.getState();
    store.dispatchSession("session:a:new", {
      type: "OPEN_WORKSPACE",
      target,
      trigger: null,
    });

    store.migrateSession("session:a:new", "session:a:uuid");

    const drawers = useFilesSurfaceStore.getState().sessionDrawers;
    expect(drawers["session:a:new"]).toBeUndefined();
    expect(drawers["session:a:uuid"]).toMatchObject({
      kind: "workspace",
      target,
    });
  });
});
