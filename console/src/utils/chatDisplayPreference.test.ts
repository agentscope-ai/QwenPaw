import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAssistantMessageDisplayPreference,
  getToolDisplayPreference,
  setAssistantMessageDisplayPreference,
  setToolDisplayPreference,
} from "./chatDisplayPreference";

describe("chatDisplayPreference", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_tool_calls_default_expanded");
    localStorage.removeItem("qwenpaw_tool_display_mode");
    localStorage.removeItem("qwenpaw_assistant_message_display_mode");
    vi.restoreAllMocks();
  });

  it("preserves the current display behavior by default", () => {
    expect(getToolDisplayPreference()).toBe("current");
    expect(getAssistantMessageDisplayPreference()).toBe("result-collapsed");
  });

  it("persists and clears the tool display preference", () => {
    setToolDisplayPreference("raw-input-output");
    expect(getToolDisplayPreference()).toBe("raw-input-output");

    setToolDisplayPreference("current");
    expect(getToolDisplayPreference()).toBe("current");
    expect(localStorage.getItem("qwenpaw_tool_display_mode")).toBeNull();
  });

  it("clears the superseded tool expansion preference", () => {
    localStorage.setItem("qwenpaw_tool_calls_default_expanded", "true");

    setToolDisplayPreference("raw-input-output");

    expect(
      localStorage.getItem("qwenpaw_tool_calls_default_expanded"),
    ).toBeNull();
  });

  it("persists non-default assistant display modes", () => {
    setAssistantMessageDisplayPreference("expanded");
    expect(getAssistantMessageDisplayPreference()).toBe("expanded");

    setAssistantMessageDisplayPreference("process-collapsed");
    expect(getAssistantMessageDisplayPreference()).toBe("process-collapsed");
  });

  it("clears storage when result collapse is restored", () => {
    setAssistantMessageDisplayPreference("expanded");
    setAssistantMessageDisplayPreference("result-collapsed");

    expect(getAssistantMessageDisplayPreference()).toBe("result-collapsed");
    expect(
      localStorage.getItem("qwenpaw_assistant_message_display_mode"),
    ).toBeNull();
  });

  it("ignores an invalid stored assistant display mode", () => {
    localStorage.setItem("qwenpaw_assistant_message_display_mode", "invalid");

    expect(getAssistantMessageDisplayPreference()).toBe("result-collapsed");
  });

  it("does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => setToolDisplayPreference("raw-input-output")).not.toThrow();
    expect(() =>
      setAssistantMessageDisplayPreference("expanded"),
    ).not.toThrow();
  });
});
