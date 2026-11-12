import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import GeneralSettings from "./GeneralSettings";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: "en", resolvedLanguage: "en" },
    t: (key: string) => key,
  }),
}));

describe("GeneralSettings browser title", () => {
  afterEach(() => vi.restoreAllMocks());

  beforeEach(() => {
    localStorage.removeItem("qwenpaw_console_title");
  });

  it("loads a saved title, persists edits and allows clearing it", () => {
    localStorage.setItem("qwenpaw_console_title", "Project Alpha");
    renderWithProviders(<GeneralSettings />);
    const input = screen.getByRole("textbox", {
      name: "settingsCenter.browserTitle",
    });
    expect(input).toHaveValue("Project Alpha");
    fireEvent.change(input, { target: { value: "Project Beta" } });
    expect(input).toHaveValue("Project Beta");
    expect(localStorage.getItem("qwenpaw_console_title")).toBe("Project Beta");
    fireEvent.change(input, { target: { value: "" } });
    expect(input).toHaveValue("");
    expect(localStorage.getItem("qwenpaw_console_title")).toBeNull();
  });

  it("reports failed persistence and keeps the saved title", async () => {
    localStorage.setItem("qwenpaw_console_title", "Saved Title");
    renderWithProviders(<GeneralSettings />);
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("Storage full", "QuotaExceededError");
    });
    const input = screen.getByRole("textbox", {
      name: "settingsCenter.browserTitle",
    });
    fireEvent.change(input, { target: { value: "Unsaved Title" } });
    expect(
      await screen.findByText("settingsCenter.browserTitleSaveFailed"),
    ).toBeInTheDocument();
    expect(input).toHaveValue("Saved Title");
  });
});
