import { describe, expect, it } from "vitest";
import { CLOSED_FILES_DRAWER, filesDrawerReducer } from "./filesDrawerState";

const target = { source: "workspace" as const, path: "src/app.py" };

describe("filesDrawerReducer", () => {
  it("opens Preview before a Chat-origin workspace", () => {
    const preview = filesDrawerReducer(CLOSED_FILES_DRAWER, {
      type: "OPEN_PREVIEW",
      target,
      trigger: null,
    });
    expect(preview.kind).toBe("preview");
    expect(
      filesDrawerReducer(preview, { type: "EXPAND_WORKSPACE" }),
    ).toMatchObject({ kind: "workspace", origin: "chat", target });
  });

  it("expands a message attachment into the same workspace", () => {
    const attachment = {
      source: "attachment" as const,
      path: "LICENSE",
      artifactUrl: "/api/files/preview/LICENSE",
    };
    const preview = filesDrawerReducer(CLOSED_FILES_DRAWER, {
      type: "OPEN_PREVIEW",
      target: attachment,
      trigger: null,
    });

    expect(
      filesDrawerReducer(preview, { type: "EXPAND_WORKSPACE" }),
    ).toMatchObject({
      kind: "workspace",
      origin: "chat",
      target: attachment,
    });
  });

  it("separates collapse from direct close", () => {
    const workspace = {
      kind: "workspace" as const,
      origin: "chat" as const,
      target,
      trigger: null,
    };
    expect(
      filesDrawerReducer(workspace, {
        type: "COLLAPSE_TO_PREVIEW",
      }),
    ).toMatchObject({ kind: "preview", target });
    expect(filesDrawerReducer(workspace, { type: "CLOSE" })).toEqual(
      CLOSED_FILES_DRAWER,
    );
  });

  it("opens direct Files without an intermediate Preview", () => {
    expect(
      filesDrawerReducer(CLOSED_FILES_DRAWER, {
        type: "OPEN_FILES",
        trigger: null,
      }),
    ).toMatchObject({ kind: "workspace", origin: "files" });
  });

  it("opens an editor reference directly in the Chat workspace", () => {
    const lineTarget = { ...target, line: 12, endLine: 18 };
    expect(
      filesDrawerReducer(CLOSED_FILES_DRAWER, {
        type: "OPEN_WORKSPACE",
        target: lineTarget,
        trigger: null,
      }),
    ).toMatchObject({
      kind: "workspace",
      origin: "chat",
      target: lineTarget,
    });
  });
});
