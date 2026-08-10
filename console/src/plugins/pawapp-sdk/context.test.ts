import { afterEach, describe, expect, it } from "vitest";
import {
  getActivePawAppId,
  getPawAppIdFromPath,
  setActivePawAppId,
} from "./context";

afterEach(() => setActivePawAppId(null));

describe("PawApp context", () => {
  it("extracts app ids from classic console paths", () => {
    expect(getPawAppIdFromPath("/apps/office")).toBe("office");
    expect(getPawAppIdFromPath("/console/apps/office/settings")).toBe("office");
  });

  it("does not infer app context from unsupported OS subpaths", () => {
    expect(getPawAppIdFromPath("/os/apps/office/settings")).toBe("");
    expect(getPawAppIdFromPath("/console/os/apps/office")).toBe("");
  });

  it("prefers the explicit active app context", () => {
    window.history.replaceState({}, "", "/os");
    setActivePawAppId("office");
    expect(getActivePawAppId()).toBe("office");
  });

  it("falls back to the current classic browser path", () => {
    window.history.replaceState({}, "", "/apps/reviewer");
    expect(getActivePawAppId()).toBe("reviewer");
  });
});
