import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SESSION_GROUP_MODE_CHANGE_EVENT,
  getSessionGroupModePreference,
  setSessionGroupModePreference,
} from "./sessionGroupModePreference";

describe("sessionGroupModePreference", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_session_group_mode");
    vi.restoreAllMocks();
  });

  it("defaults to date grouping", () => {
    expect(getSessionGroupModePreference()).toBe("date");
  });

  it("persists each mode", () => {
    setSessionGroupModePreference("none");
    expect(getSessionGroupModePreference()).toBe("none");

    setSessionGroupModePreference("source");
    expect(getSessionGroupModePreference()).toBe("source");

    setSessionGroupModePreference("date");
    expect(getSessionGroupModePreference()).toBe("date");
    expect(localStorage.getItem("qwenpaw_session_group_mode")).toBe("date");
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("qwenpaw_session_group_mode", "nested");
    expect(getSessionGroupModePreference()).toBe("date");
  });

  it("notifies mounted lists when the preference changes", () => {
    const listener = vi.fn();
    window.addEventListener(SESSION_GROUP_MODE_CHANGE_EVENT, listener);

    setSessionGroupModePreference("none");

    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(SESSION_GROUP_MODE_CHANGE_EVENT, listener);
  });

  it("does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setSessionGroupModePreference("none")).not.toThrow();
  });
});
