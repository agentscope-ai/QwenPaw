import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  getApiUrl,
  getApiToken,
  setAuthToken,
  clearAuthToken,
  updateBrowserSession,
} from "./config";

// VITE_API_BASE_URL / TOKEN are declared globals in config.ts — set via globalThis
const setViteBase = (v: string) => {
  (globalThis as any).VITE_API_BASE_URL = v;
};
const setToken = (v: string) => {
  (globalThis as any).TOKEN = v;
};

describe("getApiUrl", () => {
  beforeEach(() => setViteBase(""));

  it("prepends /api prefix when base is empty", () => {
    expect(getApiUrl("/models")).toBe("/api/models");
  });

  it("auto-prepends / when path does not start with /", () => {
    expect(getApiUrl("models")).toBe("/api/models");
  });

  it("correctly concatenates when base URL is set", () => {
    setViteBase("http://localhost:8088");
    expect(getApiUrl("/models")).toBe("http://localhost:8088/api/models");
  });

  it("correctly handles nested paths", () => {
    expect(getApiUrl("/models/openai/config")).toBe(
      "/api/models/openai/config",
    );
  });
});

describe("getApiToken", () => {
  beforeEach(() => {
    localStorage.clear();
    setToken("");
  });

  it("returns token from localStorage when present", () => {
    localStorage.setItem("qwenpaw_auth_token", "stored-token");
    expect(getApiToken()).toBe("stored-token");
  });

  it("falls back to TOKEN global variable when localStorage has no token", () => {
    setToken("build-time-token");
    expect(getApiToken()).toBe("build-time-token");
  });

  it("returns empty string when neither is set", () => {
    expect(getApiToken()).toBe("");
  });
});

describe("setAuthToken / clearAuthToken", () => {
  beforeEach(() => localStorage.clear());

  it("setAuthToken writes to localStorage", () => {
    setAuthToken("my-token");
    expect(localStorage.getItem("qwenpaw_auth_token")).toBe("my-token");
  });

  it("clearAuthToken clears cross-origin browser grants", async () => {
    setViteBase("http://localhost:8088");
    const request = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response());
    localStorage.setItem("qwenpaw_auth_token", "my-token");
    clearAuthToken();
    expect(localStorage.getItem("qwenpaw_auth_token")).toBeNull();
    await updateBrowserSession(async () => undefined);
    expect(request).toHaveBeenCalledWith(
      "http://localhost:8088/api/hub/pawapps/sessions",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
    request.mockRestore();
    setViteBase("");
  });

  it("getApiToken returns empty string after clearAuthToken", () => {
    setToken("");
    setAuthToken("my-token");
    clearAuthToken();
    expect(getApiToken()).toBe("");
  });
});
