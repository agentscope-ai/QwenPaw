import { afterEach, describe, expect, it } from "vitest";
import {
  getActivePawAppId,
  getPawAppIdFromPath,
  setActivePawAppId,
} from "./context";

afterEach(() => setActivePawAppId(null));

describe("PawApp context", () => {
  it("extracts app ids from classic and OS-owned paths", () => {
    expect(getPawAppIdFromPath("/apps/office")).toBe("office");
    expect(getPawAppIdFromPath("/os/apps/office/settings")).toBe("office");
    expect(getPawAppIdFromPath("/console/os/apps/office")).toBe("office");
  });

  it("prefers the explicit active app context", () => {
    window.history.replaceState({}, "", "/os");
    setActivePawAppId("office");
    expect(getActivePawAppId()).toBe("office");
  });

  it("falls back to the current browser path", () => {
    window.history.replaceState({}, "", "/os/apps/reviewer");
    expect(getActivePawAppId()).toBe("reviewer");
  });
});
