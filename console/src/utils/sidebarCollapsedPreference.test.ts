import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getSidebarCollapsedPreference,
  setSidebarCollapsedPreference,
} from "./sidebarCollapsedPreference";

const STORAGE_KEY = "qwenpaw_sidebar_collapsed";

describe("sidebarCollapsedPreference", () => {
  beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    vi.restoreAllMocks();
  });

  it("defaults to expanded when nothing is stored", () => {
    expect(getSidebarCollapsedPreference()).toBe(false);
  });

  it("treats malformed stored values as expanded", () => {
    localStorage.setItem(STORAGE_KEY, "collapsed");
    expect(getSidebarCollapsedPreference()).toBe(false);
  });

  it("persists the collapsed state and clears it on expand", () => {
    setSidebarCollapsedPreference(true);
    expect(getSidebarCollapsedPreference()).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("true");

    setSidebarCollapsedPreference(false);
    expect(getSidebarCollapsedPreference()).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("does not throw when writing to storage is denied", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setSidebarCollapsedPreference(true)).not.toThrow();
    expect(getSidebarCollapsedPreference()).toBe(false);
  });

  it("does not throw when reading from storage is denied", () => {
    vi.spyOn(localStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(getSidebarCollapsedPreference()).toBe(false);
  });
});
