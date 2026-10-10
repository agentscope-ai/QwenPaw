import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { applyLanguagePreference } from "./languagePreference";

const { mockUpdateLanguage, mockChangeLanguage } = vi.hoisted(() => ({
  mockUpdateLanguage: vi.fn(),
  mockChangeLanguage: vi.fn(),
}));

vi.mock("@/api/modules/language", () => ({
  settingsApi: { updateLanguage: mockUpdateLanguage },
}));

/** Minimal stand-in for the i18next instance the helper needs. */
const fakeI18n = {
  changeLanguage: mockChangeLanguage,
} as never;

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("applyLanguagePreference", () => {
  beforeEach(() => {
    mockUpdateLanguage.mockReset();
    mockChangeLanguage.mockReset();
    mockUpdateLanguage.mockResolvedValue({ language: "vi" });
    localStorage.clear();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("switches i18next, stores locally and persists remotely", () => {
    applyLanguagePreference(fakeI18n, "vi");

    expect(mockChangeLanguage).toHaveBeenCalledWith("vi");
    expect(localStorage.getItem("language")).toBe("vi");
    expect(mockUpdateLanguage).toHaveBeenCalledWith("vi");
  });

  it("reports a rejected remote write instead of swallowing it", async () => {
    mockUpdateLanguage.mockRejectedValue(new Error("HTTP 400"));
    const onPersistError = vi.fn();

    applyLanguagePreference(fakeI18n, "vi", { onPersistError });
    await flush();

    expect(onPersistError).toHaveBeenCalledTimes(1);
    // The local switch still happened, which is exactly why the
    // rejection has to be surfaced: nothing else reveals the drift.
    expect(localStorage.getItem("language")).toBe("vi");
  });

  it("keeps the local switch when persistence is disabled", () => {
    const onPersistError = vi.fn();

    applyLanguagePreference(fakeI18n, "ja", {
      persistRemotely: false,
      onPersistError,
    });

    expect(mockChangeLanguage).toHaveBeenCalledWith("ja");
    expect(localStorage.getItem("language")).toBe("ja");
    expect(mockUpdateLanguage).not.toHaveBeenCalled();
    expect(onPersistError).not.toHaveBeenCalled();
  });
});
