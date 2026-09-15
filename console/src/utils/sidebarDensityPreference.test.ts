import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SIDEBAR_DENSITY_CHANGE_EVENT,
  getSidebarDensityPreference,
  setSidebarDensityPreference,
} from "./sidebarDensityPreference";

describe("sidebarDensityPreference", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_sidebar_density");
    vi.restoreAllMocks();
  });

  it("defaults to auto", () => {
    expect(getSidebarDensityPreference()).toBe("auto");
  });

  it("persists each density", () => {
    setSidebarDensityPreference("compact");
    expect(getSidebarDensityPreference()).toBe("compact");

    setSidebarDensityPreference("standard");
    expect(getSidebarDensityPreference()).toBe("standard");

    setSidebarDensityPreference("auto");
    expect(getSidebarDensityPreference()).toBe("auto");
    expect(localStorage.getItem("qwenpaw_sidebar_density")).toBe("auto");
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("qwenpaw_sidebar_density", "huge");
    expect(getSidebarDensityPreference()).toBe("auto");
  });

  it("notifies mounted surfaces when the preference changes", () => {
    const listener = vi.fn();
    window.addEventListener(SIDEBAR_DENSITY_CHANGE_EVENT, listener);

    setSidebarDensityPreference("compact");

    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(SIDEBAR_DENSITY_CHANGE_EVENT, listener);
  });

  it("does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setSidebarDensityPreference("compact")).not.toThrow();
  });
});
