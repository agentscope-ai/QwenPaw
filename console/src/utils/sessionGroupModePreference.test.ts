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

  it("defaults to source grouping", () => {
    expect(getSessionGroupModePreference()).toBe("source");
  });

  it("persists each mode", () => {
    setSessionGroupModePreference("none");
    expect(getSessionGroupModePreference()).toBe("none");

    setSessionGroupModePreference("source");
    expect(getSessionGroupModePreference()).toBe("source");
    expect(localStorage.getItem("qwenpaw_session_group_mode")).toBe("source");
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("qwenpaw_session_group_mode", "nested");
    expect(getSessionGroupModePreference()).toBe("source");
  });

  it("migrates the retired date mode to the default", () => {
    localStorage.setItem("qwenpaw_session_group_mode", "date");
    expect(getSessionGroupModePreference()).toBe("source");
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
