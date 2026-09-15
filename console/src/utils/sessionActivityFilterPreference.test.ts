import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SESSION_ACTIVITY_FILTER_CHANGE_EVENT,
  getSessionActivityFilterPreference,
  setSessionActivityFilterPreference,
} from "./sessionActivityFilterPreference";

describe("sessionActivityFilterPreference", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_session_activity_filter");
    vi.restoreAllMocks();
  });

  it("defaults to all", () => {
    expect(getSessionActivityFilterPreference()).toBe("all");
  });

  it("persists each range", () => {
    setSessionActivityFilterPreference("today");
    expect(getSessionActivityFilterPreference()).toBe("today");

    setSessionActivityFilterPreference("week");
    expect(getSessionActivityFilterPreference()).toBe("week");

    setSessionActivityFilterPreference("month");
    expect(getSessionActivityFilterPreference()).toBe("month");
    expect(localStorage.getItem("qwenpaw_session_activity_filter")).toBe(
      "month",
    );
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("qwenpaw_session_activity_filter", "year");
    expect(getSessionActivityFilterPreference()).toBe("all");
  });

  it("notifies mounted lists when the preference changes", () => {
    const listener = vi.fn();
    window.addEventListener(SESSION_ACTIVITY_FILTER_CHANGE_EVENT, listener);

    setSessionActivityFilterPreference("today");

    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(SESSION_ACTIVITY_FILTER_CHANGE_EVENT, listener);
  });

  it("does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setSessionActivityFilterPreference("week")).not.toThrow();
  });
});
