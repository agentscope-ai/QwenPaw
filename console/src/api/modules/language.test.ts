/**
 * Tests for api/modules/language.ts
 *
 * Contract-guard style: verify return pass-through; cover the language
 * round-trip, the upload-limit endpoint, and the deprecated `languageApi`
 * alias pointing at the same object.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { settingsApi, languageApi } from "./language";
import { request } from "../request";

describe("settingsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getLanguage returns the saved language code", async () => {
    vi.mocked(request).mockResolvedValue({ language: "zh-CN" });
    await expect(settingsApi.getLanguage()).resolves.toEqual({
      language: "zh-CN",
    });
  });

  it("updateLanguage returns the persisted language", async () => {
    vi.mocked(request).mockResolvedValue({ language: "en" });
    await expect(settingsApi.updateLanguage("en")).resolves.toEqual({
      language: "en",
    });
  });

  it("getUploadLimit returns null when no override is configured", async () => {
    vi.mocked(request).mockResolvedValue({ upload_max_size_mb: null });
    await expect(settingsApi.getUploadLimit()).resolves.toEqual({
      upload_max_size_mb: null,
    });
  });

  it("getUploadLimit returns the numeric limit when configured", async () => {
    vi.mocked(request).mockResolvedValue({ upload_max_size_mb: 25 });
    await expect(settingsApi.getUploadLimit()).resolves.toEqual({
      upload_max_size_mb: 25,
    });
  });

  it("propagates request errors", async () => {
    vi.mocked(request).mockRejectedValue(new Error("500"));
    await expect(settingsApi.getLanguage()).rejects.toThrow("500");
  });
});

describe("languageApi (deprecated alias)", () => {
  it("is the same object reference as settingsApi", () => {
    expect(languageApi).toBe(settingsApi);
  });
});
