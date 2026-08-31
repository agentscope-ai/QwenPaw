import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getChatWideModePreference,
  setChatWideModePreference,
} from "./chatLayoutPreference";

describe("chatLayoutPreference", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_chat_wide_mode");
    vi.restoreAllMocks();
  });

  it("defaults to normal width", () => {
    expect(getChatWideModePreference()).toBe(false);
  });

  it("persists and clears wide mode", () => {
    setChatWideModePreference(true);
    expect(getChatWideModePreference()).toBe(true);

    setChatWideModePreference(false);
    expect(getChatWideModePreference()).toBe(false);
    expect(localStorage.getItem("qwenpaw_chat_wide_mode")).toBeNull();
  });

  it("does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setChatWideModePreference(true)).not.toThrow();
  });
});
